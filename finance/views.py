from datetime import timedelta
from typing import Generator
from django.db.models import Sum
from django.shortcuts import redirect
from django.utils import timezone
from openai import organization
from requests import session
from rest_framework.generics import ListAPIView, GenericAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from main.mixins import RequiredOrganizationIDMixin
from accounts.permissions import IsRegularPlatformUser
from .serializers import PlanSerializer, SubscriptionSerializer
from main import serializers
from .models import Payment, Plan, Subscription
from rest_framework.exceptions import ValidationError
from rest_framework import status
from main.models import Organization
import stripe
from django.conf import settings
stripe.api_key = settings.STRIPE_SECRET_KEY


class PlanListAPIView(ListAPIView):
	serializer_class = PlanSerializer
	queryset = Plan.objects.filter(is_active=True)

class BuyPlanAPIView(RequiredOrganizationIDMixin, GenericAPIView):
	permission_classes = [IsAuthenticated]

	def post(self, request, *args, **kwargs):
		plan_id = request.data.get('plan_id', None)

		if not plan_id:
			return Response({'error': "Plan id is required."}, status=status.HTTP_400_BAD_REQUEST)

		plan = Plan.objects.filter(id=int(plan_id))
		if not plan.exists():
			return Response({'error': f"Plan not found with id {plan_id}"}, status=status.HTTP_400_BAD_REQUEST)

		# Currently creating directly for testing.
		organization_snowflake_id = self.get_org_id()
		subscription = Subscription.objects.filter(
			plan=plan.first(), 
			organization__snowflake_id=organization_snowflake_id,
			status='active'

		)

		if subscription.exists():
			return Response({"message": "Subscription already exists"}, status=status.HTTP_200_OK)
		
		organization = Organization.objects.get(snowflake_id=organization_snowflake_id)
		subscription = Subscription.objects.create(
			organization=organization,
			plan=plan.first(),
			status='incomplete',
		)

		session = stripe.checkout.Session.create(
			payment_method_types=['card'],
			line_items=[{
				# Add multiple items
				'price_data': {
					'currency': 'usd',
					'product_data':{
						'name': f'{plan.first().name} Plan',
					},
					'unit_amount': int(plan.first().price * 100),  # Amount in cents
					'recurring': {'interval': plan.first().interval},
				},
				'quantity': 1
			}],
			mode='subscription',
			success_url='http://127.0.0.1:8000/success',
			cancel_url='http://127.0.0.1:8000/cancel',
			metadata={
				'plan_id': str(plan.first().id),
				'organization_id': str(organization_snowflake_id),
			}
		)
		
		return Response({'checkout_url': session.url}, status=status.HTTP_200_OK)



class GetPlanAPIView(RequiredOrganizationIDMixin, GenericAPIView):
	permission_classes = [IsAuthenticated]

	def get(self, request, *args, **kwargs):
		organization_snowflake_id = self.get_org_id()
		organization = Organization.objects.get(snowflake_id=organization_snowflake_id)
		subscription = Subscription.objects.filter(organization=organization, status='active').select_related('plan')
		if not subscription.exists():
			return Response({'error': "No active subscription found."}, status=status.HTTP_404_NOT_FOUND)
		
		subscription = subscription.first()

		plan_name = subscription.plan.name
		campaign_limit = subscription.plan.features.filter(key="feature_1").first().value.split()[0]
		campaign_used = subscription.usage_records.filter(feature_key="feature_1").aggregate(total_used=Sum('used'))['total_used'] or 0

		return Response({	
				'plan_name': plan_name,
				'campaign_limit': subscription.plan.get_campaign_limit(),
				'campaign_used': campaign_used
			})


class BillingHistoryAPIView(RequiredOrganizationIDMixin, GenericAPIView):
	permission_classes = [IsRegularPlatformUser]

	def get(self, request, *args, **kwargs):
		user = request.user
		organization_snowflake_id = self.get_org_id()
		organization = Organization.objects.get(snowflake_id=organization_snowflake_id)
		# Assuming BillingHistory model exists and has a foreign key to Organization
		billing_history = Payment.objects.filter(organization=organization).order_by('-paid_at')

		serializer = serializers.BillingHistorySerializer(billing_history, many=True)
		return Response(serializer.data, status=status.HTTP_200_OK)
