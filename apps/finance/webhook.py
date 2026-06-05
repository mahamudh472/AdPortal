from django.utils import timezone
import stripe

from django.views import View
from django.http import HttpResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from apps.finance.models import Payment, Plan, Subscription
from apps.main.models import Organization

stripe.api_key = settings.STRIPE_SECRET_KEY
endpoint_secret = settings.HTTP_STRIPE_SIGNATURE


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(View):
    def post(self, request):
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
        except ValueError:
            return HttpResponse(status=400)  # Invalid payload
        except stripe.error.SignatureVerificationError:
            return HttpResponse(status=400)  # Invalid signature

        event_type = event["type"]

        if event_type == "checkout.session.completed":
            self._handle_checkout_completed(event["data"]["object"])

        elif event_type == "invoice.payment_failed":
            self._handle_payment_failed(event["data"]["object"])

        elif event_type == "customer.subscription.updated":
            self._handle_subscription_updated(event["data"]["object"])

        elif event_type == "customer.subscription.deleted":
            self._handle_subscription_deleted(event["data"]["object"])

        return HttpResponse(status=200)

    # ── Event handlers ─────────────────────────────────────────────────────

    @staticmethod
    def _handle_checkout_completed(session):
        """First-time purchase: activate the local subscription record."""
        plan_id = session["metadata"]["plan_id"]
        organization_id = session["metadata"]["organization_id"]
        subscription_id = session["metadata"]["subscription_id"]

        organization = Organization.objects.filter(
            snowflake_id=organization_id
        ).first()

        try:
            subscription = Subscription.objects.get(
                id=subscription_id,
                organization__snowflake_id=organization_id,
                plan__id=plan_id,
                status="incomplete",
            )
            subscription.status = "active"
            subscription.stripe_subscription_id = session.get("subscription")
            subscription.current_period_start = timezone.now()
            subscription.current_period_end = timezone.now() + timezone.timedelta(
                days=30
            )
            subscription.save()


            payment = Payment.objects.create(
                organization=organization,
                subscription=subscription,
                amount=subscription.plan.price,
                status="paid",
                paid_at=timezone.now(),
                stripe_payment_intent_id=session.get("payment_intent"),
                stripe_invoice_id=session.get("invoice"),
                raw_payload=session,
            )

            from apps.accounts.notifications import notify_org_members

            notify_org_members(
                organization,
                f"Your subscription to the {subscription.plan.name} plan has been "
                "activated successfully.",
            )

        except Subscription.DoesNotExist:
            pass

    @staticmethod
    def _handle_payment_failed(invoice):
        """Record a failed payment and notify the organisation."""
        stripe_subscription_id = invoice.get("subscription")
        if not stripe_subscription_id:
            return

        subscription = (
            Subscription.objects.filter(
                stripe_subscription_id=stripe_subscription_id
            )
            .select_related("organization", "plan")
            .first()
        )
        if not subscription:
            return

        organization = subscription.organization
        amount_due = invoice.get("amount_due", 0) / 100  # cents → dollars

        Payment.objects.create(
            organization=organization,
            subscription=subscription,
            amount=amount_due,
            status="failed",
            stripe_invoice_id=invoice.get("id"),
            raw_payload=invoice,
        )

        from apps.accounts.notifications import notify_org_members, notify_admins

        notify_org_members(
            organization,
            f"A payment of ${amount_due:.2f} failed for your "
            f"{subscription.plan.name} subscription. "
            "Please update your payment method to avoid service interruption.",
            setting_key="budget_alerts",
        )
        notify_admins(
            f'Payment failed for organization "{organization.name}" '
            f"(plan: {subscription.plan.name}, amount: ${amount_due:.2f}).",
            setting_key="failed_payment",
        )

    @staticmethod
    def _handle_subscription_updated(stripe_sub):
        """
        Sync local subscription after Stripe applies a plan change.

        This is the primary hook for **scheduled downgrades**: Stripe fires
        this event at the start of the new billing period once it has swapped
        the price item.  We detect that the Stripe price has changed and
        update the local plan accordingly.

        Also syncs ``cancel_at_period_end`` and billing period timestamps.
        """
        stripe_sub_id = stripe_sub["id"]

        subscription = (
            Subscription.objects.filter(stripe_subscription_id=stripe_sub_id)
            .select_related("plan", "organization")
            .first()
        )
        if not subscription:
            return

        # ── Sync cancel_at_period_end ──────────────────────────────────────
        subscription.cancel_at_period_end = stripe_sub.get(
            "cancel_at_period_end", False
        )

        # ── Sync billing period timestamps ─────────────────────────────────
        period_start = stripe_sub.get("current_period_start")
        period_end = stripe_sub.get("current_period_end")
        if period_start:
            subscription.current_period_start = timezone.datetime.fromtimestamp(
                period_start, tz=timezone.utc
            )
        if period_end:
            subscription.current_period_end = timezone.datetime.fromtimestamp(
                period_end, tz=timezone.utc
            )

        # ── Detect plan change (downgrade schedule applied at cycle end) ───
        # With SubscriptionSchedule, the price on the Stripe subscription only
        # changes when a scheduled phase transitions (i.e. at period end).
        # At that moment Stripe releases the schedule (schedule field → null).
        # If a schedule is still attached, the update is just bookkeeping from
        # creating/modifying the schedule — the current plan has not changed yet.
        schedule_still_active = bool(stripe_sub.get("schedule"))

        stripe_price_id = (
            stripe_sub.get("items", {}).get("data", [{}])[0]
            .get("price", {})
            .get("id")
        )
        if (
            stripe_price_id
            and stripe_price_id != subscription.plan.stripe_price_id
            and not schedule_still_active  # only act once the schedule is released
        ):
            new_plan = Plan.objects.filter(stripe_price_id=stripe_price_id).first()
            if new_plan:
                old_plan_name = subscription.plan.name
                subscription.plan = new_plan
                subscription.pending_plan = None  # downgrade has been applied

                from apps.accounts.notifications import notify_org_members

                notify_org_members(
                    subscription.organization,
                    f"Your subscription has been updated to the {new_plan.name} plan.",
                )

        subscription.save()

    @staticmethod
    def _handle_subscription_deleted(stripe_sub):
        """
        Mark the local subscription as canceled when Stripe confirms deletion.

        This fires when the subscription period ends and ``cancel_at_period_end``
        was ``True``, or when an immediate cancellation is performed.
        """
        stripe_sub_id = stripe_sub["id"]

        subscription = Subscription.objects.filter(
            stripe_subscription_id=stripe_sub_id
        ).select_related("organization", "plan").first()

        if not subscription:
            return

        subscription.status = "canceled"
        subscription.save(update_fields=["status"])

        from apps.accounts.notifications import notify_org_members

        notify_org_members(
            subscription.organization,
            f"Your {subscription.plan.name} subscription has ended. "
            "You can resubscribe at any time.",
        )
