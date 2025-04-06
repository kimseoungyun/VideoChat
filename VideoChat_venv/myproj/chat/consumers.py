import json
from channels.generic.websocket import AsyncWebsocketConsumer
import asyncio
from main.models import Room
from channels.db import database_sync_to_async

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = f'chat_{self.room_name}'

        # 방 정보를 가져오고 존재하지 않으면 생성
        try:
            room_instance = await database_sync_to_async(Room.objects.get)(room_number=int(self.room_name))
            # 방이 존재할 경우 사용자 수 증가
            room_instance.user_count += 1
            await database_sync_to_async(room_instance.save)()
        except Room.DoesNotExist:
            # 방이 존재하지 않으면 새로 생성
            room_instance = await database_sync_to_async(Room.objects.create)(room_number=int(self.room_name), user_count=1)
            

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()
            
        # 입장 메시지 생성 및 클라이언트에게 전송
        join_message = f"[{self.scope['user'].username}님이 입장했습니다.]"
        await self.send(text_data=json.dumps({
            'join': join_message
            }))


    async def disconnect(self, close_code):
        # 방의 사용자 수를 데이터베이스에서 감소시킵니다.
        room = await database_sync_to_async(Room.objects.get)(room_number=int(self.room_name))
        if room.user_count > 0:
            room.user_count -= 1
            await database_sync_to_async(room.save)()  # 변경 사항 저장


        # 퇴장 메시지 생성 및 클라이언트에게 전송
        out_message = f"[{self.scope['user'].username}님이 나갔습니다.]"
        # await self.send(text_data=json.dumps({
        #     'out': out_message
        #     }))
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_message',
                'usermessage': out_message,
                'sender': self.channel_name  # 메시지를 보낸 클라이언트 정보 추가
            }
        )

        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

        # 방의 사용자 수가 0이 되면 데이터베이스에서 방 삭제
        if room.user_count == 0:
            # 데이터베이스에서 방 번호 삭제 또는 업데이트
            await database_sync_to_async(Room.objects.filter(room_number=int(self.room_name)).delete)()  # 방 삭제 예시



    async def receive(self, text_data):
        data = json.loads(text_data)

        # 메시지 전송 처리
        if 'message' in data:
            # 다른 클라이언트에게만 메시지 전송
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'message': data['message'],
                    'sender': self.channel_name  # 메시지를 보낸 클라이언트 정보 추가
                }
            )
        elif 'usermessage' in data:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'user_message',
                    'usermessage': data['usermessage'],
                    'sender': self.channel_name  # 메시지를 보낸 클라이언트 정보 추가
                }
            )   
        
        # SDP 처리
        elif 'sdp' in data:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'sdp_message',
                    'sdp': data['sdp'],
                    'sender': self.channel_name  # SDP를 보낸 클라이언트 정보 추가
                }
            )

        # ICE 후보 처리
        elif 'candidate' in data:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'ice_candidate',
                    'candidate': data['candidate'],
                    'sender': self.channel_name  # 후보를 보낸 클라이언트 정보 추가
                }
            )

        # 비디오 상태 처리
        elif 'videoEnabled' in data:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'video_status',
                    'video_enabled': data['videoEnabled'],
                    'sender': self.channel_name  # 비디오 상태를 보낸 클라이언트 정보 추가
                }
            )

        # 오디오 상태 처리
        elif 'audioEnabled' in data:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'audio_status',
                    'audio_enabled': data['audioEnabled'],
                    'sender': self.channel_name  # 오디오 상태를 보낸 클라이언트 정보 추가
                }
            )

    async def chat_message(self, event):
        message = event['message']
        sender = event['sender']

        # 보낸 클라이언트를 확인하여 자신의 메시지는 제외
        if sender != self.channel_name:
            await self.send(text_data=json.dumps({
                'message': message,
                'username': self.scope['user'].username  # 사용자 이름 추가
            }))

    async def user_message(self, event):
        message = event['usermessage']
        sender = event['sender']

        # 보낸 클라이언트를 확인하여 자신의 메시지는 제외
        if sender != self.channel_name:
            await self.send(text_data=json.dumps({
                'usermessage': message,
                'username': self.scope['user'].username  # 사용자 이름 추가
            }))

    async def sdp_message(self, event):
        sdp = event['sdp']
        sender = event['sender']
        if sender != self.channel_name:
            await self.send(text_data=json.dumps({
                'sdp': sdp
            }))

    async def ice_candidate(self, event):
        candidate = event['candidate']
        sender = event['sender']
        if sender != self.channel_name:
            await self.send(text_data=json.dumps({
                'candidate': candidate
            }))

    async def video_status(self, event):
        video_enabled = event['video_enabled']
        sender = event['sender']
        if sender != self.channel_name:
            await self.send(text_data=json.dumps({
                'videoEnabled': video_enabled
            }))

    async def audio_status(self, event):
        audio_enabled = event['audio_enabled']
        sender = event['sender']
        if sender != self.channel_name:
            await self.send(text_data=json.dumps({
                'audioEnabled': audio_enabled
            }))
