from django.utils import timezone
import stripe

from django.views import View
from django.http import HttpResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from finance.models import Payment, Subscription

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

            try:
                subscription = Subscription.objects.get(
                    organization_id=organization_id,
                    plan_id=plan_id,
                    status='incomplete'
                )
                subscription.status = 'active'
                subscription.current_period_start = timezone.now()
                subscription.current_period_end = timezone.now() + timezone.timedelta(days=30)
                subscription.save()

                payment = Payment.objects.create(
                    organization_id=organization_id,
                    subscription=subscription,
                    amount=subscription.plan.price,
                    status='paid',
                    paid_at=timezone.now(),
                    stripe_payment_intent_id=session.get('payment_intent'),
                    stripe_invoice_id=session.get('invoice'),
                    raw_payload=session
                )
            except Subscription.DoesNotExist:
                pass
            except Payment.DoesNotExist:
                pass

        return HttpResponse(status=200)