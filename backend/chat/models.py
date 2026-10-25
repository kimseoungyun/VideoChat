from django.db import models


class Report(models.Model):
    """A user report kept for moderator review. Identities are account ids or hashed IPs."""

    class Reason(models.TextChoices):
        NUDITY = 'nudity', '부적절한 노출'
        HARASSMENT = 'harassment', '욕설·괴롭힘'
        SPAM = 'spam', '스팸·광고'
        OTHER = 'other', '기타'

    reporter = models.CharField(max_length=32)
    reported = models.CharField(max_length=32, db_index=True)
    reason = models.CharField(max_length=20, choices=Reason.choices)
    match_id = models.CharField(max_length=32)
    banned = models.BooleanField(default=False, help_text='이 신고로 신고 누적 기준에 도달해 일시 제한됨')
    # Last chat lines the server itself relayed in this match, so the reporter cannot forge them.
    evidence = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_reason_display()} → {self.reported}'
