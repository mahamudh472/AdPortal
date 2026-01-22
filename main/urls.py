from django.urls import path
from . import views
from .integration_handler import AdProfileListView, SelectAdProfileView

urlpatterns = [
	path('campaigns/', views.CampaignListAPIView.as_view()),
	path('create-ad/', views.CreateAdAPIView.as_view()),
	path('get-ad-profiles/', AdProfileListView.as_view()),
	path('select-ad-profile/', SelectAdProfileView.as_view()),
	path('generate-ai-copy/', views.AICopyGeneratorAPIView.as_view()),
]