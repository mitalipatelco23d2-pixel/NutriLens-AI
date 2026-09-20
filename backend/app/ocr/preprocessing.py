from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

from fastapi import UploadFile
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

from ..core.config import Settings, get_settings
from ..core.errors import InvalidImageError, UnsupportedMediaTypeError, UploadTooLargeError


ALLOWED_IMAGE_TYPES = {
    "image/jpeg": {"JPEG"},
    "image/png": {"PNG"},
    "image/webp": {"WEBP"},
}


@dataclass(frozen=True)
class PreparedImage:
    image: Image.Image
    original_width: int
    original_height: int
    preprocessing_applied: bool


async def read_upload_limited(upload: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(min(1024 * 1024, max_bytes + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLargeError()
        chunks.append(chunk)
    if total == 0:
        raise InvalidImageError("The uploaded image is empty")
    return b"".join(chunks)


def validate_and_preprocess_image(
    content: bytes,
    content_type: str | None,
    settings: Settings | None = None,
) -> PreparedImage:
    active_settings = settings or get_settings()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise UnsupportedMediaTypeError()

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as probe:
                probe.verify()
            with Image.open(io.BytesIO(content)) as source:
                if source.format not in ALLOWED_IMAGE_TYPES[content_type]:
                    raise UnsupportedMediaTypeError()
                width, height = source.size
                if width <= 0 or height <= 0:
                    raise InvalidImageError()
                if width * height > active_settings.max_image_pixels:
                    raise UploadTooLargeError("Image dimensions exceed the configured limit")
                image = ImageOps.exif_transpose(source).convert("RGB")
    except UnsupportedMediaTypeError:
        raise
    except UploadTooLargeError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise InvalidImageError() from exc

    processed = ImageOps.grayscale(image)
    preprocessing_applied = True
    if min(processed.size) < 1400:
        pixel_safe_scale = (active_settings.max_image_pixels / (processed.width * processed.height)) ** 0.5
        scale = max(1.0, min(3.0, 1400 / min(processed.size), pixel_safe_scale))
        processed = processed.resize(
            (round(processed.width * scale), round(processed.height * scale)),
            Image.Resampling.LANCZOS,
        )
    processed = ImageOps.autocontrast(processed, cutoff=1)
    processed = ImageEnhance.Contrast(processed).enhance(1.15)
    processed = processed.filter(ImageFilter.SHARPEN)

    return PreparedImage(
        image=processed,
        original_width=width,
        original_height=height,
        preprocessing_applied=preprocessing_applied,
    )
