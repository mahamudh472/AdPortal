"""Encrypted-at-rest model fields (audit SEC-12).

Values are stored as ``enc1:<fernet-token>``. Rows written before encryption was introduced
(plain text) are still readable and are encrypted the next time they are saved, or in bulk
with ``python manage.py encrypt_tokens``.

Keys: ``FIELD_ENCRYPTION_KEYS`` (comma separated Fernet keys; first encrypts, all decrypt,
enabling rotation). If unset, a key is derived from ``SECRET_KEY`` — set a dedicated key in
production so rotating SECRET_KEY doesn't make stored tokens unreadable.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.db import models

PREFIX = 'enc1:'
_cache = {}


def _fernet():
    configured = tuple(getattr(settings, 'FIELD_ENCRYPTION_KEYS', ()) or ())
    key = (configured, settings.SECRET_KEY if not configured else None)
    f = _cache.get(key)
    if f is None:
        if configured:
            keys = [Fernet(k.encode() if isinstance(k, str) else k) for k in configured]
        else:
            derived = base64.urlsafe_b64encode(hashlib.sha256(('adportal-field-key:' + settings.SECRET_KEY).encode()).digest())
            keys = [Fernet(derived)]
        f = _cache[key] = MultiFernet(keys)
    return f


def encrypt_value(value: str) -> str:
    if value is None or value == '' or str(value).startswith(PREFIX):
        return value
    return PREFIX + _fernet().encrypt(str(value).encode()).decode()


def decrypt_value(value):
    if value is None or not isinstance(value, str) or not value.startswith(PREFIX):
        return value  # legacy plaintext
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        # Wrong/rotated-out key: don't crash every request, surface as an unusable token.
        return ''


class EncryptedTextField(models.TextField):
    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return encrypt_value(value)

    def from_db_value(self, value, expression, connection):
        return decrypt_value(value)


def token_hash(token: str) -> str:
    """Deterministic blind index so integrations can still be looked up by token."""
    return hashlib.sha256((token or '').encode()).hexdigest()
