
from urllib.parse import parse_qs
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError
from django.contrib.auth.models import AnonymousUser
from django.conf import settings


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):

        query_string = scope.get("query_string", b"")

        try:
            decoded = query_string.decode()
        except Exception as e:
            decoded = ""

        params = parse_qs(decoded)

        ticket = params.get("ticket")
        token = params.get("token")

        user = None
        if ticket:
            # Preferred: single-use, 30 s ticket obtained from POST /accounts/ws-ticket/
            user = await self.get_user_from_ticket(ticket[0])
        elif token and settings.WS_ALLOW_QUERY_TOKEN:
            # Legacy: JWT in the URL ends up in access logs / history. Disabled by default
            # outside DEBUG (set WS_ALLOW_QUERY_TOKEN=True temporarily during a rollout).
            user = await self.get_user(token[0])
        scope["user"] = user if user is not None else AnonymousUser()

        return await super().__call__(scope, receive, send)

    @database_sync_to_async
    def get_user_from_ticket(self, ticket):
        from django.core.cache import cache
        key = f"wsticket:{ticket}"
        user_id = cache.get(key)
        if not user_id:
            return None
        cache.delete(key)  # single use
        User = get_user_model()
        user = User.objects.filter(id=user_id, is_active=True).first()
        return user

    @database_sync_to_async
    def get_user(self, token):

        User = get_user_model()
        try:
            access = AccessToken(token)
            user_id = access["user_id"]
            user = User.objects.get(id=user_id)
            return user if user.is_active else None

        except TokenError as e:
            return None

        except Exception as e:
            return None

