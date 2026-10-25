"""Client identity, rate limits and counters shared by HTTP views and WebSockets.

Identities are hashed so Redis keys and stored reports never contain raw IP addresses.
Rate limits fail open: Redis outages are surfaced by /health/, not by locking users out.
"""
import hashlib
import hmac
import logging
from django.conf import settings
from redis import ConnectionPool, Redis
from redis.exceptions import RedisError
from .matchmaking import shared_redis

logger = logging.getLogger(__name__)
# Fixed window: the first hit sets the expiry, so a key can never outlive its window.
HIT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""
# Live connections per IP; members expire unless the socket keeps pinging.
CONNECT = """
local t = redis.call('TIME')
local now = tonumber(t[1])
for _, k in ipairs(KEYS) do redis.call('ZREMRANGEBYSCORE', k, '-inf', now) end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then return 0 end
for _, k in ipairs(KEYS) do
    redis.call('ZADD', k, now + tonumber(ARGV[3]), ARGV[1])
    redis.call('EXPIRE', k, ARGV[3])
end
return 1
"""
_sync = None


def key(*parts):
    return settings.MATCHMAKING_PREFIX + ':'.join(parts)


def anonymize(value):
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()[:20]


def client_ip(remote, forwarded=''):
    # Behind a trusted proxy the last hop is the one it appended; earlier hops are client-controlled.
    if settings.TRUST_PROXY and forwarded:
        return forwarded.split(',')[-1].strip()
    return remote or 'unknown'


def request_ip(request):
    return client_ip(request.META.get('REMOTE_ADDR'), request.META.get('HTTP_X_FORWARDED_FOR', ''))


def scope_ip(scope):
    headers = dict(scope.get('headers', []))
    return client_ip((scope.get('client') or [None])[0], headers.get(b'x-forwarded-for', b'').decode('latin-1'))


def identity(user, ip):
    """Accounts are tracked by id; guests by hashed IP, so NAT-shared guests share limits."""
    return f'u{user.pk}' if user.is_authenticated else 'ip' + anonymize(ip)


def sync_redis():
    global _sync
    if _sync is None:
        _sync = Redis(connection_pool=ConnectionPool.from_url(
            settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2, socket_timeout=2))
    return _sync


def hit(name, window):
    """Count one event in a fixed window; returns the count, or 0 when Redis is unavailable."""
    try:
        return sync_redis().eval(HIT, 1, key('rate', name), window)
    except RedisError:
        logger.warning('Rate limit skipped: Redis unavailable')
        return 0


def peek(name):
    try:
        return int(sync_redis().get(key('rate', name)) or 0)
    except RedisError:
        return 0


def reset(name):
    try:
        sync_redis().delete(key('rate', name))
    except RedisError:
        pass


def count(metric, amount=1):
    try:
        sync_redis().hincrby(key('metrics'), metric, amount)
    except RedisError:
        pass


async def ahit(name, window):
    try:
        return await shared_redis().eval(HIT, 1, key('rate', name), window)
    except RedisError:
        logger.warning('Rate limit skipped: Redis unavailable')
        return 0


async def acount(metric, amount=1):
    try:
        await shared_redis().hincrby(key('metrics'), metric, amount)
    except RedisError:
        pass


async def track_connection(ip_key, channel, limit, ttl):
    """Register a live socket; False when this IP already holds `limit` live sockets."""
    try:
        return bool(await shared_redis().eval(CONNECT, 2, key('conns', ip_key), key('conns'), channel, limit, ttl))
    except RedisError:
        return True


async def refresh_connection(ip_key, channel, ttl):
    redis = shared_redis()
    expiry = int((await redis.time())[0]) + ttl
    async with redis.pipeline(transaction=False) as pipe:
        for name in (key('conns', ip_key), key('conns')):
            pipe.zadd(name, {channel: expiry}, xx=True).expire(name, ttl)
        await pipe.execute()


async def drop_connection(ip_key, channel):
    try:
        async with shared_redis().pipeline(transaction=False) as pipe:
            await pipe.zrem(key('conns', ip_key), channel).zrem(key('conns'), channel).execute()
    except RedisError:
        logger.warning('Connection cleanup deferred to TTL')
