from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from chat.models import Report, Sanction


class Command(BaseCommand):
    help = ('Delete reports (with their chat evidence) and sanctions (with their appeals) older than '
            'REPORT_RETENTION_DAYS, as the privacy policy states. Run daily.')

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=settings.REPORT_RETENTION_DAYS)

    def handle(self, *args, days, **options):
        cutoff = timezone.now() - timedelta(days=days)
        reports, _ = Report.objects.filter(created_at__lt=cutoff).delete()
        # A sanction is kept while it runs and for the retention period after it ends.
        sanctions, _ = Sanction.objects.filter(ends_at__lt=cutoff).delete()
        self.stdout.write(f'Deleted {reports} report row(s) and {sanctions} sanction row(s) older than {days} days.')
