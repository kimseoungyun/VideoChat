import asyncio
import base64
import hashlib
import hmac
from unittest.mock import patch
from uuid import uuid4
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from channels.testing import WebsocketCommunicator
from channels.auth import AuthMiddlewareStack
from channels.routing import URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from . import limits
from .routing import websocket_urlpatterns
from .matchmaking import Matchmaker
from .models import Report
from .testing import isolated_prefix


class RtcConfigTests(SimpleTestCase):
    def setUp(self):
        isolated_prefix(self)

    @override_settings(TURN_URLS=['turn:relay.example.test:3478'], TURN_SECRET='test-only-secret')
    def test_credentials_are_refreshed_and_never_cached(self):
        with patch('chat.views.time.time', return_value=1000):
            first = self.client.get('/chat/rtc-config/')
        with patch('chat.views.time.time', return_value=5000):
            second = self.client.get('/chat/rtc-config/')
        self.assertEqual(first.status_code, 200)
        self.assertIn('no-store', first['Cache-Control'])
        self.assertIn('private', first['Cache-Control'])
        old = first.json()['iceServers'][1]
        new = second.json()['iceServers'][1]
        self.assertTrue(old['username'].startswith('4600:'))
        self.assertTrue(new['username'].startswith('8600:'))
        self.assertNotEqual(old['credential'], new['credential'])
        expected = base64.b64encode(hmac.new(b'test-only-secret', new['username'].encode(), hashlib.sha1).digest()).decode()
        self.assertEqual(new['credential'], expected)
        self.assertNotContains(second, 'test-only-secret')
        self.assertNotContains(self.client.get('/chat/'), 'credential')

    @override_settings(TURN_URLS=[], TURN_SECRET='')
    def test_stun_only_and_get_only(self):
        self.assertEqual(len(self.client.get('/chat/rtc-config/').json()['iceServers']), 1)
        self.assertEqual(self.client.post('/chat/rtc-config/').status_code, 405)


class MatchmakingTests(SimpleTestCase):
    async def async_case(self, callback):
        with override_settings(MATCHMAKING_PREFIX='test:' + uuid4().hex + ':'):
            matcher = Matchmaker()
            try:
                await callback(matcher)
            finally:
                keys = [k async for k in matcher.redis.scan_iter(match=settings.MATCHMAKING_PREFIX + '*')]
                if keys:
                    await matcher.redis.delete(*keys)

    async def test_concurrent_200_clients_are_exactly_100_pairs(self):
        async def run(m):
            await asyncio.gather(*(m.transition('join', str(i)) for i in range(200)))
            states = await asyncio.gather(*(m.transition('state', str(i)) for i in range(200)))
            rooms = {}
            for i, state in enumerate(states):
                self.assertEqual(state[0], 'matched')
                self.assertNotEqual(state[1], str(i))
                self.assertEqual(states[int(state[1])][1], str(i))
                rooms.setdefault(state[2], []).append(i)
            self.assertEqual(len(rooms), 100)
            self.assertTrue(all(len(pair) == 2 for pair in rooms.values()))
        await self.async_case(run)

    async def test_duplicate_join_skip_and_disconnect(self):
        async def run(m):
            self.assertEqual(await m.transition('join', 'a'), ['waiting'])
            self.assertEqual(await m.transition('join', 'a'), ['waiting'])
            self.assertEqual(await m.redis.zcard(settings.MATCHMAKING_PREFIX + 'queue'), 1)
            match = await m.transition('join', 'b')
            self.assertEqual(match[0], 'new_match')
            self.assertEqual((await m.transition('leave', 'a'))[0], 'b')
            self.assertEqual(await m.transition('state', 'b'), ['idle'])
            self.assertEqual(await m.transition('join', 'a'), ['waiting'])
            self.assertEqual(await m.transition('join', 'b'), ['waiting'])
            other = await m.transition('join', 'c')
            self.assertEqual(other[0], 'new_match')
            self.assertNotEqual(other[2], match[2])
            await m.transition('leave', 'c')
            await m.transition('leave', 'c')
        await self.async_case(run)

    async def test_exclusion_survives_next_after_peer_already_left(self):
        async def run(m):
            await m.transition('join', 'a')
            await m.transition('join', 'b')
            await m.transition('leave', 'a')  # a ends the match (report or stop)
            await m.transition('leave', 'a')  # then presses next: leave, join
            await m.transition('leave', 'b')  # b presses next after a already left
            self.assertEqual(await m.transition('join', 'a'), ['waiting'])
            self.assertEqual(await m.transition('join', 'b'), ['waiting'])
        await self.async_case(run)

    async def test_expired_peer_and_queue_are_reclaimed(self):
        async def run(m):
            from django.conf import settings
            await m.transition('join', 'a')
            await m.redis.delete(settings.MATCHMAKING_PREFIX + 'member:a')
            self.assertEqual(await m.transition('join', 'b'), ['waiting'])
            await m.transition('join', 'c')
            await m.redis.delete(settings.MATCHMAKING_PREFIX + 'member:c')
            self.assertEqual(await m.transition('state', 'b'), ['idle'])
        await self.async_case(run)


@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class SignalingTests(SimpleTestCase):
    async def test_missing_presence_requires_reconnect(self):
        app = AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        client = WebsocketCommunicator(app, '/ws/chat/')
        await client.connect()
        await client.receive_json_from()
        await client.send_json_to({'type': 'ping'})
        self.assertEqual((await client.receive_output())['code'], 1012)
        await client.disconnect()

    async def test_oversized_frame_is_rejected(self):
        app = AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        client = WebsocketCommunicator(app, '/ws/chat/')
        await client.connect()
        await client.receive_json_from()
        await client.send_to(text_data='x' * 32769)
        self.assertEqual((await client.receive_output())['code'], 1009)
        await client.disconnect()

    async def test_health_checks_redis(self):
        response = await self.async_client.get('/health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    async def test_match_chat_validation_stale_signal_and_departure(self):
        with override_settings(MATCHMAKING_PREFIX='test:' + uuid4().hex + ':'):
            app = AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
            clients = [WebsocketCommunicator(app, '/ws/chat/') for _ in range(3)]
            try:
                for client in clients:
                    self.assertTrue((await client.connect())[0])
                    self.assertEqual((await client.receive_json_from())['type'], 'ready')
                a, b, c = clients
                await a.send_json_to({'type': 'join'})
                self.assertEqual((await a.receive_json_from())['type'], 'waiting')
                await b.send_json_to({'type': 'join'})
                first, second = await a.receive_json_from(), await b.receive_json_from()
                self.assertEqual(first['match_id'], second['match_id'])
                self.assertNotEqual(first['initiator'], second['initiator'])
                await c.send_json_to({'type': 'join'})
                self.assertEqual((await c.receive_json_from())['type'], 'waiting')
                await a.send_json_to({'type': 'chat', 'match_id': first['match_id'], 'message': '<hello>'})
                self.assertEqual((await b.receive_json_from())['message'], '<hello>')
                await a.send_to(text_data='not-json')
                self.assertEqual((await a.receive_json_from())['type'], 'error')
                await a.send_json_to({'type': 'media', 'match_id': first['match_id'], 'audio': 'bad', 'video': True})
                self.assertEqual((await a.receive_json_from())['type'], 'error')
                await a.send_json_to({'type': 'signal', 'match_id': 'old-match', 'signal': {'candidate': {}}})
                self.assertTrue(await b.receive_nothing(timeout=0.05))
                self.assertTrue(await c.receive_nothing(timeout=0.05))
                await asyncio.sleep(1)  # join/next cooldown
                await b.send_json_to({'type': 'next'})
                rematch = await b.receive_json_from()
                self.assertEqual(rematch['type'], 'matched')
                self.assertEqual((await c.receive_json_from())['match_id'], rematch['match_id'])
                self.assertEqual((await a.receive_json_from())['type'], 'peer_left')
                await a.send_json_to({'type': 'chat', 'match_id': first['match_id'], 'message': 'stale'})
                self.assertTrue(await b.receive_nothing(timeout=0.1))
                self.assertTrue(await c.receive_nothing(timeout=0.05))
                await c.send_json_to({'type': 'leave'})
                self.assertEqual((await c.receive_json_from())['type'], 'idle')
                self.assertEqual((await b.receive_json_from())['type'], 'peer_left')
            finally:
                for client in clients:
                    await client.disconnect()

    async def test_origin_rejected(self):
        with override_settings(ALLOWED_HOSTS=['localhost'], DEBUG=False):
            app = AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(websocket_urlpatterns)))
            client = WebsocketCommunicator(app, '/ws/chat/', headers=[(b'origin', b'https://evil.example')])
            self.assertFalse((await client.connect())[0])
            await client.disconnect()

    def test_lobby_and_legacy_routes(self):
        response = self.client.get('/chat/')
        self.assertContains(response, 'rtc-config')
        self.assertContains(response, '대화 시작')
        self.assertRedirects(self.client.get('/chat/start_chat/'), '/chat/')
        self.assertEqual(self.client.get('/chat/12/').status_code, 200)


def communicator(ip):
    client = WebsocketCommunicator(AuthMiddlewareStack(URLRouter(websocket_urlpatterns)), '/ws/chat/')
    client.scope['client'] = [ip, 50000]
    return client


@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class ModerationTests(TransactionTestCase):
    def setUp(self):
        isolated_prefix(self)

    async def pair(self, a, b):
        await a.send_json_to({'type': 'join'})
        self.assertEqual((await a.receive_json_from())['type'], 'waiting')
        await b.send_json_to({'type': 'join'})
        first, second = await a.receive_json_from(), await b.receive_json_from()
        self.assertEqual(first['match_id'], second['match_id'])
        return first['match_id']

    async def test_report_ends_match_blocks_pair_and_is_stored(self):
        clients = [communicator(f'10.0.0.{i}') for i in (1, 2, 3)]
        try:
            for client in clients:
                await client.connect()
                await client.receive_json_from()
            a, b, c = clients
            match = await self.pair(a, b)
            await a.send_json_to({'type': 'report', 'match_id': match, 'reason': 'unknown'})
            self.assertEqual((await a.receive_json_from())['type'], 'error')
            await a.send_json_to({'type': 'report', 'match_id': match, 'reason': 'harassment'})
            self.assertEqual((await a.receive_json_from())['type'], 'reported')
            self.assertEqual((await b.receive_json_from())['type'], 'peer_left')
            await a.send_json_to({'type': 'report', 'match_id': match, 'reason': 'spam'})
            self.assertEqual((await a.receive_json_from())['type'], 'error')  # once per match
            await asyncio.sleep(1)
            for client in (a, b):  # blocked identities wait instead of re-pairing
                await client.send_json_to({'type': 'join'})
                self.assertEqual((await client.receive_json_from())['type'], 'waiting')
            await c.send_json_to({'type': 'join'})
            self.assertEqual((await c.receive_json_from())['type'], 'matched')
            report = await Report.objects.aget()
            self.assertEqual((report.reason, report.banned), ('harassment', False))
            self.assertNotIn('10.0.0', report.reported + report.reporter)
        finally:
            for client in clients:
                await client.disconnect()

    async def test_report_between_shared_ip_guests_does_not_block_the_ip(self):
        clients = [communicator('10.0.0.7') for _ in range(4)]
        try:
            for client in clients:
                await client.connect()
                await client.receive_json_from()
            a, b, c, d = clients
            match = await self.pair(a, b)
            await a.send_json_to({'type': 'report', 'match_id': match, 'reason': 'spam'})
            self.assertEqual((await a.receive_json_from())['type'], 'reported')
            self.assertFalse((await Report.objects.aget()).banned)
            await self.pair(c, d)  # the shared identity can still match itself
        finally:
            for client in clients:
                await client.disconnect()

    @override_settings(REPORT_BAN_THRESHOLD=2)
    async def test_distinct_reporters_ban_target(self):
        m = Matchmaker()
        self.assertFalse(await m.report('ipA', 'ipT'))
        self.assertFalse(await m.report('ipA', 'ipT'))  # the same reporter counts once
        self.assertTrue(await m.report('ipB', 'ipT'))
        state = await m.transition('join', 'target', 'ipT')
        self.assertEqual(state[0], 'banned')
        self.assertGreater(int(state[1]), 0)
        self.assertEqual(await m.transition('join', 'other', 'ipC'), ['waiting'])

    @override_settings(WS_MAX_PER_IP=2)
    async def test_connection_limit_per_ip(self):
        clients = [communicator('10.0.0.9') for _ in range(3)] + [communicator('10.0.0.10')]
        try:
            for client in clients[:2]:
                await client.connect()
                self.assertEqual((await client.receive_json_from())['type'], 'ready')
            await clients[2].connect()
            self.assertEqual((await clients[2].receive_output())['code'], 4029)
            await clients[3].connect()
            self.assertEqual((await clients[3].receive_json_from())['type'], 'ready')
            await clients[0].disconnect()
            replacement = communicator('10.0.0.9')
            clients.append(replacement)
            await replacement.connect()
            self.assertEqual((await replacement.receive_json_from())['type'], 'ready')
        finally:
            for client in clients:
                await client.disconnect()


class HttpLimitTests(TestCase):
    def setUp(self):
        isolated_prefix(self)

    def test_login_failures_lock_the_account_even_for_the_right_password(self):
        User.objects.create_user('tester', password='test-password-123!')
        for _ in range(settings.LOGIN_FAILURES_PER_USER):
            self.assertEqual(self.client.post('/login/', {'username': 'tester', 'password': 'wrong'}).status_code, 200)
        response = self.client.post('/login/', {'username': 'Tester', 'password': 'test-password-123!'})
        self.assertEqual(response.status_code, 429)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_successful_login_resets_the_account_counter(self):
        User.objects.create_user('tester', password='test-password-123!')
        for _ in range(settings.LOGIN_FAILURES_PER_USER - 1):
            self.client.post('/login/', {'username': 'tester', 'password': 'wrong'})
        self.assertEqual(self.client.post('/login/', {'username': 'tester', 'password': 'test-password-123!'}).status_code, 302)
        self.client.post('/logout/')
        self.client.post('/login/', {'username': 'tester', 'password': 'wrong'})
        self.assertEqual(self.client.post('/login/', {'username': 'tester', 'password': 'test-password-123!'}).status_code, 302)

    @override_settings(SIGNUPS_PER_IP=1)
    def test_signup_rate(self):
        data = {'username': 'first', 'email': 'a@example.com', 'password1': 'A-long-new-password-789!',
                'password2': 'A-long-new-password-789!'}
        self.assertEqual(self.client.post('/signup/', data).status_code, 302)
        data.update(username='second', email='b@example.com')
        self.assertEqual(self.client.post('/signup/', data).status_code, 429)
        self.assertEqual(User.objects.count(), 1)

    @override_settings(RTC_CONFIG_PER_IP=2)
    def test_rtc_config_rate(self):
        codes = [self.client.get('/chat/rtc-config/').status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_metrics_require_token_outside_debug(self):
        with override_settings(DEBUG=False, METRICS_TOKEN=''):
            self.assertEqual(self.client.get('/metrics/').status_code, 404)
        with override_settings(DEBUG=False, METRICS_TOKEN='secret-token'):
            self.assertEqual(self.client.get('/metrics/', HTTP_AUTHORIZATION='Bearer wrong').status_code, 404)
            limits.count('matches_total', 3)
            response = self.client.get('/metrics/', HTTP_AUTHORIZATION='Bearer secret-token')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'videochat_matches_total 3')
        self.assertContains(response, '# TYPE videochat_match_wait_seconds histogram')
        self.assertContains(response, 'videochat_queue_waiting 0')
