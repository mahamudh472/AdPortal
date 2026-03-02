from rest_framework import fields, serializers
from .models import Plan, PlanFeature, Subscription, Payment

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

class PaymentSerializer(serializers.ModelSerializer):
    # Needed fields: organization, plan, amount, payment method, statys, date
    organization = serializers.CharField(source='organization.name', read_only=True)
    plan = serializers.SerializerMethodField()
    payment_method = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ['id', 'organization', 'plan', 'amount', 'payment_method', 'status', 'created_at']

    def get_payment_method(self, obj):
        return "stripe"
    def get_plan(self, obj):
        return obj.subscription.plan.name if obj.subscription and obj.subscription.plan else None
