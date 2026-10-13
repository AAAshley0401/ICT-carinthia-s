"""Port for a future vision model and conversion to the existing Agent schema."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .detection_validation import has_valid_shape


@dataclass(frozen=True)
class ModelDefect:
    defect_id: str
    label: str
    detection_score: float
    classification_score: float
    severity_label: str
    severity_score: float
    severity_distribution: Mapping[str, float]
    box_xyxy: tuple[float, float, float, float]
    mask_reference: str


@dataclass(frozen=True)
class ModelPrediction:
    sample_id: str
    model_version: str
    calibration_version: str
    defect_probability: float
    detections: tuple[ModelDefect, ...]
    image_analyzed: bool
    demo_only: bool
    inference_timestamp: str


class ModelBackend(Protocol):
    """A future model implementation converts its native output to this contract."""

    def predict(self, sample_id: str, image_path: str) -> ModelPrediction: ...


class DetectorPort(Protocol):
    """The call shape shared by DetectorAgent and ModelAdapter."""

    def detect(self, sample_id: str, image_path: str) -> dict[str, Any]: ...


class ModelAdapter:
    """Translate a backend prediction into the current detector result schema."""

    def __init__(self, backend: ModelBackend) -> None:
        self.backend = backend

    def detect(self, sample_id: str, image_path: str) -> dict[str, Any]:
        if not isinstance(sample_id, str) or not sample_id.strip():
            raise ValueError("sample_id must be a nonempty string")
        if not isinstance(image_path, str) or not image_path.strip():
            raise ValueError("image_path must be a nonempty string")

        try:
            prediction = self.backend.predict(sample_id, image_path)
        except TimeoutError:
            return self._failure(sample_id, "MODEL_TIMEOUT")
        except Exception:
            return self._failure(sample_id, "MODEL_BACKEND_ERROR")

        if not isinstance(prediction, ModelPrediction) or prediction.sample_id != sample_id:
            return self._failure(sample_id, "INVALID_MODEL_OUTPUT")

        try:
            result = {
                "schema_version": "1.0",
                "sample_id": sample_id,
                "status": "success",
                "mode": "mock" if prediction.demo_only else "model",
                "demo_only": prediction.demo_only,
                "image_analyzed": prediction.image_analyzed,
                "model_version": prediction.model_version,
                "calibration_version": prediction.calibration_version,
                "inference_timestamp": prediction.inference_timestamp,
                "defect_probability": prediction.defect_probability,
                "defects": [
                    {
                        "defect_id": defect.defect_id,
                        "defect_type": defect.label,
                        "detection_confidence": defect.detection_score,
                        "class_confidence": defect.classification_score,
                        "severity": defect.severity_label,
                        "severity_confidence": defect.severity_score,
                        "severity_probabilities": dict(defect.severity_distribution),
                        "bbox_xyxy": list(defect.box_xyxy),
                        "mask_ref": defect.mask_reference,
                    }
                    for defect in prediction.detections
                ],
                "error": None,
            }
            if not has_valid_shape(result, sample_id):
                return self._failure(sample_id, "INVALID_MODEL_OUTPUT")
            json.dumps(result, allow_nan=False)
            return result
        except (AttributeError, TypeError, ValueError):
            return self._failure(sample_id, "INVALID_MODEL_OUTPUT")

    @staticmethod
    def _failure(sample_id: str, code: str) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "sample_id": sample_id,
            "status": "failed",
            "mode": "model",
            "demo_only": False,
            "image_analyzed": False,
            "model_version": None,
            "calibration_version": None,
            "defect_probability": None,
            "defects": [],
            "error": {"code": code},
        }
