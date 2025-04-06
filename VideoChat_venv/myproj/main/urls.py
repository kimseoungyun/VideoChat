from django.urls import path
from .views import login_view, signup_view, home_view, logout_view, starthome_view

urlpatterns = [
    path('login/', login_view, name='login'),
    path('signup/', signup_view, name='signup'),
    path('home/', home_view, name='home'),
    path('logout/', logout_view, name='logout'),
    path('', starthome_view, name='starthome'),
]
