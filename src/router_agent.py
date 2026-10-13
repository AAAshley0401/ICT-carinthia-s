"""Small adapter that exposes actual and demonstration-only routing decisions."""

from __future__ import annotations

from typing import Any

from .routing_engine import EvidenceEvaluation, RoutingDecision, preview_demo_route, route_detection
from .task_state import InspectionTask


class RouterAgent:
    def decide(
        self, task: InspectionTask, detection_result: dict[str, Any]
    ) -> tuple[RoutingDecision, EvidenceEvaluation]:
        actual = route_detection(task, detection_result)
        if detection_result.get("demo_only") is True:
            preview = preview_demo_route(detection_result, task.task_id)
        else:
            preview = EvidenceEvaluation(
                actual.selected_path, actual.reason_codes, actual.explanation,
                actual.human_review_required, actual.recommended_action,
                actual.evidence_summary, actual.evidence,
            )
        return actual, preview
