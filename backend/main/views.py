from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from .forms import CustomUserCreationForm


def starthome_view(request):
    return redirect('chat:lobby')


def login_view(request):
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        return redirect('home')
    return render(request, 'main/login.html', {'form': form})


def signup_view(request):
    form = CustomUserCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
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
