from __future__ import annotations

import os
import shutil

import cv2
import numpy as np
import pytesseract


class EasyOCRService:
    """
    Tesseract-based OCR service.

    The class name is kept as EasyOCRService temporarily so that
    existing imports do not break while we migrate the project
    to the README architecture.
    """

    def __init__(self) -> None:
        self.tesseract_cmd = self._find_tesseract()

        pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd

    @staticmethod
    def _find_tesseract() -> str:
        """
        Find the Tesseract executable.

        Priority:
        1. NUTRILENS_TESSERACT_CMD environment variable
        2. Tesseract available on PATH
        3. Standard Windows installation path
        """

        # ----------------------------------------------------
        # 1. Environment variable
        # ----------------------------------------------------

        env_path = os.getenv("NUTRILENS_TESSERACT_CMD")

        if env_path:
            env_path = os.path.expandvars(
                os.path.expanduser(env_path)
            )

            if os.path.isfile(env_path):
                return env_path

        # ----------------------------------------------------
        # 2. PATH
        # ----------------------------------------------------

        path_result = shutil.which("tesseract")

        if path_result:
            return path_result

        # ----------------------------------------------------
        # 3. Standard Windows installation
        # ----------------------------------------------------

        windows_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]

        for path in windows_paths:
            if os.path.isfile(path):
                return path

        raise FileNotFoundError(
            "Tesseract OCR executable was not found. "
            "Set NUTRILENS_TESSERACT_CMD or install Tesseract OCR."
        )

    def extract_text(
        self,
        image_data: bytes,
        filename: str = "label.png",
    ) -> str:
        """
        Extract text from uploaded image bytes using Tesseract.
        """

        if not isinstance(image_data, bytes):
            raise ValueError(
                "Image data must be provided as bytes."
            )

        if not image_data:
            raise ValueError(
                "Uploaded image is empty."
            )

        # ----------------------------------------------------
        # Decode image
        # ----------------------------------------------------

        image_array = np.frombuffer(
            image_data,
            dtype=np.uint8,
        )

        image = cv2.imdecode(
            image_array,
            cv2.IMREAD_COLOR,
        )

        if image is None:
            raise ValueError(
                f"Could not decode image '{filename}'."
            )

        # ----------------------------------------------------
        # Prepare image for OCR
        # ----------------------------------------------------

        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY,
        )

        # Upscale small label text.
        height, width = gray.shape

        if width < 1600:
            scale = 1600 / width

            new_width = int(width * scale)
            new_height = int(height * scale)

            gray = cv2.resize(
                gray,
                (new_width, new_height),
                interpolation=cv2.INTER_CUBIC,
            )

        # ----------------------------------------------------
        # Light noise reduction
        # ----------------------------------------------------

        gray = cv2.GaussianBlur(
            gray,
            (3, 3),
            0,
        )

        # ----------------------------------------------------
        # Tesseract OCR
        # ----------------------------------------------------

        config = "--oem 3 --psm 6"

        text = pytesseract.image_to_string(
            gray,
            lang="eng",
            config=config,
        )

        # ----------------------------------------------------
        # Clean OCR output
        # ----------------------------------------------------

        lines = []

        for line in text.splitlines():
            cleaned = line.strip()

            if cleaned:
                lines.append(cleaned)

        return "\n".join(lines)
