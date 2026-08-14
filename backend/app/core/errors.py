from __future__ import annotations


class NutriLensError(Exception):
    """Expected application error safe to translate into an API response."""

    code = "application_error"
    status_code = 500
    public_message = "The request could not be completed."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.public_message)


class InvalidImageError(NutriLensError):
    code = "invalid_image"
    status_code = 400
    public_message = "The uploaded file is not a valid supported image."


class UnsupportedMediaTypeError(NutriLensError):
    code = "unsupported_media_type"
    status_code = 415
    public_message = "Only JPEG, PNG, and WEBP images are supported."


class UploadTooLargeError(NutriLensError):
    code = "upload_too_large"
    status_code = 413
    public_message = "The uploaded image exceeds the configured size limit."


class OcrUnavailableError(NutriLensError):
    code = "ocr_unavailable"
    status_code = 503
    public_message = "The OCR service is not available."


class OcrProcessingError(NutriLensError):
    code = "ocr_failed"
    status_code = 422
    public_message = "Text could not be extracted from this image."


class InvalidOcrEngineError(NutriLensError):
    code = "invalid_ocr_engine"
    status_code = 422
    public_message = "The requested OCR engine is not supported."


class ModelUnavailableError(NutriLensError):
    code = "model_unavailable"
    status_code = 503
    public_message = "The health-score model is not available."


class InvalidModelInputError(NutriLensError):
    code = "invalid_model_input"
    status_code = 422
    public_message = "The nutrition data is incomplete or invalid for scoring."


class ModelInferenceError(NutriLensError):
    code = "model_inference_failed"
    status_code = 503
    public_message = "Health scoring is temporarily unavailable."
