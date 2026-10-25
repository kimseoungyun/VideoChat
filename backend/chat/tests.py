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
from .consumers import ChatConsumer
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

    async def test_unpair_requeues_both_without_blocking(self):
        async def run(m):
            await m.transition('join', 'a')
            match = await m.transition('join', 'b')
            self.assertEqual(match[0], 'new_match')
            self.assertEqual(await m.transition('unpair', 'b'), ['waiting'])
            self.assertEqual(await m.transition('state', 'a'), ['waiting'])
            self.assertEqual(await m.transition('state', 'b'), ['waiting'])
            self.assertEqual((await m.transition('join', 'c'))[0], 'new_match')
            again = await m.transition('join', 'd')
            self.assertEqual(again[0], 'new_match')
            self.assertEqual({again[1], (await m.transition('state', 'c'))[1]}, {'a', 'b'})
        await self.async_case(run)

    async def test_release_requeues_peer_so_caller_can_retry(self):
        async def run(m):
            await m.transition('join', 'a')
            first = await m.transition('join', 'b')
            self.assertEqual(await m.transition('release', 'b'), ['idle'])
            self.assertEqual(await m.transition('state', 'a'), ['waiting'])
            retry = await m.transition('join', 'b')
            self.assertEqual(retry[:2], ['new_match', 'a'])
            self.assertNotEqual(retry[2], first[2])
        await self.async_case(run)

    @override_settings(MATCH_RELAX_SECONDS=1)
    async def test_preferences_share_interest_language_and_relax(self):
        async def run(m):
            self.assertEqual(await m.join('d', 'w1', 'ko', ['music']), ['waiting'])
            self.assertEqual(await m.join('e', 'w2', 'ko', ['games']), ['waiting'])  # nothing shared
            match = await m.join('f', 'w3', 'ko', ['games', 'music'])  # ties with d and e: oldest wins
            self.assertEqual(match[1], 'd')
            self.assertEqual((await m.transition('state', 'f'))[4], 'music')
            self.assertEqual(await m.join('k', 'w4', 'en', []), ['waiting'])  # e is ko
            self.assertEqual((await m.join('n', 'w5', '', []))[:2], ['new_match', 'k'])  # no language = any
            self.assertEqual(await m.join('p', 'w6', 'en', []), ['waiting'])
            await asyncio.sleep(1.1)
            relaxed = await m.join('e', 'w2', 'ko', ['games'])  # rescan from the queue after relaxing
            self.assertEqual(relaxed[:2], ['new_match', 'p'])
            fields = await m.redis.hgetall(settings.MATCHMAKING_PREFIX + 'metrics')
            self.assertEqual(fields['matches_by_preference_total{kind="shared"}'], '1')
            self.assertEqual(fields['matches_by_preference_total{kind="relaxed"}'], '1')
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

    async def flaky_match_notices(self, failures):
        """Make the first `failures` pair.ready sends fail as if the inbox stayed full."""
        real, left = ChatConsumer.deliver, [failures]

        async def deliver(consumer, channel, message):
            if message['type'] == 'pair.ready' and left[0]:
                left[0] -= 1
                return False
            return await real(consumer, channel, message)
        return patch.object(ChatConsumer, 'deliver', deliver)

    async def test_undelivered_match_notice_is_retried(self):
        clients = [communicator(f'10.0.1.{i}') for i in (1, 2)]
        try:
            with await self.flaky_match_notices(2):
                for client in clients:
                    await client.connect()
                    await client.receive_json_from()
                await self.pair(*clients)  # third attempt reaches the peer
        finally:
            for client in clients:
                await client.disconnect()

    async def test_exhausted_retries_requeue_both(self):
        clients = [communicator(f'10.0.2.{i}') for i in (1, 2, 3)]
        try:
            with await self.flaky_match_notices(3):
                for client in clients:
                    await client.connect()
                    await client.receive_json_from()
                a, b, c = clients
                await a.send_json_to({'type': 'join'})
                self.assertEqual((await a.receive_json_from())['type'], 'waiting')
                await b.send_json_to({'type': 'join'})
                self.assertEqual((await b.receive_json_from())['type'], 'waiting')
                self.assertTrue(await a.receive_nothing(timeout=0.1))
                await c.send_json_to({'type': 'join'})  # a later arrival still finds them
                self.assertEqual((await c.receive_json_from())['type'], 'matched')
        finally:
            for client in clients:
                await client.disconnect()

    async def connected(self, *clients):
        for client in clients:
            self.assertTrue((await client.connect())[0])
            self.assertEqual((await client.receive_json_from())['type'], 'ready')

    async def matched_pair(self, a, b):
        await a.send_json_to({'type': 'join'})
        self.assertEqual((await a.receive_json_from())['type'], 'waiting')
        await b.send_json_to({'type': 'join'})
        first, second = await a.receive_json_from(), await b.receive_json_from()
        self.assertEqual(first['match_id'], second['match_id'])
        return first, second

    async def test_dropped_socket_resumes_the_same_call(self):
        a, b, a2, a3 = (communicator(f'10.0.3.{i}') for i in range(4))
        try:
            await self.connected(a, b, a2, a3)
            first, _ = await self.matched_pair(a, b)
            await a.disconnect()  # network blip: no explicit leave
            self.assertEqual((await b.receive_json_from())['type'], 'peer_reconnecting')
            await a2.send_json_to({'type': 'resume', 'token': first['resume_token']})
            resumed = await a2.receive_json_from()
            self.assertEqual((resumed['type'], resumed['match_id']), ('resumed', first['match_id']))
            self.assertEqual((await b.receive_json_from())['type'], 'peer_resumed')
            await a2.send_json_to({'type': 'chat', 'match_id': first['match_id'], 'message': 'back'})
            self.assertEqual((await b.receive_json_from())['message'], 'back')
            await b.send_json_to({'type': 'chat', 'match_id': first['match_id'], 'message': 'welcome'})
            self.assertEqual((await a2.receive_json_from())['message'], 'welcome')
            await a3.send_json_to({'type': 'resume', 'token': first['resume_token']})  # single use
            self.assertEqual((await a3.receive_json_from())['type'], 'resume_failed')
        finally:
            for client in (b, a2, a3):
                await client.disconnect()

    @override_settings(RESUME_GRACE_SECONDS=1)
    async def test_unresumed_call_ends_after_grace(self):
        a, b, a2 = (communicator(f'10.0.4.{i}') for i in range(3))
        try:
            await self.connected(a, b, a2)
            first, _ = await self.matched_pair(a, b)
            await a.disconnect()
            self.assertEqual((await b.receive_json_from())['type'], 'peer_reconnecting')
            self.assertEqual((await b.receive_json_from(timeout=4))['type'], 'peer_left')
            await a2.send_json_to({'type': 'resume', 'token': first['resume_token']})
            self.assertEqual((await a2.receive_json_from())['type'], 'resume_failed')
        finally:
            for client in (b, a2):
                await client.disconnect()

    @override_settings(MATCH_RELAX_SECONDS=1)
    async def test_waiting_users_with_different_interests_meet_after_relaxing(self):
        a, b = communicator('10.0.5.1'), communicator('10.0.5.2')
        try:
            await self.connected(a, b)
            await a.send_json_to({'type': 'join', 'lang': 'ko', 'interests': ['music']})
            self.assertEqual((await a.receive_json_from())['type'], 'waiting')
            await b.send_json_to({'type': 'join', 'lang': 'ko', 'interests': ['games']})
            self.assertEqual((await b.receive_json_from())['type'], 'waiting')
            first, second = await a.receive_json_from(timeout=4), await b.receive_json_from(timeout=4)
            self.assertEqual((first['type'], second['type']), ('matched', 'matched'))
            self.assertEqual(first['common'], [])
            await a.send_json_to({'type': 'join', 'interests': ['music', 'x']})
            self.assertEqual((await a.receive_json_from())['type'], 'error')
        finally:
            for client in (a, b):
                await client.disconnect()

    async def test_call_stats_count_once_per_match_and_restart_signal(self):
        a, b = communicator('10.0.6.1'), communicator('10.0.6.2')
        try:
            await self.connected(a, b)
            first, _ = await self.matched_pair(a, b)
            match = first['match_id']
            for client in (a, b):
                await client.send_json_to({'type': 'stats', 'match_id': match, 'event': 'connected',
                                           'setup_ms': 1500, 'relay': True})
            for _ in range(2):
                await a.send_json_to({'type': 'stats', 'match_id': match, 'event': 'recovered', 'restart_ms': 900})
            await a.send_json_to({'type': 'stats', 'match_id': match, 'event': 'bogus'})
            self.assertEqual((await a.receive_json_from())['type'], 'error')
            await b.send_json_to({'type': 'signal', 'match_id': match, 'signal': {'restart': True}})
            self.assertEqual((await a.receive_json_from())['signal'], {'restart': True})
            await b.send_json_to({'type': 'signal', 'match_id': match, 'signal': {'restart': 1}})
            self.assertEqual((await b.receive_json_from())['type'], 'error')
            fields = await limits.shared_redis().hgetall(settings.MATCHMAKING_PREFIX + 'metrics')
            self.assertEqual(fields['calls_total{outcome="connected"}'], '1')
            self.assertEqual(fields['call_setup_seconds_bucket{le="2"}'], '1')
            self.assertNotIn('call_setup_seconds_bucket{le="1"}', fields)
            self.assertEqual(fields['calls_relayed_total'], '1')
            self.assertEqual(fields['ice_restarts_total{outcome="recovered"}'], '2')
        finally:
            for client in (a, b):
                await client.disconnect()

    async def test_report_stores_server_relayed_conversation(self):
        a, b = communicator('10.0.7.1'), communicator('10.0.7.2')
        try:
            await self.connected(a, b)
            first, _ = await self.matched_pair(a, b)
            match = first['match_id']
            await a.send_json_to({'type': 'chat', 'match_id': match, 'message': 'hi'})
            await b.receive_json_from()
            await b.send_json_to({'type': 'chat', 'match_id': match, 'message': 'rude words'})
            await a.receive_json_from()
            await a.send_json_to({'type': 'report', 'match_id': match, 'reason': 'harassment'})
            self.assertEqual((await a.receive_json_from())['type'], 'reported')
            evidence = (await Report.objects.aget()).evidence
            self.assertEqual([(e['from'], e['text']) for e in evidence], [('me', 'hi'), ('peer', 'rude words')])
        finally:
            for client in (a, b):
                await client.disconnect()

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

    def test_admin_shows_escaped_report_conversation(self):
        report = Report.objects.create(reporter='ipA', reported='ipB', reason='spam', match_id='m', evidence=[
            {'from': 'me', 'text': 'hello', 'at': '2026-10-25T00:00:00+00:00'},
            {'from': 'peer', 'text': '<script>buy now</script>', 'at': '2026-10-25T00:00:01+00:00'}])
        self.client.force_login(User.objects.create_superuser('admin', password='admin-password-123!'))
        response = self.client.get(f'/admin/chat/report/{report.pk}/change/')
        self.assertContains(response, '신고 대상')
        self.assertContains(response, '&lt;script&gt;buy now&lt;/script&gt;')
        self.assertNotContains(response, '<script>buy now')
        self.assertContains(self.client.get('/admin/chat/report/'), '대화 줄 수')

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
