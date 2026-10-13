"""Validate model output and route inspection tasks without making production decisions."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping

from .detection_validation import ValidationStatus, has_valid_shape, validate_detection_result
from .task_state import InspectionTask, TaskState


class SelectedPath(str, Enum):
    NORMAL = "NORMAL"
    REVIEW = "REVIEW"
    FAILED = "FAILED"


@dataclass(frozen=True)
class RoutingDecision:
    task_id: str
    current_state: TaskState
    selected_path: SelectedPath
    reason_codes: tuple[str, ...]
    explanation: str
    human_review_required: bool
    action: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["current_state"] = self.current_state.value
        result["selected_path"] = self.selected_path.value
        result["reason_codes"] = list(self.reason_codes)
        return result


@dataclass(frozen=True)
class PreviewRoutingDecision:
    selected_path: SelectedPath
    reason_codes: tuple[str, ...]
    explanation: str
    human_review_required: bool


@dataclass(frozen=True)
class RoutingPolicy:
    confidence_threshold: float = 0.90
    boundary_margin: float = 0.05

    def __post_init__(self) -> None:
        if not _is_score(self.confidence_threshold) or not 0 < self.confidence_threshold <= 1:
            raise ValueError("confidence_threshold must be in (0, 1]")
        if not _is_score(self.boundary_margin) or not 0 <= self.boundary_margin <= 1:
            raise ValueError("boundary_margin must be in [0, 1]")


def _is_score(value: object) -> bool:
    return type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 1


def _decision(
    task: InspectionTask,
    path: SelectedPath,
    codes: tuple[str, ...],
    explanation: str,
    action: str,
    *,
    review: bool,
) -> RoutingDecision:
    return RoutingDecision(task.task_id, task.state, path, codes, explanation, review, action)


def route_detection(
    task: InspectionTask,
    result: object = None,
    *,
    tool_error: object = None,
    policy: RoutingPolicy | None = None,
) -> RoutingDecision:
    """Consume one detection attempt. The caller owns the task and must not route it twice.

    Threshold defaults are prototype settings, not calibrated production rules.
    A tool timeout may be supplied as TimeoutError or as an error mapping with
    code=MODEL_TIMEOUT. Other errors use TOOL_ERROR.
    """
    if task.state != TaskState.CREATED:
        raise ValueError("route_detection requires a new CREATED task")
    policy = policy or RoutingPolicy()
    task.transition_to(TaskState.DETECTING)

    validation = validate_detection_result(result, task.task_id, tool_error=tool_error)
    if validation.status is ValidationStatus.FAILED:
        return _fail(task, validation.reason_code or "INVALID_RESPONSE_FORMAT")
    if validation.status is ValidationStatus.INVALID_RESULT:
        task.transition_to(TaskState.INVALID_RESULT)
        if validation.reason_code == "DEMO_RESULT":
            explanation = "Demo output cannot be used for real production decisions."
        else:
            explanation = "Detection was not produced by a verified image analysis result."
        return _decision(
            task, SelectedPath.FAILED, (validation.reason_code or "UNTRUSTED_SOURCE",),
            explanation,
            "Cannot generate reliable suggestion", review=False,
        )

    task.transition_to(TaskState.DETECT_SUCCESS)
    task.transition_to(TaskState.SORTING)
    reasons = _review_reasons(result, policy)
    if reasons:
        task.transition_to(TaskState.REVIEW_REQUIRED)
        return _decision(
            task, SelectedPath.REVIEW, reasons,
            "Detection needs human review: " + ", ".join(reasons) + ".",
            "Human review required", review=True,
        )

    task.transition_to(TaskState.SUGGESTION_READY)
    return _decision(
        task, SelectedPath.NORMAL, ("HIGH_CONFIDENCE",),
        "Validated detection satisfies the prototype routing rule; suggestion requires human confirmation.",
        "Generate normal quality suggestion", review=False,
    )


def preview_demo_route(
    result: object, task_id: str, *, policy: RoutingPolicy | None = None
) -> PreviewRoutingDecision:
    """Show the route rules would choose for a mock, without authorizing action."""
    if not isinstance(result, Mapping) or result.get("demo_only") is not True:
        raise ValueError("preview_demo_route accepts only demo results")
    validation = validate_detection_result(result, task_id)
    if validation.status is ValidationStatus.FAILED:
        code = validation.reason_code or "INVALID_RESPONSE_FORMAT"
        return PreviewRoutingDecision(
            SelectedPath.FAILED, (code,),
            f"Simulated detector failed: {code}. No quality suggestion is available.", False,
        )
    if not has_valid_shape(result, task_id):
        return PreviewRoutingDecision(
            SelectedPath.FAILED, ("INVALID_RESPONSE_FORMAT",),
            "Simulated detector returned an invalid response format.", False,
        )
    reasons = _review_reasons(result, policy or RoutingPolicy())
    if reasons:
        return PreviewRoutingDecision(
            SelectedPath.REVIEW, reasons,
            "Preview requires human review because: " + ", ".join(reasons) + ".",
            True,
        )
    return PreviewRoutingDecision(
        SelectedPath.NORMAL, ("HIGH_CONFIDENCE",),
        "Preview suggests a normal path; no real image was analyzed or production decision made.",
        False,
    )


def _review_reasons(result: Mapping[str, Any], policy: RoutingPolicy) -> tuple[str, ...]:
    reasons: list[str] = []
    if result["confidence"] < policy.confidence_threshold:
        reasons.append("LOW_CONFIDENCE")
    if result["grade"] == "Marginal NG" or result.get("near_boundary") is True or (
        "boundary_distance" in result and result["boundary_distance"] <= policy.boundary_margin
    ):
        reasons.append("SEVERITY_BOUNDARY")
    if result.get("conflict") is True:
        reasons.append("RULE_CONFLICT")
    if (result["grade"] != "Acceptable" and not result["defects"]) or any(
        defect["severity"] != result["grade"] for defect in result["defects"]
    ):
        reasons.append("GRADE_DEFECT_CONFLICT")
    # A severity confidence alone does not prove an Acceptable image has no defect.
    if result["grade"] == "Acceptable":
        if "screening_confidence" not in result:
            reasons.append("SCREENING_SCORE_MISSING")
        elif result["screening_confidence"] < policy.confidence_threshold:
            reasons.append("LOW_SCREENING_CONFIDENCE")
    return tuple(reasons)


def _fail(task: InspectionTask, code: str) -> RoutingDecision:
    task.transition_to(TaskState.DETECT_FAILED)
    return _decision(
        task, SelectedPath.FAILED, (code,),
        f"Detection failed validation or execution: {code}. No reliable suggestion is available.",
        "Cannot generate reliable suggestion", review=False,
    )
