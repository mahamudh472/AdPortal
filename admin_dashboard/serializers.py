from rest_framework import serializers
from rest_framework.fields import SerializerMethodField
from accounts.models import User
from main.models import Campaign

class UserAdminViewSerializer(serializers.ModelSerializer):
	plan = serializers.SerializerMethodField()
	status = serializers.SerializerMethodField()
	campaigns = serializers.SerializerMethodField()
	spend = serializers.SerializerMethodField()

	class Meta:
		model = User
		fields = ['first_name', 'last_name', 'email', 'plan', 'status', 'campaigns', 'spend', 'joined_at', 'last_login']

	def get_plan(self, obj):
		# TODO: Need to make this dynamic
		return "Demo"

	def get_status(self, obj):
		# TODO: Modify for support suspended status
		return "Active" if obj.is_active else "Inactive"

	def get_campaigns(self, obj):
		return Campaign.objects.filter(integration__user=obj).count()

	def get_spend(self, obj):
		# TODO: Need to dynamic this
		return 0
