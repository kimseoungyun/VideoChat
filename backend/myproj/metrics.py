"""Prometheus text exposition. Counters live in one Redis hash so every worker reports the same totals."""
import hmac
from django.conf import settings
from django.http import Http404, HttpResponse
from redis.exceptions import RedisError
from chat.matchmaking import shared_redis

FAMILIES = {
    'ws_connections_total': ('counter', 'Accepted WebSocket connections'),
    'ws_rejected_total': ('counter', 'WebSockets refused by abuse limits'),
    'http_ratelimited_total': ('counter', 'HTTP requests refused by rate limits'),
    'matches_total': ('counter', 'Pairs created'),
    'match_wait_seconds': ('histogram', 'Time a user waited in the queue before being paired'),
    'reports_total': ('counter', 'User reports'),
    'bans_total': ('counter', 'Temporary bans issued by report threshold'),
    'queue_waiting': ('gauge', 'Users waiting for a partner'),
    'ws_active': ('gauge', 'Live WebSocket connections'),
}


def allowed(request):
    if settings.METRICS_TOKEN:
        supplied = request.headers.get('Authorization', '').removeprefix('Bearer ')
        return hmac.compare_digest(supplied.encode(), settings.METRICS_TOKEN.encode())
    return settings.DEBUG


async def metrics(request):
    if not allowed(request):
        raise Http404
    prefix = settings.MATCHMAKING_PREFIX
    redis = shared_redis()
    try:
        now = (await redis.time())[0]
        values = await redis.hgetall(prefix + 'metrics')
        values['queue_waiting'] = await redis.zcount(prefix + 'queue', now, '+inf')
        values['ws_active'] = await redis.zcount(prefix + 'conns', now, '+inf')
    except RedisError:
        return HttpResponse('# redis unavailable\n', status=503, content_type='text/plain')
    if 'match_wait_seconds_count' in values:
        values['match_wait_seconds_bucket{le="+Inf"}'] = values['match_wait_seconds_count']
    lines = []
    for family, (kind, help_text) in FAMILIES.items():
        lines += [f'# HELP videochat_{family} {help_text}', f'# TYPE videochat_{family} {kind}']
        for field in sorted(values):
            if field.split('{')[0] in (family, family + '_bucket', family + '_sum', family + '_count'):
                lines.append(f'videochat_{field} {values[field]}')
    return HttpResponse('\n'.join(lines) + '\n', content_type='text/plain; version=0.0.4')
