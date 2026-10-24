from django.urls import path
from . import views
app_name = 'chat'
urlpatterns = [
    path('', views.process, name='lobby'),
    path('rtc-config/', views.rtc_config, name='rtc_config'),
    path('start_chat/', views.start_chat, name='start_chat'),
    path('redirect_room/<str:current_room>/', views.redirect_room, name='redirect_room'),
    path('<str:room_name>/', views.process, name='process'),
]
