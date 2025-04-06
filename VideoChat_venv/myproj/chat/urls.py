from django.urls import path
from . import views

app_name = 'chat'  # 네임스페이스 설정. 프로젝트 url에서 namespace를 설정하고 그 이름을 여기에 적어준다. 왜냐하면 redirect할 때, 'chat:'을 사용하기 때문에.

urlpatterns = [
    path('start_chat/', views.start_chat, name='start_chat'),  # 방 시작 처리
    path('<str:room_name>/', views.process, name='process'),
    path('redirect_room/<str:current_room>/', views.redirect_room, name='redirect_room'),  # 방 리디렉션 경로 추가
]
