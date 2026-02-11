
from urllib.parse import parse_qs
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError
from django.contrib.auth.models import AnonymousUser


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):

        print("\n--- MIDDLEWARE HIT ---")

        query_string = scope.get("query_string", b"")
        print("RAW BYTES:", query_string)

        try:
            decoded = query_string.decode()
        except Exception as e:
            print("DECODE ERROR:", e)
            decoded = ""

        print("DECODED:", decoded)

        params = parse_qs(decoded)
        print("PARAMS:", params)

        token = params.get("token")

        if not token:
            print("NO TOKEN FOUND")
            scope["user"] = AnonymousUser()
        else:
            token = token[0]
            print("TOKEN:", token[:30], "...")
            user = await self.get_user(token)
            scope["user"] = user if user is not None else AnonymousUser()

        print("FINAL USER:", scope["user"])
        print("--- END MIDDLEWARE ---\n")

        return await super().__call__(scope, receive, send)

    @database_sync_to_async
    def get_user(self, token):

        User = get_user_model()
        try:
            access = AccessToken(token)
            user_id = access["user_id"]
            return User.objects.get(id=user_id)

        except TokenError as e:
            print("TOKEN ERROR:", e)
            return None

        except Exception as e:
            print("OTHER ERROR:", e)
            return None

