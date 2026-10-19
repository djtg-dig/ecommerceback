"""Validation and storage primitives shared by business and catalog media.

The Cloudinary SDK is imported lazily: test suites can mock these functions and
development can start normally until a user actually attempts an upload.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import BinaryIO

from django.conf import settings
from django.core.exceptions import ValidationError


logger = logging.getLogger(__name__)


IMAGE_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
VIDEO_FORMATS = {"mov", "mp4", "webm"}


class MediaStorageError(Exception):
    """A safe, API-facing Cloudinary failure that contains no provider secret."""

    code = "media_storage_unavailable"
    detail = "Le service de stockage des médias est temporairement indisponible."
    status_code = 503


class MediaStoragePermissionError(MediaStorageError):
    code = "media_storage_permission_denied"
    detail = "Le service de stockage n’autorise pas la création de ce média."
    status_code = 502


@dataclass(frozen=True)
class MediaMetadata:
    media_type: str
    resource_type: str
    width: int
    height: int
    format: str
    size_bytes: int
    duration_seconds: Decimal | None = None


def _size(upload: BinaryIO) -> int:
    size = getattr(upload, "size", None)
    if size is not None:
        return int(size)
    position = upload.tell()
    upload.seek(0, 2)
    value = upload.tell()
    upload.seek(position)
    return value


def _rewind(upload: BinaryIO) -> None:
    if hasattr(upload, "seek"):
        upload.seek(0)


def validate_image(upload: BinaryIO, *, kind: str) -> MediaMetadata:
    """Inspect pixels, not the submitted extension or MIME type."""
    from PIL import Image, UnidentifiedImageError

    limits = {
        "logo": (2 * 1024 * 1024, 256, 256, 3000, 3000),
        "banner": (5 * 1024 * 1024, 1200, 400, 6000, 3000),
        "product": (settings.ECOMMERCE_MEDIA_IMAGE_MAX_BYTES, 800, 800, 6000, 6000),
    }
    maximum, min_width, min_height, max_width, max_height = limits[kind]
    size = _size(upload)
    if size <= 0 or size > maximum:
        raise ValidationError({"file": f"Le fichier image doit peser au plus {maximum // 1024 // 1024} Mo."})
    previous_limit = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = 36_000_000
        _rewind(upload)
        with Image.open(upload) as image:
            image.verify()
        _rewind(upload)
        with Image.open(upload) as image:
            image.load()
            image_format = (image.format or "").upper()
            width, height = image.size
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise ValidationError({"file": "Le fichier ne contient pas une image valide et sûre."}) from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit
        _rewind(upload)
    if image_format not in IMAGE_FORMATS:
        raise ValidationError({"file": "Formats image acceptés : JPEG, PNG ou WebP."})
    if not (min_width <= width <= max_width and min_height <= height <= max_height):
        raise ValidationError({"file": f"Dimensions attendues : de {min_width}×{min_height} à {max_width}×{max_height}px."})
    return MediaMetadata("IMAGE", "image", width, height, IMAGE_FORMATS[image_format], size)


def validate_video(upload: BinaryIO) -> MediaMetadata:
    """Use ffprobe to prove the container and video stream before Cloudinary."""
    size = _size(upload)
    if size <= 0 or size > settings.ECOMMERCE_MEDIA_VIDEO_MAX_BYTES:
        raise ValidationError({"file": "La vidéo doit peser au plus 50 Mo."})
    executable = shutil.which("ffprobe")
    if not executable:
        raise ValidationError({"file": "La validation vidéo est indisponible : ffprobe est requis."})
    suffix = Path(getattr(upload, "name", "upload.mp4")).suffix or ".upload"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix) as temporary:
            _rewind(upload)
            for chunk in getattr(upload, "chunks", lambda: iter(lambda: upload.read(1024 * 1024), b""))():
                temporary.write(chunk)
            temporary.flush()
            result = subprocess.run(
                [executable, "-v", "error", "-show_entries", "format=format_name,duration:stream=codec_type,width,height,codec_name", "-of", "json", temporary.name],
                capture_output=True, text=True, timeout=15, check=False,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValidationError({"file": "Impossible d’analyser cette vidéo."}) from exc
    finally:
        _rewind(upload)
    if result.returncode != 0:
        raise ValidationError({"file": "Le fichier ne contient pas une vidéo valide."})
    try:
        payload = json.loads(result.stdout)
        formats = set((payload["format"]["format_name"] or "").split(","))
        video = next(stream for stream in payload["streams"] if stream.get("codec_type") == "video")
        duration = Decimal(str(payload["format"]["duration"]))
        width, height = int(video["width"]), int(video["height"])
    except (KeyError, StopIteration, TypeError, ValueError, ArithmeticError, json.JSONDecodeError) as exc:
        raise ValidationError({"file": "La vidéo doit contenir une piste vidéo exploitable."}) from exc
    if not formats.intersection(VIDEO_FORMATS):
        raise ValidationError({"file": "Formats vidéo acceptés : MP4, WebM ou MOV."})
    if duration <= 0 or duration > Decimal("60"):
        raise ValidationError({"file": "La durée de la vidéo ne peut pas dépasser 60 secondes."})
    if min(width, height) < 480 or max(width, height) > 1920:
        raise ValidationError({"file": "La résolution vidéo doit être comprise entre 480p et 1080p."})
    format_name = "webm" if "webm" in formats else "mov" if "mov" in formats else "mp4"
    return MediaMetadata("VIDEO", "video", width, height, format_name, size, duration.quantize(Decimal("0.001")))


def upload_to_cloudinary(upload: BinaryIO, *, folder: str, resource_type: str, metadata: MediaMetadata) -> dict:
    if not settings.CLOUDINARY_ENABLED:
        raise MediaStorageError("Cloudinary is not configured.")
    try:
        import cloudinary
        import cloudinary.uploader
        from cloudinary.exceptions import AuthorizationRequired, NotAllowed, RateLimited

        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True,
        )
        _rewind(upload)
        return cloudinary.uploader.upload(upload, folder=folder, resource_type=resource_type, use_filename=False, unique_filename=True)
    except (NotAllowed, AuthorizationRequired) as exc:
        logger.warning("Cloudinary refused media creation for resource_type=%s", resource_type, exc_info=True)
        raise MediaStoragePermissionError("Cloudinary denied create permission.") from exc
    except RateLimited as exc:
        logger.warning("Cloudinary rate limit reached for resource_type=%s", resource_type, exc_info=True)
        raise MediaStorageError("Cloudinary rate limit reached.") from exc
    except Exception as exc:  # SDK exceptions vary by release and network transport.
        logger.exception("Cloudinary media upload failed for resource_type=%s", resource_type)
        raise MediaStorageError("Cloudinary media upload failed.") from exc


def destroy_cloudinary(public_id: str, *, resource_type: str, required_prefix: str) -> None:
    """Never delete a public id outside this service's business-owned folder."""
    if not public_id.startswith(required_prefix):
        raise ValueError("Refus de supprimer une ressource Cloudinary hors périmètre.")
    if not settings.CLOUDINARY_ENABLED:
        return
    try:
        import cloudinary.uploader
        cloudinary.uploader.destroy(public_id, resource_type=resource_type, invalidate=True)
    except Exception:
        # The database operation is already committed. A scheduled cleanup can
        # retry this id; do not roll back a user-visible DB deletion.
        return
