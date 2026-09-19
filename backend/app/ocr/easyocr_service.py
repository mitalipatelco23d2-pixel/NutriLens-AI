from __future__ import annotations

import io
import logging
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)


class EasyOCRService:
    """OCR service using EasyOCR library for real text extraction from images.

    Extracts text from food-label images using pre-trained deep learning models.
    Keeps OCR logic isolated for easy maintenance and potential future library swaps.
    """

    def __init__(self, reader: Optional[object] = None):
        self.reader = reader

    def extract_text(self, image_bytes: bytes, filename: str = "label.png") -> str:
        """Extract text from an uploaded food-label image using EasyOCR.

        Args:
            image_bytes: Binary image data (PNG, JPEG, WEBP, etc.)
            filename: Name of the uploaded file for error reporting

        Returns:
            Extracted text string from the image

        Raises:
            ValueError: If image cannot be processed or OCR fails
            ImportError: If easyocr dependency is not installed
        """
        if not image_bytes:
            raise ValueError("No image data provided")

        try:
            # Load and validate image
            image = Image.open(io.BytesIO(image_bytes))
            logger.info(
                f"Processing image: {filename} (format: {image.format}, "
                f"size: {image.size})"
            )

            # Get OCR reader and extract text
            reader = self._get_reader()
            text_results = reader.readtext(image, detail=0, paragraph=True)

            if not text_results:
                logger.warning(f"No text detected in image: {filename}")
                return ""

            combined_text = "\n".join(text_results).strip()
            logger.info(f"Successfully extracted {len(combined_text)} characters")
            return combined_text

        except ImportError as e:
            logger.error("EasyOCR library not installed")
            raise ImportError(
                "EasyOCR dependency is not installed. "
                "Please install it with: pip install easyocr"
            ) from e
        except (OSError, ValueError) as e:
            logger.error(f"Invalid image file: {filename} - {str(e)}")
            raise ValueError(f"Cannot process image '{filename}': {str(e)}") from e
        except Exception as e:
            logger.error(f"OCR processing failed for {filename}: {str(e)}")
            raise RuntimeError(
                f"OCR processing failed: {str(e)}. "
                f"Please check your image file and try again."
            ) from e

    def _get_reader(self):
        """Get or initialize the EasyOCR reader with English language support.

        The reader is cached on first call for performance.
        GPU acceleration is disabled for compatibility across different environments.

        Returns:
            easyocr.Reader: Initialized OCR reader instance

        Raises:
            ImportError: If easyocr is not installed
        """
        if self.reader is not None:
            return self.reader

        try: 
            import easyocr
        except ImportError:
            logger.error("Failed to import easyocr")
            raise ImportError(
                "EasyOCR is not installed. Please install with: pip install easyocr"
            )

        logger.info("Initializing EasyOCR reader for English language...")
        self.reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        logger.info("EasyOCR reader initialized successfully")
        return self.reader
