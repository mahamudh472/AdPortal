from __future__ import annotations

from typing import Any

from django.utils import timezone

from main.models import (
    AdIntegration,
    PlatformSyncEvent,
    PlatformSyncOperation,
    PlatformSyncStatus,
    UnifiedCampaign,
)


def create_platform_sync_event(
    *,
    campaign: UnifiedCampaign,
    platform: str,
    operation: str,
    integration: AdIntegration | None = None,
    message: str = "",
    payload: dict[str, Any] | None = None,
    status: str = PlatformSyncStatus.QUEUED,
) -> PlatformSyncEvent:
    return PlatformSyncEvent.objects.create(
        organization=campaign.organization,
        campaign=campaign,
        integration=integration,
        platform=platform,
        operation=operation,
        status=status,
        message=message or "",
        payload=payload or {},
    )


def mark_platform_sync_event_in_progress(
    event: PlatformSyncEvent,
    *,
    message: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    event.status = PlatformSyncStatus.IN_PROGRESS
    if message:
        event.message = message
    if payload is not None:
        event.payload = payload
    if not event.started_at:
        event.started_at = timezone.now()
    event.error_message = None
    event.save(update_fields=["status", "message", "payload", "started_at", "error_message", "updated_at"])


def mark_platform_sync_event_success(
    event: PlatformSyncEvent,
    *,
    message: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    event.status = PlatformSyncStatus.SUCCESS
    if message:
        event.message = message
    if payload is not None:
        event.payload = payload
    if not event.started_at:
        event.started_at = timezone.now()
    event.completed_at = timezone.now()
    event.error_message = None
    event.save(
        update_fields=[
            "status",
            "message",
            "payload",
            "started_at",
            "completed_at",
            "error_message",
            "updated_at",
        ]
    )


def mark_platform_sync_event_failed(
    event: PlatformSyncEvent,
    *,
    error_message: str,
    message: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    event.status = PlatformSyncStatus.FAILED
    if message:
        event.message = message
    if payload is not None:
        event.payload = payload
    if not event.started_at:
        event.started_at = timezone.now()
    event.completed_at = timezone.now()
    event.error_message = str(error_message)
    event.save(
        update_fields=[
            "status",
            "message",
            "payload",
            "started_at",
            "completed_at",
            "error_message",
            "updated_at",
        ]
    )
