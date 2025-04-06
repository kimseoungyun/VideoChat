from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from .models import Room
from .forms import CustomUserCreationForm
from django.contrib import messages



def starthome_view(request):
    return render(request, 'main/starthome.html')


def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']
        user = authenticate(request, username=username, email=email, password=password)  #왜 로그인하면 none이라고 뜰까요...
        if user is not None:
            login(request, user)
            return redirect('home')
        else:
            # popup_message = ' '.join([error for errors in user.errors.values() for error in errors])
            return render(request, 'main/login.html', {'popup_message': '로그인 실패'})

    return render(request, 'main/login.html')


def signup_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']
        #이메일 검증 조건문 추가하기
        user = User.objects.create_user(username=username, email=email, password=password)
        user.save()
        return redirect('login')  # 회원가입 후 로그인 페이지로 이동
    return render(request, 'main/signup.html')


@login_required
def home_view(request):
    return render(request, 'main/home.html')

@login_required
def logout_view(request):
    logout(request)
    return redirect('login')
