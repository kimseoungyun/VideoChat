# main/management/commands/initialize_db.py

from django.core.management.base import BaseCommand
from ...models import Room

class Command(BaseCommand):
    help = 'Initialize the database with default data'

    def handle(self, *args, **kwargs):
        Room.objects.all().delete()  # 모든 Room 데이터 삭제
        self.stdout.write(self.style.SUCCESS('Database initialized successfully.'))
