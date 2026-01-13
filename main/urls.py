from django.urls import path
from . import views
from .integration_handler import AdProfileListView, SelectAdProfileView

urlpatterns = [
	path('create-ad/', views.CreateAdAPIView.as_view()),
	path('get-ad-profiles/', AdProfileListView.as_view()),
	path('select-ad-profile/', SelectAdProfileView.as_view())
]