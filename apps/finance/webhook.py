import logging
from datetime import datetime, timezone as dt_timezone
from django.db import IntegrityError, transaction
from django.utils import timezone
import stripe

from django.views import View
from django.http import HttpResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from apps.finance.models import Payment, Plan, StripeEvent, Subscription
from apps.main.models import Organization

stripe.api_key = settings.STRIPE_SECRET_KEY
endpoint_secret = settings.HTTP_STRIPE_SIGNATURE
logger = logging.getLogger(__name__)
_SignatureError = getattr(stripe, 'SignatureVerificationError', None) or stripe.error.SignatureVerificationError


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(View):
    def post(self, request):
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
        except ValueError:
            return HttpResponse(status=400)  # Invalid payload
        except _SignatureError:
            return HttpResponse(status=400)  # Invalid signature

        event_type = event["type"]
        handlers = {
            "checkout.session.completed": self._handle_checkout_completed,
            "invoice.payment_failed": self._handle_payment_failed,
            "invoice.paid": self._handle_invoice_paid,
            "customer.subscription.updated": self._handle_subscription_updated,
            "customer.subscription.deleted": self._handle_subscription_deleted,
        }
        handler = handlers.get(event_type)
        if handler is None:
            logger.info("Ignoring unhandled Stripe event type %s", event_type)
            return HttpResponse(status=200)

        try:
            # Record the event and run the handler atomically: a repeated delivery hits
            # the unique constraint (ignored); a handler crash rolls the marker back so
            # Stripe retries.
            with transaction.atomic():
                StripeEvent.objects.create(event_id=event["id"], event_type=event_type)
                handler(event["data"]["object"])
        except IntegrityError:
            logger.info("Duplicate Stripe event %s ignored", event["id"])
        except Exception:
            logger.exception("Stripe webhook handler failed for %s (%s)", event["id"], event_type)
            return HttpResponse(status=500)

        return HttpResponse(status=200)

    # ── Event handlers ─────────────────────────────────────────────────────

    @staticmethod
    def _handle_checkout_completed(session):
        """First-time purchase: activate the local subscription record."""
        metadata = session.get("metadata") or {}
        plan_id = metadata.get("plan_id")
        organization_id = metadata.get("organization_id")
        subscription_id = metadata.get("subscription_id")
        if not (plan_id and organization_id and subscription_id):
            logger.warning("checkout.session.completed without AdPortal metadata; ignoring")
            return

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
    def _handle_invoice_paid(invoice):
        """Record renewal payments and move the billing period forward."""
        stripe_subscription_id = invoice.get("subscription")
        invoice_id = invoice.get("id")
        if not stripe_subscription_id or not invoice_id:
            return
        subscription = (
            Subscription.objects.filter(stripe_subscription_id=stripe_subscription_id)
            .select_related("organization", "plan")
            .first()
        )
        if not subscription:
            return  # first invoice arrives before checkout.session.completed links it
        if Payment.objects.filter(stripe_invoice_id=invoice_id, status="paid").exists():
            return
        Payment.objects.create(
            organization=subscription.organization,
            subscription=subscription,
            amount=(invoice.get("amount_paid") or 0) / 100,
            status="paid",
            paid_at=timezone.now(),
            stripe_invoice_id=invoice_id,
            raw_payload=invoice,
        )
        lines = (invoice.get("lines") or {}).get("data") or []
        period = (lines[0].get("period") if lines else None) or {}
        if period.get("end"):
            subscription.current_period_end = datetime.fromtimestamp(period["end"], tz=dt_timezone.utc)
        if period.get("start"):
            subscription.current_period_start = datetime.fromtimestamp(period["start"], tz=dt_timezone.utc)
        if subscription.status in ("past_due", "incomplete"):
            subscription.status = "active"
        subscription.save()

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
            subscription.current_period_start = datetime.fromtimestamp(
                period_start, tz=dt_timezone.utc
            )
        if period_end:
            subscription.current_period_end = datetime.fromtimestamp(
                period_end, tz=dt_timezone.utc
            )

        # ── Detect plan change (downgrade schedule applied at cycle end) ───
        # With SubscriptionSchedule, the price on the Stripe subscription only
        # changes when a scheduled phase transitions (i.e. at period end).
        # At that moment Stripe releases the schedule (schedule field → null).
        # If a schedule is still attached, the update is just bookkeeping from
        # creating/modifying the schedule — the current plan has not changed yet.
        schedule_still_active = bool(stripe_sub.get("schedule"))

        items = (stripe_sub.get("items") or {}).get("data") or [{}]
        stripe_price_id = (items[0].get("price") or {}).get("id")
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
