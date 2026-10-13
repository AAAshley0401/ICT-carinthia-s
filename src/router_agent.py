"""Small adapter that exposes actual and demonstration-only routing decisions."""

from __future__ import annotations

from typing import Any

from .routing_engine import PreviewRoutingDecision, RoutingDecision, preview_demo_route, route_detection
from .task_state import InspectionTask


class RouterAgent:
    def decide(
        self, task: InspectionTask, detection_result: dict[str, Any]
    ) -> tuple[RoutingDecision, PreviewRoutingDecision]:
        actual = route_detection(task, detection_result)
        preview = preview_demo_route(detection_result, task.task_id)
        return actual, preview
