from datetime import timedelta
from django.conf import settings
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html_join
from . import sanctions
from .models import Appeal, Report, Sanction


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'status', 'reason', 'reported', 'reporter', 'banned', 'lines')
    list_filter = ('status', 'reason', 'banned')
    search_fields = ('reported', 'reporter', 'match_id')
    readonly_fields = ('reporter', 'reported', 'reason', 'match_id', 'banned', 'created_at', 'conversation',
                       'status', 'reviewed_by', 'reviewed_at')
    exclude = ('evidence',)
    actions = ('uphold', 'dismiss')

    @admin.display(description='대화 줄 수')
    def lines(self, report):
        return len(report.evidence)

    @admin.display(description='최근 대화 (서버 중계 기록)')
    def conversation(self, report):
        names = {'me': '신고자', 'peer': '신고 대상'}
        return format_html_join(
            '', '<p><strong>{}</strong> <small>{}</small><br>{}</p>',
            ((names.get(line.get('from'), '?'), line.get('at', ''), line.get('text', '')) for line in report.evidence),
        ) or '-'

    def review(self, request, report, status):
        report.status, report.reviewed_by, report.reviewed_at = status, request.user, timezone.now()
        report.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])

    @admin.action(description=f'신고 인정: 대상에게 {settings.SANCTION_DAYS}일 매칭 제재')
    def uphold(self, request, queryset):
        for report in queryset:
            self.review(request, report, Report.Status.UPHELD)
            sanctions.impose(report.reported, timedelta(days=settings.SANCTION_DAYS), Sanction.Source.MODERATOR, report)
        messages.success(request, f'{queryset.count()}건을 인정하고 제재했습니다.')

    @admin.action(description='신고 기각: 이 신고로 생긴 자동 제한 해제')
    def dismiss(self, request, queryset):
        for report in queryset:
            self.review(request, report, Report.Status.DISMISSED)
            for sanction in report.sanctions.filter(lifted_at__isnull=True):
                sanctions.lift(sanction, request.user)
        messages.success(request, f'{queryset.count()}건을 기각했습니다.')


@admin.register(Sanction)
class SanctionAdmin(admin.ModelAdmin):
    list_display = ('identity', 'source', 'starts_at', 'ends_at', 'is_active', 'lifted_at')
    list_filter = ('source',)
    search_fields = ('identity',)
    readonly_fields = ('identity', 'source', 'report', 'starts_at', 'ends_at', 'lifted_at', 'lifted_by')
    actions = ('lift_now',)

    @admin.display(boolean=True, description='유효')
    def is_active(self, sanction):
        return sanction.active

    @admin.action(description='제재 해제')
    def lift_now(self, request, queryset):
        for sanction in queryset.filter(lifted_at__isnull=True):
            sanctions.lift(sanction, request.user)


@admin.register(Appeal)
class AppealAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'status', 'sanction', 'message')
    list_filter = ('status',)
    readonly_fields = ('sanction', 'message', 'created_at', 'status', 'decided_by', 'decided_at')
    actions = ('accept', 'reject')

    def decide(self, request, appeal, status):
        appeal.status, appeal.decided_by, appeal.decided_at = status, request.user, timezone.now()
        appeal.save(update_fields=['status', 'decided_by', 'decided_at'])

    @admin.action(description='이의 수용: 제재 해제')
    def accept(self, request, queryset):
        for appeal in queryset.filter(status=Appeal.Status.PENDING):
            self.decide(request, appeal, Appeal.Status.ACCEPTED)
            if appeal.sanction.lifted_at is None:
                sanctions.lift(appeal.sanction, request.user)

    @admin.action(description='이의 기각')
    def reject(self, request, queryset):
        for appeal in queryset.filter(status=Appeal.Status.PENDING):
            self.decide(request, appeal, Appeal.Status.REJECTED)
