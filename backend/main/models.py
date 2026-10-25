# Legacy model. AUTH_USER_MODEL never pointed here, so authentication uses auth.User.
# The table is kept because existing databases may hold rows in it; drop it in a
# separate, explicit migration once those rows are confirmed disposable.
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
