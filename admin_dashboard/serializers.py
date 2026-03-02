from rest_framework import serializers
from accounts.models import User
from .models import AdminNotificationSettings, AdminReport

class UserAdminViewSerializer(serializers.ModelSerializer):
	status = serializers.SerializerMethodField()

	class Meta:
		model = User
		fields = ['full_name', 'email', 'status', 'joined_at', 'last_login']

	def get_status(self, obj):
		# TODO: Modify for support suspended status
		return "Active" if obj.is_active else "Inactive"

class AdminNotificationSettingsSerializer(serializers.Serializer):
    
    class Meta:
        model = AdminNotificationSettings
        fields = "__all__"


class AdminReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminReport
        fields = ['id', 'name', 'created_at', 'report_type', 'status', 'included_metrics', 'start_date', 'end_date', 'file']
