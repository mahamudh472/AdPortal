from rest_framework import serializers
from .models import AnalysisDaily, Report, ScheduledReport


class ReportSerializer(serializers.ModelSerializer):
    # Reports are private: ``file`` is an authenticated download URL, never a /media/ path.
    file = serializers.SerializerMethodField()

    def get_file(self, obj):
        if not obj.file:
            return None
        import os
        from django.urls import reverse
        ext = os.path.splitext(obj.file.name)[1] or '.xlsx'
        url = reverse('report-download', kwargs={'pk': obj.pk, 'filename': f'report{ext}'})
        url = f"{url}?org_id={obj.organization.snowflake_id}"
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url

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
