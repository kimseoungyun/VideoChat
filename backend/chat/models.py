from django.conf import settings
from django.db import models
from django.utils import timezone


class Report(models.Model):
    """A user report kept for moderator review. Identities are account ids or hashed IPs."""

    class Reason(models.TextChoices):
        NUDITY = 'nudity', '부적절한 노출'
        HARASSMENT = 'harassment', '욕설·괴롭힘'
        SPAM = 'spam', '스팸·광고'
        OTHER = 'other', '기타'

    class Status(models.TextChoices):
        PENDING = 'pending', '검토 대기'
        UPHELD = 'upheld', '인정(제재)'
        DISMISSED = 'dismissed', '기각'

    reporter = models.CharField(max_length=32)
    reported = models.CharField(max_length=32, db_index=True)
    reason = models.CharField(max_length=20, choices=Reason.choices)
    match_id = models.CharField(max_length=32)
    banned = models.BooleanField(default=False, help_text='이 신고로 신고 누적 기준에 도달해 일시 제한됨')
    # Last chat lines the server itself relayed in this match, so the reporter cannot forge them.
    evidence = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_reason_display()} → {self.reported}'


class Sanction(models.Model):
    """A matching ban on an identity. Redis (`ban:<identity>`) enforces it; this row is the
    record moderators review, extend and lift."""

    class Source(models.TextChoices):
        AUTO = 'auto', '신고 누적 자동 제한'
        MODERATOR = 'moderator', '검토자 제재'

    identity = models.CharField(max_length=32, db_index=True)
    source = models.CharField(max_length=10, choices=Source.choices)
    report = models.ForeignKey(Report, null=True, blank=True, on_delete=models.SET_NULL, related_name='sanctions')
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField()
    lifted_at = models.DateTimeField(null=True, blank=True)
    lifted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='+')

    class Meta:
        ordering = ['-starts_at']

    @property
    def active(self):
        return self.lifted_at is None and self.ends_at > timezone.now()

    def __str__(self):
        return f'{self.identity} ~ {self.ends_at:%Y-%m-%d %H:%M}'


class Appeal(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', '검토 대기'
        ACCEPTED = 'accepted', '수용(제재 해제)'
        REJECTED = 'rejected', '기각'

    sanction = models.ForeignKey(Sanction, on_delete=models.CASCADE, related_name='appeals')
    message = models.TextField(max_length=1000)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
