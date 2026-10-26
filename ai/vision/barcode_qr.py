"""Local barcode and QR decoding with untrusted-payload handling."""

from __future__ import annotations

import re
import time
from typing import Any

import cv2
import numpy as np

from ai.food_understanding.schemas import BarcodeResult, Box, QRResult
from scripts.data_engineering.normalization import validate_gtin


def _points_to_box(points: Any) -> Box | None:
    if points is None:
        return None
    array = np.asarray(points, dtype=float).reshape(-1, 2)
    if array.size == 0:
        return None
    x1, y1 = array.min(axis=0)
    x2, y2 = array.max(axis=0)
    return Box(x=float(x1), y=float(y1), width=float(x2 - x1), height=float(y2 - y1))


def sanitize_qr_payload(payload: str, *, max_length: int = 2048) -> tuple[str, str]:
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", payload).strip()
    if len(cleaned) > max_length:
        return cleaned[:max_length], "REJECTED"
    return cleaned, "UNTRUSTED" if cleaned else "EMPTY"


def decode_qr(image: np.ndarray, *, view_id: str) -> tuple[list[QRResult], float]:
    started = time.perf_counter()
    detector = cv2.QRCodeDetector()
    results: list[QRResult] = []
    try:
        success, decoded, points, _ = detector.detectAndDecodeMulti(image)
        if success:
            for index, value in enumerate(decoded):
                cleaned, status = sanitize_qr_payload(str(value))
                polygon = points[index] if points is not None and index < len(points) else None
                results.append(
                    QRResult(
                        value=cleaned,
                        bounding_box=_points_to_box(polygon),
                        decoded=bool(cleaned),
                        safety_status=status,  # type: ignore[arg-type]
                        source_view_id=view_id,
                    )
                )
    except cv2.error:
        value, points, _ = detector.detectAndDecode(image)
        cleaned, status = sanitize_qr_payload(str(value))
        if points is not None or cleaned:
            results.append(
                QRResult(
                    value=cleaned,
                    bounding_box=_points_to_box(points),
                    decoded=bool(cleaned),
                    safety_status=status,  # type: ignore[arg-type]
                    source_view_id=view_id,
                )
            )
    return results, (time.perf_counter() - started) * 1000


def decode_barcodes(image: np.ndarray, *, view_id: str) -> tuple[list[BarcodeResult], float]:
    started = time.perf_counter()
    detector_type = getattr(cv2, "barcode_BarcodeDetector", None)
    if detector_type is None:
        return [], (time.perf_counter() - started) * 1000
    try:
        detector = detector_type()
        values: list[str] = []
        types: list[str] = []
        point_groups: list[Any] = []

        if hasattr(detector, "detectAndDecodeWithType"):
            ret = detector.detectAndDecodeWithType(image)
            # detectAndDecodeWithType returns (retval, decoded_info, decoded_type, points)
            if len(ret) == 4:
                retval, d_info, d_type, d_pts = ret
                if retval:
                    raw_vals = [d_info] if isinstance(d_info, str) else list(d_info or [])
                    raw_types = [d_type] if isinstance(d_type, str) else list(d_type or [])
                    values = [str(v) for v in raw_vals]
                    types = [str(t) for t in raw_types]
                    point_groups = [] if d_pts is None else list(np.asarray(d_pts))
        elif hasattr(detector, "detectAndDecode"):
            ret = detector.detectAndDecode(image)
            # Could be (decoded_info, points, straight_code) or legacy (info, types, points)
            if len(ret) == 3:
                first, second, third = ret
                if isinstance(second, list | tuple) and not isinstance(second, np.ndarray):
                    # Mock or legacy (info, types, points)
                    values = [first] if isinstance(first, str) else [str(v) for v in (first or [])]
                    types = [str(t) for t in second]
                    point_groups = [] if third is None else list(np.asarray(third))
                else:
                    # OpenCV standard: (decoded_info, points, straight_code)
                    if isinstance(first, str):
                        values = [first] if first.strip() else []
                    else:
                        values = [str(v) for v in (first or []) if str(v).strip()]
                    point_groups = [] if second is None else list(np.asarray(second))
                    types = ["UNKNOWN"] * len(values)

        results: list[BarcodeResult] = []
        for index, text in enumerate(values):
            clean_text = text.strip()
            if not clean_text:
                continue
            symbology = types[index] if index < len(types) and types[index] else "UNKNOWN"
            checksum = (
                validate_gtin(clean_text)
                if clean_text.isdigit() and len(clean_text) in {8, 12, 13, 14}
                else None
            )
            polygon = point_groups[index] if index < len(point_groups) else None
            results.append(
                BarcodeResult(
                    symbology=symbology,
                    value=clean_text,
                    checksum_valid=checksum,
                    bounding_box=_points_to_box(polygon),
                    confidence=1.0 if checksum is True else None,
                    source_view_id=view_id,
                )
            )
        return results, (time.perf_counter() - started) * 1000
    except (cv2.error, TypeError, ValueError):
        return [], (time.perf_counter() - started) * 1000
