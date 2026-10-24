import asyncio
import base64
import hashlib
import hmac
from unittest.mock import patch
from uuid import uuid4
from django.conf import settings
from django.test import SimpleTestCase, override_settings
from channels.testing import WebsocketCommunicator
from channels.auth import AuthMiddlewareStack
from channels.routing import URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from .routing import websocket_urlpatterns
from .matchmaking import Matchmaker


class RtcConfigTests(SimpleTestCase):
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
                await matcher.close()

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
                await a.send_json_to({'type': 'leave'})
                self.assertEqual((await a.receive_json_from())['type'], 'idle')
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
