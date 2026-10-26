"""Safe, in-memory image validation for camera/gallery/file uploads."""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from ai.food_understanding.config import R3Config
from ai.food_understanding.schemas import ImageMetadata, ViewType

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
FORMAT_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
EXTENSION_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}


class ImageInputError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ValidatedImage:
    metadata: ImageMetadata
    original_bgr: np.ndarray


def sanitize_filename(filename: str) -> str:
    """Return a basename containing only conservative filename characters."""
    basename = Path(filename.replace("\\", "/")).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", basename).strip("._")
    return (cleaned or "upload")[:120]


def validate_image_bytes(
    content: bytes,
    *,
    filename: str,
    mime_type: str,
    view_id: str,
    view_type: ViewType,
    config: R3Config,
) -> ValidatedImage:
    """Validate declared and decoded type, dimensions, size, and image integrity."""
    if not content:
        raise ImageInputError("EMPTY_FILE", "The uploaded image is empty.")
    if len(content) > config.max_upload_bytes:
        raise ImageInputError(
            "FILE_TOO_LARGE", f"Image exceeds the {config.max_upload_bytes}-byte limit."
        )

    safe_filename = sanitize_filename(filename)
    extension = Path(safe_filename).suffix.lower()
    declared_format = EXTENSION_FORMATS.get(extension)
    if declared_format is None:
        raise ImageInputError("UNSUPPORTED_EXTENSION", "Use a JPEG, PNG, or WebP file.")
    normalized_mime = mime_type.lower().split(";", maxsplit=1)[0].strip()
    if normalized_mime not in FORMAT_MIME.values():
        raise ImageInputError("UNSUPPORTED_MIME", "Use image/jpeg, image/png, or image/webp.")

    try:
        with Image.open(io.BytesIO(content)) as probe:
            detected_format = (probe.format or "").upper()
            probe.verify()
        if detected_format not in ALLOWED_FORMATS:
            raise ImageInputError("UNSUPPORTED_FORMAT", "Decoded image format is unsupported.")
        if declared_format != detected_format:
            raise ImageInputError("EXTENSION_MISMATCH", "File extension does not match image data.")
        if FORMAT_MIME[detected_format] != normalized_mime:
            raise ImageInputError("MIME_MISMATCH", "MIME type does not match image data.")

        with Image.open(io.BytesIO(content)) as decoded:
            orientation = int(decoded.getexif().get(274, 1))
            source_width, source_height = decoded.size
            if max(source_width, source_height) > config.max_image_dimension:
                raise ImageInputError(
                    "IMAGE_TOO_LARGE",
                    f"No dimension may exceed {config.max_image_dimension} pixels.",
                )
            if source_width * source_height > config.max_image_pixels:
                raise ImageInputError(
                    "IMAGE_TOO_MANY_PIXELS",
                    f"Image exceeds the {config.max_image_pixels}-pixel limit.",
                )
            corrected = ImageOps.exif_transpose(decoded)
            corrected.load()
            width, height = corrected.size
            if min(width, height) < config.min_image_dimension:
                raise ImageInputError(
                    "IMAGE_TOO_SMALL",
                    f"Both dimensions must be at least {config.min_image_dimension} pixels.",
                )
            if max(width, height) > config.max_image_dimension:
                raise ImageInputError(
                    "IMAGE_TOO_LARGE",
                    f"No dimension may exceed {config.max_image_dimension} pixels.",
                )
            rgb = np.asarray(corrected.convert("RGB"), dtype=np.uint8)
    except ImageInputError:
        raise
    except Image.DecompressionBombError as exc:
        raise ImageInputError("DECOMPRESSION_BOMB", "Image dimensions are unsafe.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageInputError(
            "CORRUPT_IMAGE", "Image content could not be decoded safely."
        ) from exc

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    metadata = ImageMetadata(
        view_id=view_id,
        view_type=view_type,
        original_filename=Path(filename.replace("\\", "/")).name[:120],
        safe_filename=safe_filename,
        mime_type=normalized_mime,
        detected_format=detected_format,  # type: ignore[arg-type]
        width=width,
        height=height,
        byte_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        exif_orientation_applied=orientation not in {0, 1},
    )
    return ValidatedImage(metadata=metadata, original_bgr=bgr)


def encoded_pixel_count(content: bytes) -> int:
    """Read encoded dimensions without allocating the decoded pixel buffer."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            return width * height
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ImageInputError(
            "CORRUPT_IMAGE", "Image dimensions could not be read safely."
        ) from exc
