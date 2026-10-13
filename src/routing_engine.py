"""Validate model output and route inspection tasks without making production decisions."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping

from .task_state import InspectionTask, TaskState


GRADES = frozenset({"Acceptable", "Marginal NG", "NG", "Gross NG"})
REQUIRED_FIELDS = frozenset(
    {"sample_id", "mode", "demo_only", "image_analyzed", "model_version", "grade", "confidence", "defects"}
)


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

    if tool_error is not None:
        return _fail(task, "MODEL_TIMEOUT" if _is_timeout(tool_error) else "TOOL_ERROR")
    if not isinstance(result, Mapping):
        return _fail(task, "INVALID_RESPONSE_FORMAT")
    if result.get("error") is not None:
        return _fail(task, "MODEL_TIMEOUT" if _is_timeout(result["error"]) else "TOOL_ERROR")

    # The mock currently lacks fields needed by the real model contract. Its
    # explicit demo flag takes priority so it is never mistaken for real output.
    if result.get("demo_only") is True:
        task.transition_to(TaskState.INVALID_RESULT)
        return _decision(
            task, SelectedPath.FAILED, ("DEMO_RESULT",),
            "Demo output cannot be used for real production decisions.",
            "Cannot generate reliable suggestion", review=False,
        )

    if REQUIRED_FIELDS - result.keys():
        return _fail(task, "MISSING_REQUIRED_FIELDS")
    if not _valid_format(result, task.task_id):
        return _fail(task, "INVALID_RESPONSE_FORMAT")
    if result["mode"] != "model" or result["image_analyzed"] is not True:
        task.transition_to(TaskState.INVALID_RESULT)
        return _decision(
            task, SelectedPath.FAILED, ("UNTRUSTED_SOURCE",),
            "Detection was not produced by a verified image analysis result.",
            "Cannot generate reliable suggestion", review=False,
        )

    task.transition_to(TaskState.DETECT_SUCCESS)
    task.transition_to(TaskState.SORTING)
    reasons: list[str] = []
    if result["confidence"] < policy.confidence_threshold:
        reasons.append("LOW_CONFIDENCE")
    if result["grade"] == "Marginal NG" or result.get("near_boundary") is True or (
        "boundary_distance" in result and result["boundary_distance"] <= policy.boundary_margin
    ):
        reasons.append("SEVERITY_BOUNDARY")
    if result.get("conflict") is True:
        reasons.append("RULE_CONFLICT")
    # A severity confidence alone does not prove an Acceptable image has no defect.
    if result["grade"] == "Acceptable":
        if "screening_confidence" not in result:
            reasons.append("SCREENING_SCORE_MISSING")
        elif result["screening_confidence"] < policy.confidence_threshold:
            reasons.append("LOW_SCREENING_CONFIDENCE")
    if reasons:
        task.transition_to(TaskState.REVIEW_REQUIRED)
        return _decision(
            task, SelectedPath.REVIEW, tuple(reasons),
            "Detection needs human review: " + ", ".join(reasons) + ".",
            "Human review required", review=True,
        )

    task.transition_to(TaskState.SUGGESTION_READY)
    return _decision(
        task, SelectedPath.NORMAL, ("HIGH_CONFIDENCE",),
        "Validated detection satisfies the prototype routing rule; suggestion requires human confirmation.",
        "Generate normal quality suggestion", review=False,
    )


def _fail(task: InspectionTask, code: str) -> RoutingDecision:
    task.transition_to(TaskState.DETECT_FAILED)
    return _decision(
        task, SelectedPath.FAILED, (code,),
        f"Detection failed validation or execution: {code}. No reliable suggestion is available.",
        "Cannot generate reliable suggestion", review=False,
    )


def _is_timeout(error: object) -> bool:
    return isinstance(error, TimeoutError) or (
        isinstance(error, Mapping) and error.get("code") == "MODEL_TIMEOUT"
    )


def _valid_format(result: Mapping[str, Any], task_id: str) -> bool:
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
    if "screening_confidence" in result and not _is_score(result["screening_confidence"]):
        return False
    if "boundary_distance" in result and not _is_score(result["boundary_distance"]):
        return False
    if "near_boundary" in result and type(result["near_boundary"]) is not bool:
        return False
    if "conflict" in result and type(result["conflict"]) is not bool:
        return False
    return True
