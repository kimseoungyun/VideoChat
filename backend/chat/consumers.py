"""Validated signaling transport. Clients cannot choose a room or recipient."""
import asyncio
import json
import logging
import time
from contextlib import suppress
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from redis.exceptions import RedisError
from .matchmaking import Matchmaker

logger = logging.getLogger(__name__)


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.matcher = Matchmaker()
        self.match_id = None
        self.tokens = 100.0
        self.updated = time.monotonic()
        self.last_seen = self.updated
        self.last_join = 0
        await self.accept()
        await self.send_json({'type': 'ready'})
        self.watchdog = asyncio.create_task(self.watch_presence())

    async def watch_presence(self):
        while True:
            await asyncio.sleep(15)
            if time.monotonic() - self.last_seen > 45:
                try:
                    await self.leave()
                except RedisError:
                    logger.warning('Presence cleanup deferred to TTL')
                await self.close(code=4000)
                return

    async def disconnect(self, code):
        self.watchdog.cancel()
        with suppress(asyncio.CancelledError):
            await self.watchdog
        try:
            await self.leave()
        except RedisError:
            logger.warning('Presence cleanup deferred to TTL')
        finally:
            await self.matcher.close()

    async def leave(self):
        peer, match = await self.matcher.transition('leave', self.channel_name)
        self.match_id = None
        if peer:
            await self.channel_layer.send(peer, {'type': 'peer.left', 'match_id': match})

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        now = time.monotonic()
        self.tokens = min(100, self.tokens + (now - self.updated) * 30)
        self.updated = now
        if self.tokens < 1:
            await self.close(code=4008)
            return
        self.tokens -= 1
        if text_data is None or len(text_data.encode('utf-8')) > 32768:
            await self.close(code=1009)
            return
        try:
            data = json.loads(text_data)
            if not isinstance(data, dict):
                raise ValueError
            await self.handle(data)
        except (ValueError, TypeError, KeyError):
            await self.send_json({'type': 'error', 'message': '올바르지 않은 요청입니다.'})
        except RedisError:
            logger.exception('Matchmaking backend unavailable')
            await self.send_json({'type': 'error', 'message': '연결 서버에 문제가 있습니다. 잠시 후 다시 시도해 주세요.'})
            await self.close(code=1013)

    async def handle(self, data):
        kind = data.get('type')
        if kind == 'ping':
            self.last_seen = time.monotonic()
            state = await self.matcher.transition('state', self.channel_name)
            if state[0] == 'expired':
                await self.close(code=1012)
                return
            if self.match_id and (state[0] != 'matched' or state[2] != self.match_id):
                await self.peer_left({'match_id': self.match_id})
            await self.send_json({'type': 'pong'})
        elif kind in ('join', 'next'):
            if time.monotonic() - self.last_join < 1:
                await self.send_json({'type': 'error', 'message': '잠시 후 다시 시도해 주세요.'})
                return
            self.last_join = time.monotonic()
            if kind == 'next':
                await self.leave()
            state = await self.matcher.transition('join', self.channel_name)
            if state[0] == 'waiting':
                await self.send_json({'type': 'waiting'})
            elif state[0] == 'new_match':
                _, peer, match = state
                await self.channel_layer.send(peer, {'type': 'pair.ready', 'match_id': match, 'initiator': True})
                await self.pair_ready({'match_id': match, 'initiator': False})
        elif kind == 'leave':
            await self.leave()
            await self.send_json({'type': 'idle'})
        elif kind in ('signal', 'chat', 'media'):
            state = await self.matcher.transition('state', self.channel_name)
            if state[0] != 'matched' or data.get('match_id') != state[2]:
                return
            payload = {'type': kind, 'match_id': state[2]}
            if kind == 'chat':
                message = data.get('message')
                if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
                    raise ValueError
                payload['message'] = message.strip()
                payload['username'] = self.scope['user'].get_username() or '상대방'
            elif kind == 'media':
                if not all(isinstance(data.get(k), bool) for k in ('audio', 'video')):
                    raise ValueError
                payload.update(audio=data['audio'], video=data['video'])
            else:
                signal = data.get('signal')
                if not isinstance(signal, dict):
                    raise ValueError
                if 'description' in signal:
                    desc = signal['description']
                    if not isinstance(desc, dict) or desc.get('type') not in ('offer', 'answer') or not isinstance(desc.get('sdp'), str):
                        raise ValueError
                elif 'candidate' in signal:
                    if not isinstance(signal['candidate'], dict):
                        raise ValueError
                else:
                    raise ValueError
                payload['signal'] = signal
            await self.channel_layer.send(state[1], {'type': 'relay', 'payload': payload})
        else:
            raise ValueError

    async def pair_ready(self, event):
        state = await self.matcher.transition('state', self.channel_name)
        if state[0] == 'matched' and state[2] == event['match_id']:
            self.match_id = state[2]
            await self.send_json({'type': 'matched', 'match_id': state[2], 'initiator': event['initiator']})

    async def peer_left(self, event):
        if self.match_id == event['match_id']:
            self.match_id = None
            await self.send_json({'type': 'peer_left', 'match_id': event['match_id']})

    async def relay(self, event):
        state = await self.matcher.transition('state', self.channel_name)
        if state[0] == 'matched' and state[2] == event['payload']['match_id']:
            await self.send_json(event['payload'])
