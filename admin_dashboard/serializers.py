from rest_framework import serializers
from accounts.models import User
from .models import AdminNotificationSettings, AdminReport

class UserAdminViewSerializer(serializers.ModelSerializer):

	class Meta:
		model = User
		fields = ['id', 'full_name', 'email', 'status', 'joined_at', 'last_login']


class AdminNotificationSettingsSerializer(serializers.Serializer):
    
    class Meta:
        model = AdminNotificationSettings
        fields = "__all__"


class AdminReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminReport
        fields = ['id', 'name', 'created_at', 'report_type', 'status', 'included_metrics', 'start_date', 'end_date', 'file']
