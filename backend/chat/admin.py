from django.contrib import admin
from django.utils.html import format_html_join
from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'reason', 'reported', 'reporter', 'banned', 'lines')
    list_filter = ('reason', 'banned')
    search_fields = ('reported', 'reporter', 'match_id')
    readonly_fields = ('reporter', 'reported', 'reason', 'match_id', 'banned', 'created_at', 'conversation')
    exclude = ('evidence',)

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
