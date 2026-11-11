from django.db.models import Sum
from django.db import transaction
from rest_framework.generics import ListAPIView, GenericAPIView
from rest_framework.response import Response
from apps.main.mixins import RequiredOrganizationIDMixin
from apps.accounts.permissions import IsOrganizationMember, IsRegularPlatformUser, IsAdminOrOwnerOfOrganization
from .serializers import PlanSerializer
from apps.main import serializers
from .models import Payment, Plan, Subscription
from rest_framework import status
from apps.main.models import Organization
import calendar
import stripe
from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

stripe.api_key = settings.STRIPE_SECRET_KEY

_ORG_ID_PARAM = OpenApiParameter(
    name="org_id",
    type=OpenApiTypes.INT,
    location=OpenApiParameter.QUERY,
    required=True,
    description="Organization Snowflake ID",
)


class PlanListAPIView(ListAPIView):
    from rest_framework.permissions import AllowAny as _AllowAny
    permission_classes = [_AllowAny]
    authentication_classes = []
    serializer_class = PlanSerializer
    queryset = Plan.objects.filter(is_active=True)
    CACHE_KEY = 'finance:plans:list'
    CACHE_TTL = 300  # invalidated immediately when a Plan / PlanFeature changes

    def list(self, request, *args, **kwargs):
        from django.core.cache import cache
        data = cache.get(self.CACHE_KEY)
        if data is None:
            data = self.get_serializer(self.filter_queryset(self.get_queryset()), many=True).data
            cache.set(self.CACHE_KEY, data, self.CACHE_TTL)
        return Response(data)


class BuyPlanAPIView(RequiredOrganizationIDMixin, GenericAPIView):
    """
    Purchase or change a subscription plan.

    - **Upgrade** (higher-priced plan): applied immediately; Stripe prorates
      the current billing period and invoices/charges right away.
    - **Downgrade** (lower-priced plan): scheduled for the next billing cycle;
      the organisation keeps its current plan until the period ends.
    - **No existing subscription**: starts a new Stripe Checkout session as
      before.
    """

    permission_classes = [IsRegularPlatformUser, IsAdminOrOwnerOfOrganization]

    @extend_schema(parameters=[_ORG_ID_PARAM])
    def post(self, request, *args, **kwargs):
        plan_id = request.data.get("plan_id")
        if not plan_id:
            return Response(
                {"error": "plan_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            new_plan = Plan.objects.get(id=int(plan_id), is_active=True)
        except Plan.DoesNotExist:
            return Response(
                {"error": f"Plan not found with id {plan_id}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        organization_snowflake_id = self.get_org_id()
        organization = Organization.objects.get(snowflake_id=organization_snowflake_id)

        # ── Check for an existing active subscription ──────────────────────
        # select_for_update serialises concurrent requests for the same org
        # at the DB level so only one proceeds at a time.
        with transaction.atomic():
            active_sub = (
                Subscription.objects.select_for_update(of=('self',))
                .filter(organization=organization, status="active")
                .select_related("plan", "pending_plan")
                .first()
            )

            if active_sub:
                current_plan = active_sub.plan

                if current_plan.id == new_plan.id:
                    return Response(
                        {"message": "You are already subscribed to this plan."},
                        status=status.HTTP_200_OK,
                    )

                if not active_sub.stripe_subscription_id:
                    return Response(
                        {"error": "Active subscription has no Stripe ID. Cannot modify."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Idempotency: downgrade to this plan is already queued
                if (
                    active_sub.pending_plan
                    and active_sub.pending_plan.id == new_plan.id
                ):
                    return Response(
                        {
                            "message": f"Downgrade to the {new_plan.name} plan is already "
                                       "scheduled for the end of your current billing cycle."
                        },
                        status=status.HTTP_200_OK,
                    )

                is_upgrade = new_plan.price > current_plan.price

                # Retrieve the Stripe subscription to get the subscription-item ID
                stripe_sub = stripe.Subscription.retrieve(active_sub.stripe_subscription_id)
                stripe_item_id = stripe_sub["items"]["data"][0]["id"]
                current_stripe_price_id = stripe_sub["items"]["data"][0]["price"]["id"]
                existing_schedule_id = stripe_sub.get("schedule")

                # current_period_end may be absent immediately after a billing-cycle
                # reset (e.g. an upgrade with billing_cycle_anchor='now').
                # Fall back to our locally-stored value in that case.
                _cpe_stripe = stripe_sub.get("current_period_end")
                if _cpe_stripe:
                    current_period_end = int(_cpe_stripe)
                elif active_sub.current_period_end:
                    current_period_end = calendar.timegm(
                        active_sub.current_period_end.timetuple()
                    )
                else:
                    current_period_end = None

                # Resolve the Stripe price ID for the new plan
                new_stripe_price_id = self._get_or_create_stripe_price(new_plan)

                if is_upgrade:
                    # ── Immediate upgrade ──────────────────────────────────────
                    # If a downgrade schedule was previously queued, release it first
                    # so the upgrade can be applied cleanly.
                    if existing_schedule_id:
                        try:
                            stripe.SubscriptionSchedule.release(existing_schedule_id)
                        except stripe.error.InvalidRequestError:
                            pass  # already released or not applicable

                    stripe.Subscription.modify(
                        active_sub.stripe_subscription_id,
                        items=[{"id": stripe_item_id, "price": new_stripe_price_id}],
                        proration_behavior="always_invoice",  # charge the difference now
                        billing_cycle_anchor="now",           # reset billing cycle
                    )
                    # Update local record; clear any pending downgrade too
                    active_sub.plan = new_plan
                    active_sub.pending_plan = None
                    active_sub.save(update_fields=["plan", "pending_plan"])

                    return Response(
                        {
                            "message": f"Successfully upgraded to the {new_plan.name} plan. "
                                       "You have been charged the prorated difference."
                        },
                        status=status.HTTP_200_OK,
                    )
                else:
                    # ── Scheduled downgrade via Subscription Schedule ──────────
                    # We use a SubscriptionSchedule so the price on the Stripe
                    # subscription object does NOT change until the billing cycle
                    # ends.  This prevents our webhook from seeing a price change
                    # and applying it immediately.
                    if not current_period_end:
                        return Response(
                            {"error": "Unable to determine the current billing period end. "
                                      "Please try again in a moment."},
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    if existing_schedule_id:
                        # An existing schedule is already attached — update its phases
                        schedule = stripe.SubscriptionSchedule.retrieve(existing_schedule_id)
                        stripe.SubscriptionSchedule.modify(
                            existing_schedule_id,
                            end_behavior="release",
                            phases=[
                                {
                                    "items": [{"price": current_stripe_price_id, "quantity": 1}],
                                    "start_date": schedule["phases"][0]["start_date"],
                                    "end_date": current_period_end,
                                },
                                {
                                    "items": [{"price": new_stripe_price_id, "quantity": 1}],
                                },
                            ],
                        )
                    else:
                        # No schedule yet — create one.
                        # Guard against a concurrent request that already created
                        # the schedule between our retrieve() and now.
                        try:
                            schedule = stripe.SubscriptionSchedule.create(
                                from_subscription=active_sub.stripe_subscription_id
                            )
                        except stripe.error.InvalidRequestError as exc:
                            if "already attached to a schedule" in str(exc):
                                # Re-fetch to get the schedule ID the concurrent
                                # request just created and update it instead.
                                stripe_sub = stripe.Subscription.retrieve(
                                    active_sub.stripe_subscription_id
                                )
                                existing_schedule_id = stripe_sub.get("schedule")
                                if not existing_schedule_id:
                                    raise
                                schedule = stripe.SubscriptionSchedule.retrieve(
                                    existing_schedule_id
                                )
                            else:
                                raise

                        stripe.SubscriptionSchedule.modify(
                            schedule["id"],
                            end_behavior="release",
                            phases=[
                                {
                                    "items": [{"price": current_stripe_price_id, "quantity": 1}],
                                    "start_date": schedule["phases"][0]["start_date"],
                                    "end_date": current_period_end,
                                },
                                {
                                    "items": [{"price": new_stripe_price_id, "quantity": 1}],
                                },
                            ],
                        )

                    # Store pending plan locally; current plan stays unchanged
                    active_sub.pending_plan = new_plan
                    active_sub.save(update_fields=["pending_plan"])

                    return Response(
                        {
                            "message": f"Downgrade to the {new_plan.name} plan has been scheduled. "
                                       "It will take effect at the end of your current billing cycle."
                        },
                        status=status.HTTP_200_OK,
                    )

        # ── No existing subscription → start a new Checkout session ────────
        # Reuse a recent abandoned attempt for the same plan instead of piling up rows.
        pending_sub = (
            Subscription.objects.filter(
                organization=organization, plan=new_plan, status="incomplete",
                stripe_subscription_id__isnull=True,
                created_at__gte=timezone.now() - timezone.timedelta(hours=24),
            ).order_by("-created_at").first()
            or Subscription.objects.create(organization=organization, plan=new_plan, status="incomplete")
        )

        session = stripe.checkout.Session.create(
            idempotency_key=f"checkout-{pending_sub.id}-{int(timezone.now().timestamp() // 600)}",
            ui_mode="embedded",
            customer_email=request.user.email,
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": f"{new_plan.name} Plan"},
                        "unit_amount": int(new_plan.price * 100),
                        "recurring": {"interval": new_plan.interval},
                    },
                    "quantity": 1,
                }
            ],
            mode="subscription",
            return_url=(
                settings.FRONTEND_URL
                + "/payment/success?session_id={CHECKOUT_SESSION_ID}"
            ),
            metadata={
                "plan_id": str(new_plan.id),
                "organization_id": str(organization_snowflake_id),
                "subscription_id": str(pending_sub.id),
            },
        )

        return Response(
            {
                "checkout_session_id": session.id,
                "client_secret": session.client_secret,
            },
            status=status.HTTP_200_OK,
        )

    # ── Private helpers ────────────────────────────────────────────────────

    @staticmethod
    def _get_or_create_stripe_price(plan: Plan) -> str:
        """
        Return the Stripe price ID stored on the plan, or create a one-off
        price object if the plan doesn't have one yet.
        """
        if plan.stripe_price_id:
            return plan.stripe_price_id

        # Create a recurring price on the fly (idempotent per product+amount)
        price = stripe.Price.create(
            currency="usd",
            unit_amount=int(plan.price * 100),
            recurring={"interval": plan.interval},
            product_data={"name": f"{plan.name} Plan"},
        )
        plan.stripe_price_id = price.id
        plan.save(update_fields=["stripe_price_id"])
        return price.id


class CancelPlanAPIView(RequiredOrganizationIDMixin, GenericAPIView):
    """
    Cancel the organisation's active subscription.

    The subscription is **not** cancelled immediately. It will remain active
    until the end of the current billing period and will **not** renew
    afterwards (``cancel_at_period_end = True`` on Stripe).
    """

    permission_classes = [IsRegularPlatformUser, IsAdminOrOwnerOfOrganization]

    @extend_schema(parameters=[_ORG_ID_PARAM])
    def post(self, request, *args, **kwargs):
        organization_snowflake_id = self.get_org_id()
        organization = Organization.objects.get(snowflake_id=organization_snowflake_id)

        active_sub = (
            Subscription.objects.filter(organization=organization, status="active")
            .select_related("plan")
            .first()
        )

        if not active_sub:
            return Response(
                {"error": "No active subscription found for this organisation."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if active_sub.cancel_at_period_end:
            return Response(
                {
                    "message": "Your subscription is already scheduled to cancel at the "
                               f"end of the current billing period ({active_sub.current_period_end})."
                },
                status=status.HTTP_200_OK,
            )

        if not active_sub.stripe_subscription_id:
            return Response(
                {"error": "Active subscription has no Stripe ID. Cannot cancel."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Retrieve the Stripe subscription to check for an attached schedule.
        # When a SubscriptionSchedule manages the subscription, Stripe forbids
        # setting cancel_at_period_end directly — we must update the schedule instead.
        stripe_sub = stripe.Subscription.retrieve(active_sub.stripe_subscription_id)
        existing_schedule_id = stripe_sub.get("schedule")

        if existing_schedule_id:
            # The subscription is governed by a schedule.
            # Update the schedule so it ends (cancels) after the current phase
            # rather than rolling into the next phase.
            schedule = stripe.SubscriptionSchedule.retrieve(existing_schedule_id)
            current_phase = schedule["phases"][0]
            current_stripe_price_id = stripe_sub["items"]["data"][0]["price"]["id"]

            # Collapse to a single phase (the current one) and set end_behavior
            # to "cancel" so Stripe cancels the subscription when that phase ends.
            stripe.SubscriptionSchedule.modify(
                existing_schedule_id,
                end_behavior="cancel",
                phases=[
                    {
                        "items": [{"price": current_stripe_price_id, "quantity": 1}],
                        "start_date": current_phase["start_date"],
                        "end_date": current_phase["end_date"],
                    }
                ],
            )
        else:
            # No schedule — safe to modify the subscription directly.
            stripe.Subscription.modify(
                active_sub.stripe_subscription_id,
                cancel_at_period_end=True,
            )

        # Mirror the flag locally so the UI can reflect it right away
        active_sub.cancel_at_period_end = True
        active_sub.save(update_fields=["cancel_at_period_end"])

        return Response(
            {
                "message": (
                    f"Your {active_sub.plan.name} subscription has been scheduled for "
                    f"cancellation. It will remain active until "
                    f"{active_sub.current_period_end} and will not renew."
                )
            },
            status=status.HTTP_200_OK,
        )


class GetPlanAPIView(RequiredOrganizationIDMixin, GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    @extend_schema(parameters=[_ORG_ID_PARAM])
    def get(self, request, *args, **kwargs):
        organization_snowflake_id = self.get_org_id()
        organization = Organization.objects.get(snowflake_id=organization_snowflake_id)
        subscription = Subscription.objects.filter(
            organization=organization, status="active"
        ).select_related("plan")

        if not subscription.exists():
            return Response(
                {"error": "No active subscription found for this organization."},
                status=status.HTTP_404_NOT_FOUND,
            )
        subscription = subscription.select_related("pending_plan").first()

        plan_name = subscription.plan.name
        limit = subscription.plan.get_campaign_limit()
        campaign_limit = "Unlimited" if limit is None else limit
        campaign_used = (
            subscription.usage_records.filter(feature_key="campaign_limit").aggregate(
                total_used=Sum("used")
            )["total_used"]
            or 0
        )

        # Build the info message for pending state changes
        info = None
        period_end = subscription.current_period_end
        period_end_str = (
            period_end.strftime("%B %d, %Y") if period_end else "the end of your billing cycle"
        )

        if subscription.cancel_at_period_end:
            info = (
                f"Your {plan_name} subscription is scheduled to cancel on "
                f"{period_end_str}. It will not renew after that date."
            )
        elif subscription.pending_plan:
            info = (
                f"You have a pending downgrade to the {subscription.pending_plan.name} plan. "
                f"It will take effect on {period_end_str} at the start of your next billing cycle."
            )

        return Response(
            {
                "plan_name": plan_name,
                "campaign_limit": campaign_limit,
                "campaign_used": campaign_used,
                "cancel_at_period_end": subscription.cancel_at_period_end,
                "current_period_end": subscription.current_period_end,
                "info": info,
            }
        )


class BillingHistoryAPIView(RequiredOrganizationIDMixin, GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsAdminOrOwnerOfOrganization]

    def get(self, request, *args, **kwargs):
        organization_snowflake_id = self.get_org_id()
        organization = Organization.objects.get(snowflake_id=organization_snowflake_id)

        billing_history = (
            Payment.objects.filter(organization=organization)
            .select_related("subscription__plan")
            .order_by("-paid_at", "-created_at")
        )

        serializer = serializers.BillingHistorySerializer(billing_history, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


def _stripe_invoice_pdf_url(payment):
    """Resolve the Stripe-hosted PDF for a payment, or None if it has no invoice."""
    if not payment.stripe_invoice_id:
        return None
    try:
        invoice = stripe.Invoice.retrieve(payment.stripe_invoice_id)
    except stripe.StripeError:
        return None
    return invoice.get("invoice_pdf") or invoice.get("hosted_invoice_url")


class InvoiceDownloadAPIView(RequiredOrganizationIDMixin, GenericAPIView):
    """GET /finance/invoices/<payment_id>/download/ — URL of a single invoice PDF."""
    permission_classes = [IsRegularPlatformUser, IsAdminOrOwnerOfOrganization]

    def get(self, request, payment_id, *args, **kwargs):
        organization = Organization.objects.get(snowflake_id=self.get_org_id())
        payment = Payment.objects.filter(id=payment_id, organization=organization).first()
        if not payment:
            return Response({"error": "Invoice not found."}, status=status.HTTP_404_NOT_FOUND)
        url = _stripe_invoice_pdf_url(payment)
        if not url:
            return Response(
                {"error": "No invoice is available for this payment yet."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"url": url})


class InvoiceDownloadAllAPIView(RequiredOrganizationIDMixin, GenericAPIView):
    """GET /finance/invoices/download-all/ — ZIP with every available invoice PDF."""
    permission_classes = [IsRegularPlatformUser, IsAdminOrOwnerOfOrganization]

    def get(self, request, *args, **kwargs):
        import io
        import zipfile

        import requests
        from django.http import HttpResponse

        organization = Organization.objects.get(snowflake_id=self.get_org_id())
        payments = Payment.objects.filter(
            organization=organization, stripe_invoice_id__isnull=False
        ).order_by("-paid_at", "-created_at")

        buffer = io.BytesIO()
        added = 0
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for payment in payments:
                url = _stripe_invoice_pdf_url(payment)
                if not url:
                    continue
                try:
                    pdf = requests.get(url, timeout=15)
                    pdf.raise_for_status()
                except requests.RequestException:
                    continue
                stamp = (payment.paid_at or payment.created_at).strftime("%Y%m%d")
                archive.writestr(f"invoice_{stamp}_{payment.id}.pdf", pdf.content)
                added += 1

        if not added:
            return Response(
                {"error": "There are no invoices available to download yet."},
                status=status.HTTP_404_NOT_FOUND,
            )

        response = HttpResponse(buffer.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="invoices.zip"'
        return response
