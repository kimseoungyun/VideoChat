from django.contrib import admin
from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'reason', 'reported', 'reporter', 'banned')
    list_filter = ('reason', 'banned')
    search_fields = ('reported', 'reporter', 'match_id')
    readonly_fields = ('reporter', 'reported', 'reason', 'match_id', 'banned', 'created_at')
