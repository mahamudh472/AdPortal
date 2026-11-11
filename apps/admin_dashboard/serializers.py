from rest_framework import serializers
from apps.accounts.models import User
from .models import AdminNotificationSettings, AdminReport
from apps.finance.models import Invoice

class UserAdminViewSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'full_name', 'role', 'email', 'status', 'joined_at', 'last_login']
    
    def get_role(self, obj):
        if obj.is_staff:
            return 'Admin'
        else:
            return 'User'


class AdminNotificationSettingsSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = AdminNotificationSettings
        fields = "__all__"


class AdminReportSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()

    def get_file(self, obj):
        if not obj.file:
            return None
        import os
        from django.urls import reverse
        ext = os.path.splitext(obj.file.name)[1] or '.xlsx'
        url = reverse('admin-report-file', kwargs={'report_id': obj.pk, 'filename': f'report{ext}'})
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url

    class Meta:
        model = AdminReport
        fields = ['id', 'name', 'created_at', 'report_type', 'status', 'included_metrics', 'start_date', 'end_date', 'file', 'file_size', 'download_count', 'generated_by']


class UpcomingInvoiceSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization.name')

    class Meta:
        model = Invoice
        fields = ['id', 'organization', 'amount', 'due_date', 'plan', 'status']

