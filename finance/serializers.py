from rest_framework import fields, serializers
from .models import Plan, PlanFeature, Subscription

class PlanFeatureSerializer(serializers.ModelSerializer):

	class Meta:
		model = PlanFeature
		fields = ['key', 'value']

class PlanSerializer(serializers.ModelSerializer):
	features = PlanFeatureSerializer(many=True, read_only=True)
	class Meta:
		model = Plan
		fields = ['id', 'name', 'price', 'description', 'interval', 'features']

class SubscriptionSerializer(serializers.ModelSerializer):
	plan_name = serializers.CharField(source='plan.name', read_only=True)
	campaign_limit = serializers.SerializerMethodField()
	campaign_used = serializers.SerializerMethodField()
	class Meta:
		model = Subscription
		fields = ['plan_name', 'campaign_limit'], 'campaign_used'

	def get_campaign_limit(self):
		limit = self.plan.features.filter(key='feature_1').first().value.split()[0]

		return int(limit)

	def get_campaign_used(self):
		# TODO: Need to make this dynamic
		used = 0

		return int(used)