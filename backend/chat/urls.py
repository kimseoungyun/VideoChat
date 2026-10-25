from django.urls import path
from . import views
app_name = 'chat'
urlpatterns = [
    path('', views.process, name='lobby'),
    path('rtc-config/', views.rtc_config, name='rtc_config'),
    path('consent/', views.consent, name='consent'),
    path('verify/', views.verify, name='verify'),
    path('verify/callback/', views.verify_callback, name='verify_callback'),
    path('appeal/<str:code>/', views.appeal, name='appeal'),
    path('start_chat/', views.start_chat, name='start_chat'),
    path('redirect_room/<str:current_room>/', views.redirect_room, name='redirect_room'),
    path('<str:room_name>/', views.process, name='process'),
]
