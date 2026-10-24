from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.dispatch import receiver

class MainConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'main'

    def ready(self):
        post_migrate.connect(initialize_rooms)

@receiver(post_migrate)
def initialize_rooms(sender, **kwargs):
    from .models import Room
    if sender.name == 'main':
        Room.objects.all().delete()  # 모든 Room 데이터 삭제
