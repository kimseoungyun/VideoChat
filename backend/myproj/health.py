from django.conf import settings
from django.http import JsonResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError


async def health(request):
    client = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
    try:
        await client.ping()
        return JsonResponse({'status': 'ok'})
    except RedisError:
        return JsonResponse({'status': 'unavailable'}, status=503)
    finally:
        await client.aclose()
