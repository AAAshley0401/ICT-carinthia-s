"""Versioned mock detector output; no image is opened or analyzed."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote


class DetectorAgent:
    MODES = frozenset({"normal", "boundary", "failure"})
    MODEL_VERSION = "mock-detector-v2"

    def __init__(self, mode: str = "normal") -> None:
        if not isinstance(mode, str) or mode not in self.MODES:
            raise ValueError(f"mode must be one of: {', '.join(sorted(self.MODES))}")
        self.mode = mode

    def detect(self, sample_id: str, image_path: str) -> dict[str, Any]:
        if not isinstance(sample_id, str) or not sample_id.strip():
            raise ValueError("sample_id must be a nonempty string")
        if not isinstance(image_path, str) or not image_path.strip():
            raise ValueError("image_path must be a nonempty string")

        result: dict[str, Any] = {
            "schema_version": "1.0",
            "sample_id": sample_id,
            "status": "success",
            "mode": "mock",
            "demo_only": True,
            "image_analyzed": False,
            "model_version": self.MODEL_VERSION,
            "calibration_version": "mock-unvalidated",
            "inference_timestamp": datetime.now(timezone.utc).isoformat(),
            "defect_probability": 0.05,
            "defects": [],
            "error": None,
        }
        if self.mode == "boundary":
            result["defect_probability"] = 0.95
            result["defects"] = [{
                "defect_id": "d1",
                "defect_type": "scratch",
                "detection_confidence": 0.96,
                "class_confidence": 0.91,
                "severity": "Marginal NG",
                "severity_confidence": 0.52,
                "severity_probabilities": {
                    "Acceptable": 0.05,
                    "Marginal NG": 0.52,
                    "NG": 0.43,
                    "Gross NG": 0.0,
                },
                "bbox_xyxy": [320, 390, 500, 470],
                "mask_ref": f"mock://masks/{quote(sample_id, safe='')}/d1",
            }]
        elif self.mode == "failure":
            result.update(status="failed", defect_probability=None, error="timeout")
        return result
