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
from apps.accounts.routing import websocket_urlpatterns
from apps.accounts.middleware import JWTAuthMiddleware
from channels.security.websocket import OriginValidator
from django.conf import settings

# Cross-site WebSocket hijacking protection: only allow our own frontend origins
# (same allow-list as CORS). Everything is allowed only in DEBUG / explicit allow-all.
_ws_allowed_origins = ['*'] if settings.CORS_ALLOW_ALL_ORIGINS else list(settings.CORS_ALLOWED_ORIGINS)

application = ProtocolTypeRouter({
	'http': get_asgi_application(),
	'websocket': OriginValidator(
		JWTAuthMiddleware(
			URLRouter(
				websocket_urlpatterns
			)
		),
		_ws_allowed_origins,
	)
})
