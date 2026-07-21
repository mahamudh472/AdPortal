from rest_framework import serializers
from apps.accounts.models import User
from .models import AdminNotificationSettings, AdminReport

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
    class Meta:
        model = AdminReport
        fields = ['id', 'name', 'created_at', 'report_type', 'status', 'included_metrics', 'start_date', 'end_date', 'file', 'file_size', 'download_count', 'generated_by']
