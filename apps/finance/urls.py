from django.urls import path
from . import views
from apps.finance.webhook import StripeWebhookView

urlpatterns = [
	path('get-plans/', views.PlanListAPIView.as_view()),
	path('buy-plan/', views.BuyPlanAPIView.as_view()),
	path('cancel-plan/', views.CancelPlanAPIView.as_view()),
	path('get-current-plan/', views.GetPlanAPIView.as_view()),
	path('billing-history/', views.BillingHistoryAPIView.as_view()),
	path('invoices/download-all/', views.InvoiceDownloadAllAPIView.as_view()),
	path('invoices/<int:payment_id>/download/', views.InvoiceDownloadAPIView.as_view()),
	path('stripe/webhook/', StripeWebhookView.as_view()),
]