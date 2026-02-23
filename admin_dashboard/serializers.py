from rest_framework import serializers
from accounts.models import User

class UserAdminViewSerializer(serializers.ModelSerializer):
	status = serializers.SerializerMethodField()

	class Meta:
		model = User
		fields = ['full_name', 'email', 'status', 'campaigns', 'joined_at', 'last_login']

	def get_status(self, obj):
		# TODO: Modify for support suspended status
		return "Active" if obj.is_active else "Inactive"

