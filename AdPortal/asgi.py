"""
ASGI config for AdPortal project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AdPortal.settings')
django.setup()

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from accounts.routing import websocket_urlpatterns
from accounts.middleware import JWTAuthMiddleware

application = ProtocolTypeRouter({
	'http': get_asgi_application(),
	'websocket': JWTAuthMiddleware(
		URLRouter(
			websocket_urlpatterns
		)
	)
})
