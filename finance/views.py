from django.db.models import Sum
from rest_framework.generics import ListAPIView, GenericAPIView
from rest_framework.response import Response
from main.mixins import RequiredOrganizationIDMixin
from accounts.permissions import IsOrganizationMember, IsRegularPlatformUser, IsAdminOrOwnerOfOrganization
from .serializers import PlanSerializer
from main import serializers
from .models import Payment, Plan, Subscription
from rest_framework import status
from main.models import Organization
import stripe
from django.conf import settings
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

stripe.api_key = settings.STRIPE_SECRET_KEY


class PlanListAPIView(ListAPIView):
    serializer_class = PlanSerializer
    queryset = Plan.objects.filter(is_active=True)

class BuyPlanAPIView(RequiredOrganizationIDMixin, GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsAdminOrOwnerOfOrganization]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="org_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Organization Snowflake ID"
            )
        ]
    )
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
        print(f"Created subscription {subscription.id} for organization {organization_snowflake_id} and plan {plan.first().name}")

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
            success_url= settings.FRONTEND_URL + '/payment/success',
            cancel_url= settings.FRONTEND_URL + '/payment/cancel',
            metadata={
                'plan_id': str(plan.first().id),
                'organization_id': str(organization_snowflake_id),
                'subscription_id': str(subscription.id)
            }
        )

        return Response({'checkout_url': session.url}, status=status.HTTP_200_OK)



class GetPlanAPIView(RequiredOrganizationIDMixin, GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="org_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Organization Snowflake ID"
            )
        ]
    )
    def get(self, request, *args, **kwargs):
        organization_snowflake_id = self.get_org_id()
        organization = Organization.objects.get(snowflake_id=organization_snowflake_id)
        subscription = Subscription.objects.filter(organization=organization, status='active').select_related('plan')
        if not subscription.exists():
            return Response({'error': "No active subscription found for this organization."}, status=status.HTTP_404_NOT_FOUND)
        subscription = subscription.first()

        plan_name = subscription.plan.name
        limit = subscription.plan.get_campaign_limit()
        campaign_limit = 'Unlimited' if limit is None else limit
        campaign_used = subscription.usage_records.filter(feature_key="campaign_limit").aggregate(total_used=Sum('used'))['total_used'] or 0

        return Response({
                'plan_name': plan_name,
                'campaign_limit': campaign_limit,
                'campaign_used': campaign_used
            })


class BillingHistoryAPIView(RequiredOrganizationIDMixin, GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsAdminOrOwnerOfOrganization]

    def get(self, request, *args, **kwargs):
        organization_snowflake_id = self.get_org_id()
        organization = Organization.objects.get(snowflake_id=organization_snowflake_id)

        billing_history = Payment.objects.filter(organization=organization).order_by('-paid_at')

        serializer = serializers.BillingHistorySerializer(billing_history, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
