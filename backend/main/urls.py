from django.urls import path
from .views import (delete_account_view, home_view, login_view, logout_view, policy_view, signup_view,
                    starthome_view)

urlpatterns = [
    path('login/', login_view, name='login'),
    path('signup/', signup_view, name='signup'),
    path('home/', home_view, name='home'),
    path('home/delete/', delete_account_view, name='delete_account'),
    path('logout/', logout_view, name='logout'),
    path('terms/', policy_view, {'page': 'terms'}, name='terms'),
    path('privacy/', policy_view, {'page': 'privacy'}, name='privacy'),
    path('safety/', policy_view, {'page': 'safety'}, name='safety'),
    path('', starthome_view, name='starthome'),
]
