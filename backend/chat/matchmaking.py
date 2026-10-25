"""Redis owns ephemeral presence; consumers only own transport connections."""
import asyncio
import weakref
from pathlib import Path
from uuid import uuid4
from django.conf import settings
from redis.asyncio import BlockingConnectionPool, Redis

SCRIPT = Path(__file__).with_suffix('.lua').read_text(encoding='utf-8')
# Block the pair both ways, count distinct reporters, ban the target at the threshold.
REPORT = """
local blocks, reporters, ban, metrics = KEYS[1], KEYS[2], KEYS[3], KEYS[4]
local target, reporter = ARGV[1], ARGV[2]
redis.call('SADD', blocks, target)
redis.call('EXPIRE', blocks, ARGV[3])
redis.call('SADD', reporters, reporter)
redis.call('EXPIRE', reporters, ARGV[4])
if redis.call('SCARD', reporters) >= tonumber(ARGV[5]) then
    redis.call('SET', ban, '1', 'EX', ARGV[6])
    redis.call('DEL', reporters)
    redis.call('HINCRBY', metrics, 'bans_total', 1)
    return 1
end
return 0
"""
# One bounded pool per event loop: a pool per WebSocket costs one Redis connection
# (and one file descriptor) per user.
_clients = weakref.WeakKeyDictionary()


def shared_redis():
    loop = asyncio.get_running_loop()
    if loop not in _clients:
        pool = BlockingConnectionPool.from_url(
            settings.REDIS_URL, decode_responses=True, max_connections=settings.REDIS_POOL_SIZE,
            timeout=3, socket_connect_timeout=3, socket_timeout=3)
        _clients[loop] = Redis(connection_pool=pool)
    return _clients[loop]


class Matchmaker:
    def __init__(self):
        self.redis = shared_redis()
        self.script = self.redis.register_script(SCRIPT)
        self.report_script = self.redis.register_script(REPORT)

    async def transition(self, action, channel, who=''):
        prefix = settings.MATCHMAKING_PREFIX
        return await self.script(keys=[prefix + 'queue', prefix + 'member:', prefix],
                                 args=[action, channel, settings.PRESENCE_TTL, uuid4().hex, who])

    async def report(self, reporter, target):
        """Returns True when this report banned the target."""
        prefix = settings.MATCHMAKING_PREFIX
        return bool(await self.report_script(
            keys=[prefix + 'blocks:' + reporter, prefix + 'reports:' + target, prefix + 'ban:' + target,
                  prefix + 'metrics'],
            args=[target, reporter, settings.REPORT_BLOCK_SECONDS, settings.REPORT_WINDOW_SECONDS,
                  settings.REPORT_BAN_THRESHOLD, settings.REPORT_BAN_SECONDS]))
