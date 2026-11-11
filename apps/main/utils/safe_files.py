"""Helpers for safe handling of uploaded / generated files (audit SEC-08/09/19/25)."""
import os
import uuid

from django.core.exceptions import ValidationError

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 200 * 1024 * 1024
MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000


# ── unguessable stored file names ─────────────────────────────
def _unique_name(filename: str) -> str:
    ext = os.path.splitext(filename or '')[1].lower()[:10]
    return f"{uuid.uuid4().hex}{ext}"


def ad_asset_upload_to(instance, filename):
    return f"ad_assets/{_unique_name(filename)}"


def avatar_upload_to(instance, filename):
    return f"avatars/{_unique_name(filename)}"


def report_upload_to(instance, filename):
    return f"reports/{_unique_name(filename)}"


def admin_report_upload_to(instance, filename):
    return f"reports/admin/{_unique_name(filename)}"


# ── spreadsheet formula injection ─────────────────────────────
_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def excel_safe(value):
    """Neutralise strings that Excel/LibreOffice would execute as formulas."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


# ── content sniffing ──────────────────────────────────────────
_IMAGE_FORMATS = {
    'JPEG': 'image/jpeg', 'PNG': 'image/png', 'GIF': 'image/gif', 'BMP': 'image/bmp',
    'WEBP': 'image/webp', 'TIFF': 'image/tiff',
}


def sniff_video(head: bytes):
    """Return a MIME type if the leading bytes look like a supported video container."""
    if head[4:8] == b'ftyp':
        return 'video/quicktime' if head[8:12] == b'qt  ' else 'video/mp4'
    if head[:4] == b'\x1a\x45\xdf\xa3':
        return 'video/webm'
    if head[:4] == b'RIFF' and head[8:12] == b'AVI ':
        return 'video/x-msvideo'
    if head[:4] == b'FLV\x01':
        return 'video/x-flv'
    if head[:4] == b'OggS':
        return 'video/ogg'
    if head[:3] == b'\x00\x00\x01' and head[3:4] in (b'\xba', b'\xb3'):
        return 'video/mpeg'
    if head[:4] == b'\x30\x26\xb2\x75':
        return 'video/x-ms-wmv'
    if head[:1] == b'\x47' and len(head) > 188 and head[188:189] == b'\x47':
        return 'video/mp2t'
    return None


def detect_media_type(uploaded):
    """Inspect real file content. Returns (kind, mime) or raises ValidationError.

    The client-supplied content type is never trusted; SVG and other scriptable
    formats are not accepted.
    """
    from PIL import Image, UnidentifiedImageError

    size = getattr(uploaded, 'size', None)
    pos = uploaded.tell() if hasattr(uploaded, 'tell') else 0
    uploaded.seek(0)
    head = uploaded.read(512)
    uploaded.seek(0)

    video_mime = sniff_video(head)
    if video_mime:
        if size and size > MAX_VIDEO_BYTES:
            raise ValidationError("Video is too large (max 200 MB).")
        return 'VIDEO', video_mime

    try:
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        with Image.open(uploaded) as img:
            fmt = img.format
            img.verify()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise ValidationError("Unsupported or corrupt file. Upload a JPEG, PNG, GIF, WebP, BMP, TIFF image or an MP4/MOV/WebM video.")
    finally:
        uploaded.seek(0)

    if fmt not in _IMAGE_FORMATS:
        raise ValidationError(f"Image format '{fmt}' is not supported.")
    if size and size > MAX_IMAGE_BYTES:
        raise ValidationError("Image is too large (max 10 MB).")
    return 'IMAGE', _IMAGE_FORMATS[fmt]
