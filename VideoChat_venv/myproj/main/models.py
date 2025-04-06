# main/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser


class Room(models.Model):
    room_number = models.PositiveIntegerField(unique=True)  # 방 번호는 고유해야 합니다.
    user_count = models.PositiveIntegerField(default=0)      # 사용자 수
    created_at = models.DateTimeField(auto_now_add=True)    # 방 생성 시간

    def __str__(self):
        return f"Room {self.room_number}"

# myapp/models.py
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db import models

class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    USERNAME_FIELD = 'username'  # 이메일을 사용자 이름으로 설정
    REQUIRED_FIELDS = ['email']  # 필수 필드 설정 (username은 생략 가능)

    # phone_number = models.CharField(max_length=15, blank=True)

    
    # 이 밑에 group과 user_permissions을 해야지 작동하는지 모르겠다. allauth 이전에는 없이도 잘됐는데....
    groups = models.ManyToManyField(
        Group,
        related_name='customuser_set',  # related_name 추가
        blank=True,
        help_text='The groups this user belongs to.',
        verbose_name='groups',
    )

    user_permissions = models.ManyToManyField(
        Permission,
        related_name='customuser_set',  # related_name 추가
        blank=True,
        help_text='Specific permissions for this user.',
        verbose_name='user permissions',
    )

    # def __str__(self):
    #     return self.email
