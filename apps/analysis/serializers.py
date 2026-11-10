from rest_framework import serializers
from .models import AnalysisDaily, Report, ScheduledReport


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = [
            'id', 'name', 'created_at', 'report_type', 'file', 'status',
            'start_date', 'end_date', 'included_platforms', 'included_metrics',
        ]


class ScheduledReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduledReport
        fields = ['id', 'title', 'schedule', 'frequency', 'enabled', 'included_metrics']
        read_only_fields = ['id', 'schedule']
