from datetime import timedelta
from typing import Generator
from django.db.models import Sum
from django.utils import timezone
from rest_framework.generics import ListAPIView, GenericAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .serializers import PlanSerializer, SubscriptionSerializer
from main import serializers
from .models import Plan, Subscription
from rest_framework.exceptions import ValidationError
from rest_framework import status


class PlanListAPIView(ListAPIView):
	serializer_class = PlanSerializer
	queryset = Plan.objects.filter(is_active=True)

class BuyPlanAPIView(GenericAPIView):
	permission_classes = [IsAuthenticated]

	def post(self, request, *args, **kwargs):
		plan_id = request.data.get('plan_id', None)

		if not plan_id:
			return Response({'error': "Plan id is required."}, status=status.HTTP_400_BAD_REQUEST)

		plan = Plan.objects.filter(id=int(plan_id))
		if not plan.exists():
			return Response({'error': f"Plan not found with id {plan_id}"}, status=status.HTTP_400_BAD_REQUEST)

		# TODO: Create checkout session
		# Currently creating directly for testing.
		subscription = Subscription.objects.filter(plan=plan.first(), user=request.user)

		if subscription.exists():
			return Response({"message": "Subscription already exists"}, status=status.HTTP_200_OK)
		Subscription.objects.create(
				user=request.user,
				plan=plan.first(),
				status='active',
				current_period_start=timezone.now(),
				current_period_end=timezone.now() + timedelta(days=30)
			)
		return Response({'message': "Subscription created successfull"}, status=status.HTTP_201_CREATED)


class GetPlanAPIView(GenericAPIView):
	permission_classes = [IsAuthenticated]

	def get(self, request, *args, **kwargs):
		subscription = Subscription.objects.filter(user=request.user, status='active').select_related('plan').first()

		plan_name = subscription.plan.name
		campaign_limit = subscription.plan.features.filter(key="feature_1").first().value.split()[0]
		campaign_used = subscription.usage_records.filter(feature_key="feature_1").aggregate(total_used=Sum('used'))['total_used'] or 0

		return Response({
				'plan_name': plan_name,
				'campaign_limit': int(campaign_limit),
				'campaign_used': campaign_used
			})

