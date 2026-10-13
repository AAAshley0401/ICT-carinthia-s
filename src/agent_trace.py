"""Collect JSON-safe execution steps and render a compact console view."""

from __future__ import annotations

import json
from typing import Any, Mapping


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("trace data must be a mapping")
    return json.loads(json.dumps(dict(value), ensure_ascii=False, allow_nan=False))


class TraceCollector:
    def __init__(self, sample_id: str) -> None:
        if not isinstance(sample_id, str) or not sample_id.strip():
            raise ValueError("sample_id must be a nonempty string")
        self.sample_id = sample_id
        self._steps: list[dict[str, Any]] = []

    def add_step(
        self,
        agent_name: str,
        *,
        input_data: Mapping[str, Any] | None = None,
        output_data: Mapping[str, Any] | None = None,
        decision_data: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(agent_name, str) or not agent_name.strip():
            raise ValueError("agent_name must be a nonempty string")
        step: dict[str, Any] = {"agent": agent_name}
        if input_data is not None:
            step["input"] = _json_copy(input_data)
        if output_data is not None:
            step["output_summary"] = _json_copy(output_data)
        if decision_data is not None:
            step["decision"] = _json_copy(decision_data)
        self._steps.append(step)

    def to_dict(self, final_decision: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "execution_trace": _json_copy({"steps": self._steps})["steps"],
            "final_decision": _json_copy(final_decision),
        }


def format_trace(trace: Mapping[str, Any]) -> str:
    """Render the same structured trace without discarding provenance details."""
    lines = ["========== Agent Execution Trace ==========", f"Sample: {trace['sample_id']}", ""]
    for step in trace["execution_trace"]:
        lines.append(f"[{step['agent']}]")
        summary = step.get("output_summary", {})
        decision = step.get("decision", {})
        if step["agent"] not in {"ValidationAgent", "RoutingEngine"}:
            lines.append(f"Status: {str(summary.get('status', 'unknown')).upper()}")
            lines.append(f"Defect probability: {summary.get('defect_probability')}")
            lines.append(f"Model version: {summary.get('model_version')}")
            if summary.get("error") is not None:
                lines.append(f"Tool error: {summary['error']}")
        elif step["agent"] == "ValidationAgent":
            lines.append(f"Result: {summary.get('validation_result')}")
            if summary.get("reason_code"):
                lines.append(f"Reason: {summary['reason_code']}")
        elif step["agent"] == "RoutingEngine":
            decision_label = (
                "Preview decision" if decision.get("decision_scope") == "SIMULATION_PREVIEW"
                else "Decision"
            )
            lines.append(f"{decision_label}: {decision.get('path')}")
            evidence = decision.get("evidence", {})
            if evidence.get("severity_confidence") is not None:
                lines.append(f"Severity confidence: {evidence['severity_confidence']}")
            for defect in evidence.get("defects", []):
                lines.append(
                    f"Defect {defect['defect_id']} severity gap: {defect['severity_gap']}"
                )
            lines.append("Reasons:")
            lines.extend(f"- {code}" for code in decision.get("reason_codes", []))
            lines.append(f"Human review: {'REQUIRED' if decision.get('human_review_required') else 'NOT REQUIRED'}")
            lines.append(f"Validated decision: {decision.get('validated_path')}")
        lines.append("")
    final = trace["final_decision"]
    final_label = "Final preview" if final["decision_scope"] == "SIMULATION_PREVIEW" else "Final decision"
    lines.append(f"{final_label}: {final['path']} ({final['decision_scope']})")
    lines.append(
        f"Human confirmation: {'REQUIRED' if final['human_confirmation_required'] else 'NOT REQUIRED'}"
    )
    lines.append(f"Production usable: {str(final['production_usable']).lower()}")
    lines.append("===========================================")
    return "\n".join(lines)
