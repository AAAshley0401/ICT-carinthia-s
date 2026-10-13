"""Evidence-based routing for the existing inspection task state machine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping

from .detection_validation import GRADES, ValidationStatus, has_valid_shape, is_score, validate_detection_result
from .task_state import InspectionTask, TaskState


class SelectedPath(str, Enum):
    NORMAL = "NORMAL"
    REVIEW = "REVIEW"
    SUGGESTION = "SUGGESTION"
    FAILED = "FAILED"


@dataclass(frozen=True)
class RoutingPolicy:
    normal_probability_threshold: float = 0.2
    detection_threshold: float = 0.85
    class_threshold: float = 0.85
    severity_threshold: float = 0.8
    severity_gap_threshold: float = 0.2

    def __post_init__(self) -> None:
        for field, value in vars(self).items():
            if not is_score(value):
                raise ValueError(f"{field} must be in [0, 1]")


@dataclass(frozen=True)
class EvidenceEvaluation:
    path: SelectedPath
    reason_codes: tuple[str, ...]
    explanation: str
    human_review_required: bool
    recommended_action: str | None
    evidence_summary: str
    evidence: dict[str, Any]


@dataclass(frozen=True)
class RoutingDecision:
    task_id: str
    current_state: TaskState
    selected_path: SelectedPath
    reason_codes: tuple[str, ...]
    explanation: str
    human_review_required: bool
    recommended_action: str | None
    evidence_summary: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["current_state"] = self.current_state.value
        result["selected_path"] = self.selected_path.value
        result["reason_codes"] = list(self.reason_codes)
        result["sample_id"] = self.task_id
        result["agent_called"] = ["DetectorAgent", "RouterAgent"]
        result["path"] = self.selected_path.value
        return result


def _decision(task: InspectionTask, evaluation: EvidenceEvaluation) -> RoutingDecision:
    return RoutingDecision(
        task.task_id, task.state, evaluation.path, evaluation.reason_codes,
        evaluation.explanation, evaluation.human_review_required,
        evaluation.recommended_action, evaluation.evidence_summary, evaluation.evidence,
    )


def _failed(code: str) -> EvidenceEvaluation:
    explanation = {
        "DEMO_RESULT": "Demo output cannot be used for real production decisions.",
        "TOOL_ERROR": "Detector tool failed; no reliable suggestion is available.",
        "INVALID_SCHEMA": "Detector output does not satisfy the required model contract.",
        "EVIDENCE_CONFLICT": "Defect probability indicates a possible defect, but no localized defect evidence was returned.",
    }[code]
    return EvidenceEvaluation(
        SelectedPath.FAILED, (code,), explanation, True, None,
        "No valid detection evidence.", _empty_evidence(),
    )


def _empty_evidence() -> dict[str, Any]:
    return {
        "defect_probability": None,
        "detection_confidence": None,
        "class_confidence": None,
        "severity_confidence": None,
        "defects": [],
    }


def _collect_evidence(result: Mapping[str, Any]) -> dict[str, Any]:
    defects = result["defects"]
    return {
        "defect_probability": result["defect_probability"],
        "detection_confidence": min((d["detection_confidence"] for d in defects), default=None),
        "class_confidence": min((d["class_confidence"] for d in defects), default=None),
        "severity_confidence": min((d["severity_confidence"] for d in defects), default=None),
        "defects": [
            {
                "defect_id": d["defect_id"],
                "defect_type": d["defect_type"],
                "detection_confidence": d["detection_confidence"],
                "class_confidence": d["class_confidence"],
                "severity": d["severity"],
                "severity_confidence": d["severity_confidence"],
                "severity_gap": round(_severity_gap(d["severity_probabilities"]), 6),
            }
            for d in defects
        ],
    }


def _severity_gap(probabilities: Mapping[str, float]) -> float:
    top, second = sorted(probabilities.values(), reverse=True)[:2]
    return top - second


def _evaluate_evidence(result: Mapping[str, Any], policy: RoutingPolicy) -> EvidenceEvaluation:
    evidence = _collect_evidence(result)
    probability = result["defect_probability"]
    if probability < policy.normal_probability_threshold:
        return EvidenceEvaluation(
            SelectedPath.NORMAL, ("LOW_DEFECT_PROBABILITY",),
            "Defect probability is below the normal-candidate threshold.", False,
            "Present as a normal candidate for human confirmation.",
            f"Defect probability {probability:.2f}; defect routing skipped.", evidence,
        )

    reasons: list[str] = []
    defects = result["defects"]
    for defect in defects:
        if defect["detection_confidence"] < policy.detection_threshold:
            reasons.append("LOW_DETECTION_CONFIDENCE")
        if defect["class_confidence"] < policy.class_threshold:
            reasons.append("UNCERTAIN_DEFECT_TYPE")
        if defect["severity_confidence"] < policy.severity_threshold:
            reasons.append("UNCERTAIN_SEVERITY")
        if defect["severity"] != max(
            GRADES, key=lambda grade: defect["severity_probabilities"][grade]
        ):
            reasons.append("SEVERITY_LABEL_CONFLICT")
        if _severity_gap(defect["severity_probabilities"]) < policy.severity_gap_threshold:
            reasons.append("SEVERITY_BOUNDARY")
    reasons = list(dict.fromkeys(reasons))
    summary = f"Defect probability {probability:.2f}; {len(defects)} localized defect(s)."
    if reasons:
        return EvidenceEvaluation(
            SelectedPath.REVIEW, tuple(reasons),
            "Human review required because: " + ", ".join(reasons) + ".",
            True, None, summary, evidence,
        )

    highest_grade = max((d["severity"] for d in defects), key=GRADES.index)
    return EvidenceEvaluation(
        SelectedPath.SUGGESTION, ("RELIABLE_DEFECT_EVIDENCE",),
        "Detection, classification and severity evidence meet the prototype thresholds.",
        False, f"Suggest {highest_grade} handling; human confirmation required before any action.",
        summary, evidence,
    )


def route_detection(
    task: InspectionTask,
    result: object = None,
    *,
    tool_error: object = None,
    policy: RoutingPolicy | None = None,
) -> RoutingDecision:
    """Validate one model response, update task state, then route its evidence."""
    if task.state is not TaskState.CREATED:
        raise ValueError("route_detection requires a new CREATED task")
    policy = policy or RoutingPolicy()
    task.transition_to(TaskState.DETECTING)
    validation = validate_detection_result(result, task.task_id, tool_error=tool_error)
    if validation.status is ValidationStatus.INVALID_RESULT:
        task.transition_to(TaskState.INVALID_RESULT)
        return _decision(task, _failed(validation.reason_code or "INVALID_SCHEMA"))
    if (
        result["defect_probability"] >= policy.normal_probability_threshold
        and not result["defects"]
    ):
        task.transition_to(TaskState.INVALID_RESULT)
        return _decision(task, _failed("EVIDENCE_CONFLICT"))

    task.transition_to(TaskState.DETECT_SUCCESS)
    task.transition_to(TaskState.SORTING)
    evaluation = _evaluate_evidence(result, policy)
    task.transition_to(
        TaskState.REVIEW_REQUIRED if evaluation.path is SelectedPath.REVIEW else TaskState.SUGGESTION_READY
    )
    return _decision(task, evaluation)


def preview_demo_route(
    result: object, task_id: str, *, policy: RoutingPolicy | None = None
) -> EvidenceEvaluation:
    """Exercise identical routing rules on a mock without changing its provenance."""
    if not isinstance(result, Mapping) or result.get("demo_only") is not True:
        raise ValueError("preview_demo_route accepts only demo results")
    if result.get("error") is not None or result.get("status") == "failed":
        return _failed("TOOL_ERROR")
    if not has_valid_shape(result, task_id):
        return _failed("INVALID_SCHEMA")
    policy = policy or RoutingPolicy()
    if (
        result["defect_probability"] >= policy.normal_probability_threshold
        and not result["defects"]
    ):
        return _failed("EVIDENCE_CONFLICT")
    return _evaluate_evidence(result, policy)
