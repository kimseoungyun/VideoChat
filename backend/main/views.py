from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from chat import limits
from .forms import CustomUserCreationForm
from .throttle import THROTTLED, begin_login, finish_login


def starthome_view(request):
    return redirect('chat:lobby')


def login_view(request):
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST':
        # Per-account caps stop password guessing; per-IP caps stop spraying many accounts.
        allowed, keys = begin_login(request)
        if not allowed:
            # Unbound form: validating would still run the password hasher.
            return render(request, 'main/login.html', {'form': AuthenticationForm(request), 'error': THROTTLED},
                          status=429)
        if form.is_valid():
            finish_login(keys)
            login(request, form.get_user())
            return redirect('home')
    return render(request, 'main/login.html', {'form': form})


def signup_view(request):
    form = CustomUserCreationForm(request.POST or None)
    if request.method == 'POST':
        if limits.hit('signup:' + limits.anonymize(limits.request_ip(request)), 3600) > settings.SIGNUPS_PER_IP:
            limits.count('http_ratelimited_total{scope="signup"}')
            return render(request, 'main/signup.html', {'form': CustomUserCreationForm(), 'error': THROTTLED},
                          status=429)
        if form.is_valid():
            form.save()
            return redirect('login')
    return render(request, 'main/signup.html', {'form': form})


@login_required
def home_view(request):
    return render(request, 'main/home.html')


@require_POST
@login_required
def delete_account_view(request):
    """Self-service deletion, as the privacy policy promises; the password guards stolen sessions."""
    if not request.user.check_password(request.POST.get('password', '')):
        return render(request, 'main/home.html', {'delete_error': '비밀번호가 맞지 않습니다.'}, status=400)
    user = request.user
    logout(request)
    user.delete()
    return render(request, 'main/deleted.html')


def policy_view(request, page):
    return render(request, f'main/{page}.html', {
        'version': settings.CONSENT_VERSION, 'min_age': settings.MIN_AGE,
        'retention_days': settings.REPORT_RETENTION_DAYS, 'sanction_days': settings.SANCTION_DAYS})


@require_POST
@login_required
def logout_view(request):
    logout(request)
    return redirect('starthome')
