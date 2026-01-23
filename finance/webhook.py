
import stripe
from django.views import View
from django.http import HttpResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .models import Enrollment, Course
from django.contrib.auth import get_user_model

User = get_user_model()

stripe.api_key = settings.STRIPE_SECRET_KEY
endpoint_secret = settings.STRIPE_WEBHOOK_SECRET  # Get from Stripe Dashboard

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
            user_id = session.get("metadata", {}).get("user_id")
            course_id = session.get("metadata", {}).get("course_id")

            if user_id and course_id:
                user = User.objects.get(id=user_id)
                course = Course.objects.get(id=course_id)

                # Avoid duplicate enrollment
                if not Enrollment.objects.filter(student=user, course=course).exists():
                    Enrollment.objects.create(student=user, course=course)

        return HttpResponse(status=200)
