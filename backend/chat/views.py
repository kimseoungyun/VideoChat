import base64
import hashlib
import hmac
import time
from uuid import uuid4
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from . import limits


@never_cache
def process(request, room_name=None):
    return render(request, 'chat/process.html', {'rtc_config': {'url': reverse('chat:rtc_config')}})


@never_cache
@require_GET
def rtc_config(request):
    """Issue fresh credentials for each match, even after a long-lived page visit."""
    if limits.hit('rtc:' + limits.anonymize(limits.request_ip(request)), 60) > settings.RTC_CONFIG_PER_IP:
        limits.count('http_ratelimited_total{scope="rtc_config"}')
        return JsonResponse({'error': 'rate_limited'}, status=429)
    ice_servers = [{'urls': 'stun:stun.l.google.com:19302'}]
    if settings.TURN_URLS and settings.TURN_SECRET:
        username = f'{int(time.time()) + 3600}:{uuid4().hex}'
        credential = base64.b64encode(hmac.new(settings.TURN_SECRET.encode(), username.encode(), hashlib.sha1).digest()).decode()
        ice_servers.append({'urls': settings.TURN_URLS, 'username': username, 'credential': credential})
    return JsonResponse({'iceServers': ice_servers})


def start_chat(request):
    return redirect('chat:lobby')


def redirect_room(request, current_room):
    return redirect('chat:lobby')
