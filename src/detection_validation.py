"""Read-only validation of detector responses and their provenance."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


GRADES = frozenset({"Acceptable", "Marginal NG", "NG", "Gross NG"})
REQUIRED_FIELDS = frozenset(
    {"sample_id", "mode", "demo_only", "image_analyzed", "model_version", "grade", "confidence", "defects"}
)


class ValidationStatus(str, Enum):
    VALID = "VALID"
    FAILED = "FAILED"
    INVALID_RESULT = "INVALID_RESULT"


@dataclass(frozen=True)
class ValidationResult:
    status: ValidationStatus
    reason_code: str | None = None

    @property
    def valid(self) -> bool:
        return self.status is ValidationStatus.VALID


def is_timeout(error: object) -> bool:
    return (
        isinstance(error, TimeoutError)
        or error == "MODEL_TIMEOUT"
        or (isinstance(error, Mapping) and error.get("code") == "MODEL_TIMEOUT")
    )


def _is_score(value: object) -> bool:
    return type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 1


def has_valid_shape(result: Mapping[str, Any], task_id: str) -> bool:
    """Validate fields and types without trusting the result's source."""
    if REQUIRED_FIELDS - result.keys():
        return False
    if result["sample_id"] != task_id:
        return False
    if not isinstance(result["mode"], str) or type(result["demo_only"]) is not bool:
        return False
    if type(result["image_analyzed"]) is not bool:
        return False
    if not isinstance(result["model_version"], str) or not result["model_version"].strip():
        return False
    if not isinstance(result["grade"], str) or result["grade"] not in GRADES:
        return False
    if not _is_score(result["confidence"]):
        return False
    if not isinstance(result["defects"], list):
        return False
    for defect in result["defects"]:
        if not isinstance(defect, Mapping):
            return False
        if not {"category", "severity", "confidence"} <= defect.keys():
            return False
        if not isinstance(defect["category"], str) or not defect["category"].strip():
            return False
        if not isinstance(defect["severity"], str) or defect["severity"] not in GRADES:
            return False
        if not _is_score(defect["confidence"]):
            return False
        bbox = defect.get("bbox_xyxy")
        if bbox is not None and (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in bbox)
            or bbox[0] >= bbox[2]
            or bbox[1] >= bbox[3]
        ):
            return False
    if "screening_confidence" in result and not _is_score(result["screening_confidence"]):
        return False
    if "boundary_distance" in result and not _is_score(result["boundary_distance"]):
        return False
    if "near_boundary" in result and type(result["near_boundary"]) is not bool:
        return False
    if "conflict" in result and type(result["conflict"]) is not bool:
        return False
    return True


def validate_detection_result(
    result: object, task_id: str, *, tool_error: object = None
) -> ValidationResult:
    if tool_error is not None:
        return ValidationResult(
            ValidationStatus.FAILED,
            "MODEL_TIMEOUT" if is_timeout(tool_error) else "TOOL_ERROR",
        )
    if not isinstance(result, Mapping):
        return ValidationResult(ValidationStatus.FAILED, "INVALID_RESPONSE_FORMAT")
    if result.get("error") is not None:
        return ValidationResult(
            ValidationStatus.FAILED,
            "MODEL_TIMEOUT" if is_timeout(result["error"]) else "TOOL_ERROR",
        )
    if result.get("demo_only") is True:
        return ValidationResult(ValidationStatus.INVALID_RESULT, "DEMO_RESULT")
    if REQUIRED_FIELDS - result.keys():
        return ValidationResult(ValidationStatus.FAILED, "MISSING_REQUIRED_FIELDS")
    if not has_valid_shape(result, task_id):
        return ValidationResult(ValidationStatus.FAILED, "INVALID_RESPONSE_FORMAT")
    if result["mode"] != "model" or result["image_analyzed"] is not True:
        return ValidationResult(ValidationStatus.INVALID_RESULT, "UNTRUSTED_SOURCE")
    return ValidationResult(ValidationStatus.VALID)
