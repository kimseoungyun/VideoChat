from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from chat.models import Report


class Command(BaseCommand):
    help = 'Delete reports (and their chat evidence) older than REPORT_RETENTION_DAYS. Run daily.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=settings.REPORT_RETENTION_DAYS)

    def handle(self, *args, days, **options):
        deleted, _ = Report.objects.filter(created_at__lt=timezone.now() - timedelta(days=days)).delete()
        self.stdout.write(f'Deleted {deleted} report(s) older than {days} days.')
