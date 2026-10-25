"""Validated signaling transport. Clients cannot choose a room or recipient."""
import asyncio
import json
import logging
import secrets
import time
from collections import OrderedDict, deque
from contextlib import suppress
from datetime import datetime, timezone
from channels.db import database_sync_to_async
from channels.exceptions import ChannelFull
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from redis.exceptions import RedisError
from . import limits
from .matchmaking import Matchmaker
from .models import Report

logger = logging.getLogger(__name__)
# Every socket of a process shares one channel-layer inbox; back off while it drains.
BACKOFF = (0, 0.05, 0.1, 0.2, 0.4, 0.8, 1.6)
CALL_EVENTS = ('connected', 'failed', 'recovered', 'restart_failed')


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.matcher = Matchmaker()
        # Set only from Redis-confirmed pair_ready; relays trust these instead of re-reading Redis.
        self.match_id = self.peer = None
        # The last two matches stay reportable (a report dialog can still be open when the next
        # match starts), each with the chat this server relayed: evidence nobody can forge.
        self.history = OrderedDict()
        self.resume_token = None
        self.prefs = ('', ())
        # True while the browser shows "searching"; lets a ping requeue a stranded user.
        self.waiting = False
        self.last_ping = 0
        self.rematch = self.peer_watch = None
        self.tokens = 100.0
        self.updated = time.monotonic()
        self.last_seen = self.updated
        self.last_join = 0
        self.watchdog = None
        ip = limits.scope_ip(self.scope)
        self.ip_key = limits.anonymize(ip)
        self.who = limits.identity(self.scope['user'], ip)
        # Accept first so the browser receives a close code it can explain to the user.
        await self.accept()
        if await limits.ahit('ws:' + self.ip_key, 60) > settings.WS_CONNECT_RATE:
            return await self.reject('connect_rate')
        if not await limits.track_connection(self.ip_key, self.channel_name, settings.WS_MAX_PER_IP,
                                             settings.PRESENCE_TTL):
            return await self.reject('ip_limit')
        await limits.acount('ws_connections_total')
        await self.send_json({'type': 'ready'})
        self.watchdog = asyncio.create_task(self.watch_presence())

    async def reject(self, reason):
        await limits.acount(f'ws_rejected_total{{reason="{reason}"}}')
        await self.close(code=4029)

    @staticmethod
    def stop_task(task):
        # Never cancel the task we are running in: its remaining awaits would be cancelled too.
        if task and task is not asyncio.current_task():
            task.cancel()

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
        if not self.watchdog:
            return
        for task in (self.watchdog, self.rematch, self.peer_watch):
            self.stop_task(task)
        with suppress(asyncio.CancelledError):
            await self.watchdog
        await limits.drop_connection(self.ip_key, self.channel_name)
        try:
            # A dropped socket mid-call is usually a network blip: hold the call for a resume.
            if not (self.match_id and await self.suspend()):
                await self.leave()
        except RedisError:
            logger.warning('Presence cleanup deferred to TTL')

    async def deliver(self, channel, message):
        """Send through the channel layer; False if the recipient's inbox stayed full for ~3s."""
        for delay in BACKOFF:
            await asyncio.sleep(delay)
            with suppress(ChannelFull):
                await self.channel_layer.send(channel, message)
                return True
        logger.warning('Channel layer full, dropped %s', message['type'])
        await limits.acount('channel_full_dropped_total')
        return False

    async def suspend(self):
        peer, match = await self.matcher.suspend(self.channel_name)
        if not peer:
            return False
        await limits.acount('sessions_suspended_total')
        await self.deliver(peer, {'type': 'peer.suspended', 'match_id': match})
        return True

    async def leave(self):
        self.stop_task(self.rematch)
        self.stop_task(self.peer_watch)
        if self.resume_token:
            await self.matcher.revoke_resume_token(self.resume_token)
            self.resume_token = None
        peer, match = await self.matcher.transition('leave', self.channel_name)
        self.match_id = self.peer = None
        self.waiting = False
        if peer:
            # Undelivered, the peer still notices on its next ping (state mismatch).
            await self.deliver(peer, {'type': 'peer.left', 'match_id': match})

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
            self.last_seen = now = time.monotonic()
            # Browsers ping every 15s; extra pings must not each cost several Redis calls.
            if now - self.last_ping < 5:
                return await self.send_json({'type': 'pong'})
            self.last_ping = now
            await limits.refresh_connection(self.ip_key, self.channel_name, settings.PRESENCE_TTL)
            state = await self.matcher.transition('state', self.channel_name)
            if state[0] == 'expired':
                await self.close(code=1012)
                return
            if self.match_id and (state[0] != 'matched' or state[2] != self.match_id):
                await self.peer_left({'match_id': self.match_id})
            elif self.match_id and state[1] != self.peer:
                # A lost peer.moved after a resume would otherwise relay into a dead channel.
                await self.peer_moved({'match_id': self.match_id, 'channel': state[1]})
            elif self.waiting and state[0] == 'idle':
                # Searching in the browser but neither queued nor matched in Redis (a match
                # that fell through before it was announced): put the user back in the queue.
                await self.try_match(announce=False)
            await self.send_json({'type': 'pong'})
        elif kind in ('join', 'next'):
            if time.monotonic() - self.last_join < 1:
                await self.send_json({'type': 'error', 'message': '잠시 후 다시 시도해 주세요.'})
                return
            self.last_join = time.monotonic()
            if 'lang' in data or 'interests' in data:
                self.prefs = self.parse_prefs(data)
            if kind == 'next':
                await self.leave()
            await self.join()
        elif kind == 'resume':
            await self.resume(data)
        elif kind == 'leave':
            await self.leave()
            await self.send_json({'type': 'idle'})
        elif kind == 'report':
            await self.report(data)
        elif kind == 'stats':
            await self.record_stats(data)
        elif kind in ('signal', 'chat', 'media'):
            if not self.match_id or data.get('match_id') != self.match_id:
                return
            payload = {'type': kind, 'match_id': self.match_id}
            if kind == 'chat':
                message = data.get('message')
                if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
                    raise ValueError
                payload['message'] = message.strip()
                payload['username'] = self.scope['user'].get_username() or '상대방'
                self.remember('me', payload['message'])
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
                # The answering side asks the offerer for an ICE restart. `is True`: 1 == True in Python.
                elif list(signal) != ['restart'] or signal['restart'] is not True:
                    raise ValueError
                payload['signal'] = signal
            # A peer that already moved on has a different match_id and drops this in relay().
            await self.deliver(self.peer, {'type': 'relay', 'payload': payload})
        else:
            raise ValueError

    @staticmethod
    def parse_prefs(data):
        lang, interests = data.get('lang', ''), data.get('interests', [])
        if lang not in ('', *settings.MATCH_LANGUAGES) or not isinstance(interests, list) or len(interests) > 3 \
                or not set(interests) <= set(settings.MATCH_INTERESTS):
            raise ValueError
        return lang, tuple(sorted(set(interests)))

    async def join(self):
        self.stop_task(self.rematch)
        if await self.try_match() == 'waiting' and any(self.prefs):
            self.rematch = asyncio.create_task(self.retry_match())

    async def try_match(self, attempts=3, announce=True):
        for attempt in range(attempts):
            state = await self.matcher.join(self.channel_name, self.who, *self.prefs)
            if state[0] == 'waiting':
                self.waiting = True
                if announce:
                    await self.send_json({'type': 'waiting'})
                return 'waiting'
            if state[0] == 'banned':
                self.waiting = False
                await self.send_json({'type': 'banned', 'retry_after': int(state[1])})
                return 'banned'
            if state[0] != 'new_match':
                return state[0]
            _, peer, match = state
            if await self.deliver(peer, {'type': 'pair.ready', 'match_id': match, 'initiator': True}):
                # The peer may have left while the notice was in flight: then just search again.
                if await self.pair_ready({'match_id': match, 'initiator': False}):
                    return 'matched'
                continue
            # Never leave a half-announced match: the peer would wait on a pair it never saw.
            # Requeue the peer and match again ourselves; matching only runs on join, so
            # requeueing both would strand them until someone new arrives.
            await self.matcher.transition('release' if attempt < attempts - 1 else 'unpair', self.channel_name)
        self.waiting = True
        if announce:
            await self.send_json({'type': 'waiting'})
        return 'waiting'

    async def retry_match(self):
        """Matching only runs on join, so re-run it once preferences relax: two waiting users
        with different interests must still meet even if nobody else arrives."""
        try:
            await asyncio.sleep(settings.MATCH_RELAX_SECONDS + 0.5)
            while not self.match_id and await self.try_match(announce=False) == 'waiting':
                await asyncio.sleep(5)
        except RedisError:
            logger.warning('Preference rematch skipped: Redis unavailable')

    async def resume(self, data):
        token = data.get('token')
        if not isinstance(token, str) or not 8 <= len(token) <= 64 or self.match_id:
            raise ValueError
        state = await self.matcher.resume(self.channel_name, token, self.who)
        if state[0] != 'resumed':
            await limits.acount('sessions_resumed_total{outcome="expired"}')
            return await self.send_json({'type': 'resume_failed'})
        _, peer, match, self.who, peer_who, common = state
        self.peer, self.match_id = peer, match
        # Report history and evidence lived in the dropped socket; start a fresh record.
        self.track(match, peer_who)
        self.resume_token = secrets.token_urlsafe(18)
        await self.matcher.issue_resume_token(self.channel_name, self.resume_token)
        await limits.acount('sessions_resumed_total{outcome="resumed"}')
        await self.deliver(peer, {'type': 'peer.moved', 'match_id': match, 'channel': self.channel_name})
        await self.send_json({'type': 'resumed', 'match_id': match, 'resume_token': self.resume_token,
                              'common': [t for t in common.split(',') if t]})

    async def record_stats(self, data):
        event, match = data.get('event'), data.get('match_id')
        setup_ms, restart_ms = data.get('setup_ms'), data.get('restart_ms')
        if event not in CALL_EVENTS or match not in self.history \
                or not all(v is None or (isinstance(v, int) and 0 <= v <= 120000) for v in (setup_ms, restart_ms)) \
                or not isinstance(data.get('relay', False), bool):
            raise ValueError
        await limits.record_call(match, event, setup_ms, data.get('relay', False), restart_ms)

    def track(self, match, peer_who):
        self.history[match] = {'who': peer_who, 'lines': deque(maxlen=20)}
        while len(self.history) > 2:
            self.history.popitem(last=False)

    def remember(self, sender, text):
        if self.match_id in self.history:
            self.history[self.match_id]['lines'].append(
                {'from': sender, 'text': text[:500], 'at': datetime.now(timezone.utc).isoformat()})

    async def report(self, data):
        reason, match = data.get('reason'), data.get('match_id')
        if reason not in Report.Reason.values or match not in self.history:
            raise ValueError
        if await limits.ahit('report:' + self.who, 3600) > settings.REPORTS_PER_HOUR:
            await self.send_json({'type': 'error', 'message': '신고가 너무 많습니다. 잠시 후 다시 시도해 주세요.'})
            return
        entry = self.history.pop(match)  # one report per match
        target = entry['who']
        # Guests sharing an IP share an identity: blocking or counting it would hit the
        # reporter too, so they only get the per-connection exclusion that leave() sets.
        banned = target != self.who and await self.matcher.report(self.who, target)
        await limits.acount('reports_total')
        await database_sync_to_async(Report.objects.create)(
            reporter=self.who, reported=target, reason=reason, match_id=match, banned=banned,
            evidence=list(entry['lines']))
        if self.match_id == match:
            await self.leave()
        await self.send_json({'type': 'reported', 'match_id': match})

    async def pair_ready(self, event):
        """Announce a Redis-confirmed match; False when it already fell through."""
        state = await self.matcher.transition('state', self.channel_name)
        if state[0] != 'matched' or state[2] != event['match_id']:
            return False
        self.stop_task(self.rematch)
        self.waiting = False
        self.peer, self.match_id = state[1], state[2]
        self.track(self.match_id, state[3])
        self.resume_token = secrets.token_urlsafe(18)
        await self.matcher.issue_resume_token(self.channel_name, self.resume_token)
        await self.send_json({'type': 'matched', 'match_id': state[2], 'initiator': event['initiator'],
                              'resume_token': self.resume_token,
                              'common': [t for t in state[4].split(',') if t]})
        return True

    async def peer_left(self, event):
        if self.match_id == event['match_id']:
            self.stop_task(self.peer_watch)
            self.match_id = self.peer = None
            await self.send_json({'type': 'peer_left', 'match_id': event['match_id']})

    async def peer_suspended(self, event):
        if self.match_id != event['match_id']:
            return
        await self.send_json({'type': 'peer_reconnecting', 'match_id': self.match_id,
                              'grace': settings.RESUME_GRACE_SECONDS})
        self.stop_task(self.peer_watch)
        self.peer_watch = asyncio.create_task(self.expire_suspended_peer(event['match_id']))

    async def expire_suspended_peer(self, match):
        await asyncio.sleep(settings.RESUME_GRACE_SECONDS + 1)
        with suppress(RedisError):
            state = await self.matcher.transition('state', self.channel_name)
            if self.match_id == match and (state[0] != 'matched' or state[2] != match):
                await self.peer_left({'match_id': match})

    async def peer_moved(self, event):
        if self.match_id == event['match_id']:
            self.stop_task(self.peer_watch)
            self.peer = event['channel']
            await self.send_json({'type': 'peer_resumed', 'match_id': self.match_id})

    async def relay(self, event):
        payload = event['payload']
        if self.match_id and self.match_id == payload['match_id']:
            if payload['type'] == 'chat':
                self.remember('peer', payload['message'])
            await self.send_json(payload)
