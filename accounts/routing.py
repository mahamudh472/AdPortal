from django.urls import re_path
from .consumers import NotificationConsumer

websocket_urlpatterns = [
	re_path('ws/notifications/$', NotificationConsumer.as_asgi())
]