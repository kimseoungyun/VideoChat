"""Sanction records (SQL) kept in step with the ban keys the matcher enforces (Redis)."""
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from .limits import sync_redis
from .models import Sanction


def ban_key(identity):
    return settings.MATCHMAKING_PREFIX + 'ban:' + identity


def sync_ban(identity):
    """Make the Redis ban match the longest active sanction for this identity (or remove it)."""
    latest = (Sanction.objects.filter(identity=identity, lifted_at__isnull=True, ends_at__gt=timezone.now())
              .order_by('-ends_at').first())
    if latest:
        seconds = max(1, int((latest.ends_at - timezone.now()).total_seconds()))
        sync_redis().set(ban_key(identity), '1', ex=seconds)
    else:
        sync_redis().delete(ban_key(identity))


def impose(identity, duration, source, report=None):
    sanction = Sanction.objects.create(identity=identity, source=source, report=report,
                                       ends_at=timezone.now() + duration)
    sync_ban(identity)
    return sanction


def lift(sanction, by=None):
    sanction.lifted_at, sanction.lifted_by = timezone.now(), by
    sanction.save(update_fields=['lifted_at', 'lifted_by'])
    sync_ban(sanction.identity)


def record_auto_ban(identity, report):
    """The matcher already set the Redis ban; keep the reviewable record."""
    return Sanction.objects.create(identity=identity, source=Sanction.Source.AUTO, report=report,
                                   ends_at=timezone.now() + timedelta(seconds=settings.REPORT_BAN_SECONDS))


def appeal_key(code):
    return settings.MATCHMAKING_PREFIX + 'appeal:' + code
