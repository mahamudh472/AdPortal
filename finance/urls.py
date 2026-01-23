from django.urls import path
from . import views
from finance.webhook import StripeWebhookView

urlpatterns = [
	path('get-plans/', views.PlanListAPIView.as_view()),
	path('buy-plan/', views.BuyPlanAPIView.as_view()),
	path('get-current-plan/', views.GetPlanAPIView.as_view()),
	path('billing-history/', views.BillingHistoryAPIView.as_view()),
	path('stripe/webhook/', StripeWebhookView.as_view()),
]