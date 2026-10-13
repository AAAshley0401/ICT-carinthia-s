"""Validate the detector's versioned evidence contract and provenance."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


GRADES = ("Acceptable", "Marginal NG", "NG", "Gross NG")
REQUIRED_FIELDS = frozenset({
    "schema_version", "sample_id", "status", "mode", "demo_only",
    "image_analyzed", "model_version", "calibration_version",
    "defect_probability", "defects", "error",
})
REQUIRED_DEFECT_FIELDS = frozenset({
    "defect_id", "defect_type", "detection_confidence", "class_confidence",
    "severity", "severity_confidence", "severity_probabilities",
    "bbox_xyxy", "mask_ref",
})


class ValidationStatus(str, Enum):
    VALID = "VALID"
    INVALID_RESULT = "INVALID_RESULT"


@dataclass(frozen=True)
class ValidationResult:
    status: ValidationStatus
    reason_code: str | None = None

    @property
    def valid(self) -> bool:
        return self.status is ValidationStatus.VALID


def is_score(value: object) -> bool:
    return type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 1


def has_valid_shape(result: Mapping[str, Any], task_id: str) -> bool:
    """Check the success payload's fields and value ranges, without provenance."""
    if REQUIRED_FIELDS - result.keys():
        return False
    if result["schema_version"] != "1.0" or result["sample_id"] != task_id:
        return False
    if result["status"] != "success" or result["error"] is not None:
        return False
    if not isinstance(result["mode"], str):
        return False
    if type(result["demo_only"]) is not bool or type(result["image_analyzed"]) is not bool:
        return False
    for field in ("model_version", "calibration_version"):
        if not isinstance(result[field], str) or not result[field].strip():
            return False
    if not is_score(result["defect_probability"]):
        return False
    defects = result["defects"]
    if not isinstance(defects, list):
        return False
    seen_ids: set[str] = set()
    for defect in defects:
        if not isinstance(defect, Mapping) or REQUIRED_DEFECT_FIELDS - defect.keys():
            return False
        for field in ("defect_id", "defect_type", "mask_ref"):
            if not isinstance(defect[field], str) or not defect[field].strip():
                return False
        if defect["defect_id"] in seen_ids:
            return False
        seen_ids.add(defect["defect_id"])
        for field in ("detection_confidence", "class_confidence", "severity_confidence"):
            if not is_score(defect[field]):
                return False
        if defect["severity"] not in GRADES:
            return False
        probabilities = defect["severity_probabilities"]
        if not isinstance(probabilities, Mapping) or set(probabilities) != set(GRADES):
            return False
        if not all(is_score(probabilities[grade]) for grade in GRADES):
            return False
        if not math.isclose(sum(probabilities.values()), 1.0, abs_tol=0.001):
            return False
        bbox = defect["bbox_xyxy"]
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in bbox)
            or bbox[0] < 0 or bbox[1] < 0
            or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]
        ):
            return False
    return True


def validate_detection_result(
    result: object, task_id: str, *, tool_error: object = None
) -> ValidationResult:
    if tool_error is not None:
        return ValidationResult(ValidationStatus.INVALID_RESULT, "TOOL_ERROR")
    if not isinstance(result, Mapping):
        return ValidationResult(ValidationStatus.INVALID_RESULT, "INVALID_SCHEMA")
    if result.get("error") is not None or result.get("status") == "failed":
        return ValidationResult(ValidationStatus.INVALID_RESULT, "TOOL_ERROR")
    if result.get("demo_only") is True:
        return ValidationResult(ValidationStatus.INVALID_RESULT, "DEMO_RESULT")
    if not has_valid_shape(result, task_id):
        return ValidationResult(ValidationStatus.INVALID_RESULT, "INVALID_SCHEMA")
    if result["mode"] != "model" or result["image_analyzed"] is not True:
        return ValidationResult(ValidationStatus.INVALID_RESULT, "INVALID_SCHEMA")
    return ValidationResult(ValidationStatus.VALID)
