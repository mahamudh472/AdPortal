from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from unittest import skipIf
from django.conf import settings
from django.core.cache import cache
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User


class WebSocketAuthTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="ws@example.com", password="StrongPass123!", is_active=True)

    def _ticket(self):
        client = APIClient()
        client.force_authenticate(self.user)
        res = client.post("/api/v1/accounts/ws-ticket/")
        self.assertEqual(res.status_code, 200)
        return res.data["ticket"]

    def _app(self):
        from AdPortal.asgi import application
        return application

    async def _connect(self, query, origin=b"http://localhost:5173"):
        comm = WebsocketCommunicator(self._app(), f"/ws/notifications/?{query}", headers=[(b"origin", origin)])
        connected, _ = await comm.connect()
        await comm.disconnect()
        return connected

    async def test_ticket_is_single_use(self):
        ticket = await database_sync_to_async(self._ticket)()
        self.assertTrue(await self._connect(f"ticket={ticket}"))
        self.assertFalse(await self._connect(f"ticket={ticket}"))

    @override_settings(WS_ALLOW_QUERY_TOKEN=False)
    async def test_query_token_rejected_when_disabled(self):
        from rest_framework_simplejwt.tokens import AccessToken
        token = str(await database_sync_to_async(AccessToken.for_user)(self.user))
        self.assertFalse(await self._connect(f"token={token}"))

    @skipIf(settings.CORS_ALLOW_ALL_ORIGINS, "origin allow-list is open in DEBUG / allow-all mode")
    async def test_foreign_origin_rejected(self):
        ticket = await database_sync_to_async(self._ticket)()
        self.assertFalse(await self._connect(f"ticket={ticket}", origin=b"https://evil.example"))
