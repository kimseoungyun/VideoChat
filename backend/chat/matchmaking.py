"""Redis owns ephemeral presence; consumers only own transport connections."""
from pathlib import Path
from uuid import uuid4
from django.conf import settings
from redis.asyncio import Redis

SCRIPT = Path(__file__).with_suffix('.lua').read_text(encoding='utf-8')


class Matchmaker:
    def __init__(self):
        self.redis = Redis.from_url(settings.REDIS_URL, decode_responses=True,
                                   socket_connect_timeout=3, socket_timeout=3)
        self.script = self.redis.register_script(SCRIPT)

    async def transition(self, action, channel):
        prefix = settings.MATCHMAKING_PREFIX
        return await self.script(keys=[prefix + 'queue', prefix + 'member:'],
                                 args=[action, channel, settings.PRESENCE_TTL, uuid4().hex])

    async def close(self):
        await self.redis.aclose()
