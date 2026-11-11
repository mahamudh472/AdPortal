"""Secure OTP helpers (audit SEC-06).

- cryptographically secure code generation
- previous unused codes are invalidated when a new one is issued
- failed-attempt lockout per email (cache based, no schema change)
- constant-time comparison; one OTP can't be replayed
"""
import secrets
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from .models import OTP

OTP_TTL_MINUTES = 10
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def issue_otp(user) -> str:
    """Invalidate older codes and create a fresh one. Returns the plain code."""
    OTP.objects.filter(user=user, is_used=False).update(is_used=True)
    code = generate_code()
    OTP.objects.create(
        user=user,
        code=code,
        expires_at=timezone.now() + timedelta(minutes=OTP_TTL_MINUTES),
    )
    cache.delete(_key(user.email))
    return code


def _key(email: str) -> str:
    return f"otp_fail:{(email or '').strip().lower()}"


def is_locked(email: str) -> bool:
    return (cache.get(_key(email)) or 0) >= MAX_FAILED_ATTEMPTS


def _register_failure(email: str) -> None:
    key = _key(email)
    try:
        cache.add(key, 0, LOCKOUT_SECONDS)
        cache.incr(key)
    except ValueError:  # key expired between add and incr
        cache.set(key, 1, LOCKOUT_SECONDS)


def consume_otp(user, submitted: str):
    """Validate `submitted` against the user's latest valid OTP.

    Returns (ok, error_message). On success the OTP is marked used.
    """
    if is_locked(user.email):
        return False, "Too many failed attempts. Please request a new code later."
    otp = (
        OTP.objects.filter(user=user, is_used=False, expires_at__gt=timezone.now())
        .order_by("-created_at")
        .first()
    )
    if otp is None or not secrets.compare_digest(otp.code, str(submitted or "")):
        _register_failure(user.email)
        return False, "Invalid or expired OTP"
    otp.is_used = True
    otp.save(update_fields=["is_used"])
    cache.delete(_key(user.email))
    return True, None


def check_otp(user, submitted: str):
    """Like consume_otp but does NOT mark the code as used (pre-check step)."""
    if is_locked(user.email):
        return False, "Too many failed attempts. Please request a new code later."
    otp = (
        OTP.objects.filter(user=user, is_used=False, expires_at__gt=timezone.now())
        .order_by("-created_at")
        .first()
    )
    if otp is None or not secrets.compare_digest(otp.code, str(submitted or "")):
        _register_failure(user.email)
        return False, "Invalid or expired OTP"
    return True, None
