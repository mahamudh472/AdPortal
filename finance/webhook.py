from django.utils import timezone
import stripe

from django.views import View
from django.http import HttpResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from finance.models import Payment, Subscription
from main.models import Organization

stripe.api_key = settings.STRIPE_SECRET_KEY
endpoint_secret = settings.HTTP_STRIPE_SIGNATURE


@method_decorator(csrf_exempt, name='dispatch')
class StripeWebhookView(View):
    def post(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
        event = None

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, endpoint_secret
            )
        except ValueError:
            return HttpResponse(status=400)  # Invalid payload
        except stripe.error.SignatureVerificationError:
            return HttpResponse(status=400)  # Invalid signature

        # Handle the event type
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']

            plan_id = session['metadata']['plan_id']
            organization_id = session['metadata']['organization_id']
            subscription_id = session['metadata']['subscription_id']

            organization = Organization.objects.filter(snowflake_id=organization_id).first()
            print(f"Received checkout.session.completed for organization {organization_id} and plan {plan_id}")

            try:
                subscription = Subscription.objects.get(id=subscription_id, organization__snowflake_id=organization_id, plan__id=plan_id, status='incomplete')
                subscription.status = 'active'
                subscription.current_period_start = timezone.now()
                subscription.current_period_end = timezone.now() + timezone.timedelta(days=30)
                subscription.save()

                print(f"Updated subscription {subscription.id} to active for organization {organization_id}")

                print(f"all data for payment: organization_id={organization_id}, subscription_id={subscription.id}, amount={subscription.plan.price}, stripe_payment_intent_id={session.get('payment_intent')}, stripe_invoice_id={session.get('invoice')}")
                payment = Payment.objects.create(
                    organization=organization,
                    subscription=subscription,
                    amount=subscription.plan.price,
                    status='paid',
                    paid_at=timezone.now(),
                    stripe_payment_intent_id=session.get('payment_intent'),
                    stripe_invoice_id=session.get('invoice'),
                    raw_payload=session
                )
                print(f"Created payment {payment.id} for subscription {subscription.id} and organization {organization_id}")

                # Notify org owner/admins that the subscription is now active
                from accounts.notifications import notify_org_members
                notify_org_members(
                    organization,
                    f"Your subscription to the {subscription.plan.name} plan has been activated successfully.",
                )

            except Subscription.DoesNotExist:
                print(f"No incomplete subscription found for organization {organization_id} and plan {plan_id}")
                pass
            except Payment.DoesNotExist:
                print(f"Failed to create payment for organization {organization_id} and subscription {subscription.id}")
                pass

        elif event['type'] == 'invoice.payment_failed':
            invoice = event['data']['object']
            stripe_subscription_id = invoice.get('subscription')

            if stripe_subscription_id:
                subscription = Subscription.objects.filter(
                    stripe_subscription_id=stripe_subscription_id
                ).select_related('organization', 'plan').first()

                if subscription:
                    organization = subscription.organization
                    amount_due = invoice.get('amount_due', 0) / 100  # cents → dollars

                    Payment.objects.create(
                        organization=organization,
                        subscription=subscription,
                        amount=amount_due,
                        status='failed',
                        stripe_invoice_id=invoice.get('id'),
                        raw_payload=invoice,
                    )

                    # Notify org owner/admins to update their payment method
                    from accounts.notifications import notify_org_members, notify_admins
                    notify_org_members(
                        organization,
                        f"A payment of ${amount_due:.2f} failed for your {subscription.plan.name} subscription. "
                        "Please update your payment method to avoid service interruption.",
                        setting_key='budget_alerts',
                    )
                    # Notify platform admins
                    notify_admins(
                        f"Payment failed for organization \"{organization.name}\" "
                        f"(plan: {subscription.plan.name}, amount: ${amount_due:.2f}).",
                        setting_key='failed_payment',
                    )

        return HttpResponse(status=200)
