from django.urls import path
from . import views
urlpatterns = [
	path('create-ad/', views.CreateAdAPIView.as_view())
]