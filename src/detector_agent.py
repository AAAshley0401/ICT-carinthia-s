"""Deterministic detector simulator. It never opens or analyzes an image."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote


class DetectorAgent:
    """Produce one of three fixed, explicitly simulated detection outcomes."""

    MODES = frozenset({"normal", "boundary", "failure"})
    MODEL_VERSION = "mock-detector-v1"

    def __init__(self, mode: str = "normal") -> None:
        if not isinstance(mode, str) or mode not in self.MODES:
            raise ValueError(f"mode must be one of: {', '.join(sorted(self.MODES))}")
        self.mode = mode

    def detect(self, sample_id: str, image_path: str) -> dict[str, Any]:
        if not isinstance(sample_id, str) or not sample_id.strip():
            raise ValueError("sample_id must be a nonempty string")
        if not isinstance(image_path, str) or not image_path.strip():
            raise ValueError("image_path must be a nonempty string")

        # The requested fields are always present. Extra fields preserve the
        # existing routing contract; neither path nor mask references are read.
        result: dict[str, Any] = {
            "sample_id": sample_id,
            "defect_type": "",
            "confidence": 0.0,
            "severity": "",
            "model_version": self.MODEL_VERSION,
            "mask": "",
            "demo_only": True,
            "error": None,
            "mode": "mock",
            "image_analyzed": False,
            "grade": None,
            "defects": [],
            "conflict": False,
        }

        if self.mode == "normal":
            result.update(
                defect_type="none",
                confidence=0.98,
                severity="Acceptable",
                grade="Acceptable",
                screening_confidence=0.98,
            )
        elif self.mode == "boundary":
            mask = f"mock://masks/{quote(sample_id, safe='')}/scratch"
            result.update(
                defect_type="scratch",
                confidence=0.74,
                severity="Marginal NG",
                grade="Marginal NG",
                mask=mask,
                conflict=True,
                near_boundary=True,
                defects=[
                    {
                        "category": "scratch",
                        "confidence": 0.78,
                        "severity": "Marginal NG",
                        "bbox_xyxy": [320, 390, 500, 470],
                        "mask": mask,
                    }
                ],
            )
        else:
            result["error"] = {
                "code": "MODEL_TIMEOUT",
                "message": "Simulated detector timeout; no image was analyzed.",
            }

        return result
