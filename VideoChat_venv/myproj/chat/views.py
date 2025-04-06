from django.shortcuts import render
from django.shortcuts import redirect
from main.models import Room
import random

def start_chat(request):
    # 데이터베이스에서 사용자 수가 1인 방 찾기
    available_rooms = Room.objects.filter(user_count=1)

    if available_rooms.exists():
        # 사용자 수가 1인 방 중에서 랜덤으로 선택
        room_number = random.choice(available_rooms).room_number
    else:
        # 새로운 방 번호를 랜덤으로 생성하되, 기존 방 번호와 충돌하지 않도록 설정
        existing_rooms = Room.objects.values_list('room_number', flat=True)
        while True:
            new_room_number = random.randint(1, 100)  # 예: 1부터 100까지의 랜덤 숫자로 방 번호 생성.
            if new_room_number not in existing_rooms:
                break

        # 새 방 생성
        new_room = Room.objects.create(room_number=new_room_number)
        room_number = new_room.room_number

    # 방으로 리디렉션
    return redirect('chat:process', room_number) #chat url 중 process 이름을 가진 url로 리디렉션



def process(request, room_name):
    return render(request, 'chat/process.html', {'room_name': room_name})



def redirect_room(request, current_room):
    # 현재 방 번호를 제외한 방 목록을 가져옵니다.
    available_rooms = Room.objects.filter(user_count=1).exclude(id=current_room)  # 사용자 수가 1인 방 목록
    if available_rooms.exists():
        next_room = random.choice(available_rooms).room_number   # 랜덤으로 방 번호 선택
    else:
        # 새로운 방 번호를 랜덤으로 생성하되, 기존 방 번호와 충돌하지 않도록 설정
        existing_rooms = Room.objects.values_list('room_number', flat=True)
        while True:
            new_room_number = random.randint(1, 100)  # 예: 1부터 100까지의 랜덤 숫자로 방 번호 생성.
            if new_room_number not in existing_rooms:
                break

        # 새 방 생성
        new_room = Room.objects.create(room_number=new_room_number)
        next_room = new_room.room_number

    return redirect('chat:process', next_room) #chat url 중 process 이름을 가진 url로 리디렉션