from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from chat import limits
from .forms import CustomUserCreationForm

LOGIN_WINDOW = 15 * 60
THROTTLED = '시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.'


def starthome_view(request):
    return redirect('chat:lobby')


def login_view(request):
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST':
        ip = limits.anonymize(limits.request_ip(request))
        user = limits.anonymize(request.POST.get('username', '').strip().lower())
        # Per-account caps stop password guessing; per-IP caps stop spraying many accounts.
        if (limits.peek('login-user:' + user) >= settings.LOGIN_FAILURES_PER_USER
                or limits.peek('login-ip:' + ip) >= settings.LOGIN_FAILURES_PER_IP):
            # Unbound form: validating would still run the password hasher.
            limits.count('http_ratelimited_total{scope="login"}')
            return render(request, 'main/login.html', {'form': AuthenticationForm(request), 'error': THROTTLED},
                          status=429)
        if form.is_valid():
            limits.reset('login-user:' + user)
            login(request, form.get_user())
            return redirect('home')
        limits.hit('login-user:' + user, LOGIN_WINDOW)
        limits.hit('login-ip:' + ip, LOGIN_WINDOW)
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
def logout_view(request):
    logout(request)
    return redirect('starthome')
