import base64
import hashlib
import hmac
import time
from uuid import uuid4
from django.conf import settings
from django.http import Http404, JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from . import limits, sanctions, trust
from .models import Appeal, Sanction
from .verification import get_verifier


LANGUAGE_LABELS = {'ko': '한국어', 'en': 'English', 'ja': '日本語', 'zh': '中文'}  # each in its own language
INTEREST_LABELS = {'music': _('음악'), 'games': _('게임'), 'movies': _('영화'), 'sports': _('운동'),
                   'travel': _('여행'), 'study': _('공부'), 'pets': _('반려동물'), 'food': _('음식')}


@never_cache
@ensure_csrf_cookie
def process(request, room_name=None):
    return render(request, 'chat/process.html', {
        'rtc_config': {'url': reverse('chat:rtc_config')},
        'trust': {**trust.page_state(request.session), 'consent_url': reverse('chat:consent'),
                  'verify_url': reverse('chat:verify') + '?next=' + reverse('chat:lobby'),
                  'min_age': settings.MIN_AGE},
        'languages': [(code, LANGUAGE_LABELS[code]) for code in settings.MATCH_LANGUAGES],
        'interests': [(code, INTEREST_LABELS[code]) for code in settings.MATCH_INTERESTS],
        'relax_seconds': settings.MATCH_RELAX_SECONDS,
        'retention_days': settings.REPORT_RETENTION_DAYS,
        'min_age': settings.MIN_AGE,
    })


@require_POST
def consent(request):
    """Both statements must be ticked; the server, not the page, decides who may be matched."""
    if request.POST.get('adult') != '1' or request.POST.get('rules') != '1':
        return JsonResponse({'error': 'both_required'}, status=400)
    trust.record_consent(request.session)
    return JsonResponse({'ok': True})


@never_cache
def verify(request):
    verifier = get_verifier()
    if verifier is None:
        raise Http404
    request.session['verify_next'] = url_has_allowed_host_and_scheme(
        request.GET.get('next', ''), allowed_hosts={request.get_host()}) and request.GET['next'] or reverse('chat:lobby')
    return verifier.begin(request)


@never_cache
def verify_callback(request):
    verifier = get_verifier()
    if verifier is None:
        raise Http404
    result = verifier.complete(request)
    if result is None:
        return render(request, 'chat/verify_result.html', {'ok': False}, status=400)
    trust.record_verification(request.session, result, verifier.name)
    if not result.adult:
        return render(request, 'chat/verify_result.html', {'ok': True, 'adult': False, 'min_age': settings.MIN_AGE})
    return redirect(request.session.pop('verify_next', reverse('chat:lobby')))


@never_cache
def appeal(request, code):
    """Appeal a sanction with the single-use code shown when matching was refused."""
    identity = limits.sync_redis().get(sanctions.appeal_key(code))
    sanction = Sanction.objects.filter(identity=identity).first() if identity else None
    if sanction is None:
        return render(request, 'chat/appeal.html', {'missing': True}, status=404)
    context = {'sanction': sanction, 'pending': sanction.appeals.filter(status=Appeal.Status.PENDING).exists()}
    if request.method == 'POST' and not context['pending']:
        if limits.hit('appeal:' + limits.anonymize(limits.request_ip(request)), 3600) > settings.APPEALS_PER_HOUR:
            return render(request, 'chat/appeal.html', {**context, 'error': '요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.'},
                          status=429)
        message = request.POST.get('message', '').strip()
        if not 10 <= len(message) <= 1000:
            return render(request, 'chat/appeal.html', {**context, 'error': '10자 이상 1,000자 이하로 적어 주세요.'},
                          status=400)
        Appeal.objects.create(sanction=sanction, message=message)
        context.update(pending=True, submitted=True)
    return render(request, 'chat/appeal.html', context)


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
        if settings.ICE_RELAY_ONLY:
            # Without host/srflx candidates the stranger never learns this user's public IP.
            return JsonResponse({'iceServers': ice_servers, 'iceTransportPolicy': 'relay'})
    return JsonResponse({'iceServers': ice_servers})


def start_chat(request):
    return redirect('chat:lobby')


def redirect_room(request, current_room):
    return redirect('chat:lobby')
