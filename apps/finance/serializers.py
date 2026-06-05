from django.db.models import Sum
from rest_framework import fields, serializers
from .models import Plan, PlanFeature, Subscription, Payment

class PlanFeatureSerializer(serializers.ModelSerializer):
	# `value` surfaces the display text so the frontend contract stays unchanged.
	value = serializers.CharField(source='display')

	class Meta:
		model = PlanFeature
		fields = ['key', 'value']

class PlanSerializer(serializers.ModelSerializer):
	# Only expose features that have display text (internal tracking features are excluded).
	features = serializers.SerializerMethodField()

	class Meta:
		model = Plan
		fields = ['id', 'name', 'price', 'description', 'interval', 'features']

	def get_features(self, obj):
		qs = obj.features.filter(display__isnull=False).exclude(display='')
		return PlanFeatureSerializer(qs, many=True).data

class SubscriptionSerializer(serializers.ModelSerializer):
	plan_name = serializers.CharField(source='plan.name', read_only=True)
	campaign_limit = serializers.SerializerMethodField()
	campaign_used = serializers.SerializerMethodField()
	class Meta:
		model = Subscription
		fields = ['plan_name', 'campaign_limit', 'campaign_used']

	def get_campaign_limit(self, obj):
		# None means unlimited — return the string the frontend expects.
		limit = obj.plan.get_campaign_limit()
		return 'Unlimited' if limit is None else limit

	def get_campaign_used(self, obj):
		return obj.usage_records.filter(feature_key="campaign_limit").aggregate(
			total_used=Sum('used')
		)['total_used'] or 0

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
