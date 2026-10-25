from django.http import JsonResponse
from redis.exceptions import RedisError
from chat.matchmaking import shared_redis


async def health(request):
    try:
        await shared_redis().ping()
        return JsonResponse({'status': 'ok'})
    except RedisError:
        return JsonResponse({'status': 'unavailable'}, status=503)
