"""Login throttling shared by the site login and the Django admin login.

The attempt is counted before the password is checked: checking first and counting after
lets a burst of concurrent guesses all pass the check. A successful login gives it back.
"""
from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse
from chat import limits

WINDOW = 15 * 60
THROTTLED = '시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.'


def begin_login(request):
    """Count this attempt; returns (allowed, keys) where keys feed finish_login."""
    keys = ('login-user:' + limits.anonymize(request.POST.get('username', '').strip().lower()),
            'login-ip:' + limits.anonymize(limits.request_ip(request)))
    allowed = (limits.hit(keys[0], WINDOW) <= settings.LOGIN_FAILURES_PER_USER
               and limits.hit(keys[1], WINDOW) <= settings.LOGIN_FAILURES_PER_IP)
    if not allowed:
        limits.count('http_ratelimited_total{scope="login"}')
    return allowed, keys


def finish_login(keys):
    limits.reset(keys[0])
    limits.unhit(keys[1])


_admin_login = admin.site.login


def admin_login(request, extra_context=None):
    if request.method != 'POST':
        return _admin_login(request, extra_context)
    allowed, keys = begin_login(request)
    if not allowed:
        return HttpResponse(THROTTLED, status=429, content_type='text/plain; charset=utf-8')
    response = _admin_login(request, extra_context)
    if request.user.is_authenticated:
        finish_login(keys)
    return response
