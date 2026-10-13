"""Run the local detector → validation → router demonstration workflow."""

from __future__ import annotations

import argparse
import json
from typing import Any

from src.agent_trace import TraceCollector, format_trace
from src.detection_validation import validate_detection_result
from src.detector_agent import DetectorAgent
from src.model_adapter import DetectorPort
from src.router_agent import RouterAgent
from src.task_state import InspectionTask


def run_inspection(
    sample_id: str, image_path: str, scenario: str = "normal", *, detector: DetectorPort | None = None
) -> dict[str, Any]:
    task = InspectionTask(sample_id)
    trace = TraceCollector(sample_id)
    detector_agent = detector if detector is not None else DetectorAgent(mode=scenario)
    detector_name = type(detector_agent).__name__
    detection_result = detector_agent.detect(sample_id, image_path)
    trace.add_step(
        detector_name,
        input_data={
            "sample_id": sample_id,
            "image_path": image_path,
            **({"scenario": scenario} if detector is None else {}),
        },
        output_data={
            "status": detection_result["status"],
            "defect_probability": detection_result["defect_probability"],
            "model_version": detection_result["model_version"],
            "demo_only": detection_result["demo_only"],
            "error": detection_result["error"],
            "defects": [
                {
                    "defect_id": defect["defect_id"],
                    "defect_type": defect["defect_type"],
                    "detection_confidence": defect["detection_confidence"],
                    "class_confidence": defect["class_confidence"],
                    "severity": defect["severity"],
                    "severity_confidence": defect["severity_confidence"],
                    "severity_probabilities": defect["severity_probabilities"],
                }
                for defect in detection_result["defects"]
            ],
        },
    )
    validation = validate_detection_result(detection_result, task.task_id)
    decision_scope = (
        "SIMULATION_PREVIEW" if detection_result["demo_only"]
        else "VALIDATED_MODEL_OUTPUT" if validation.valid
        else "REJECTED_MODEL_OUTPUT"
    )
    trace.add_step(
        "ValidationAgent",
        input_data=detection_result,
        output_data={
            "validation_result": validation.status.value,
            "reason_code": validation.reason_code,
            "demo_only": detection_result["demo_only"],
        },
    )
    actual, preview = RouterAgent().decide(task, detection_result)
    trace.add_step(
        "RoutingEngine",
        input_data={
            "detection_result": detection_result,
            "validation_result": validation.status.value,
        },
        decision_data={
            "path": preview.path.value,
            "reason_codes": list(preview.reason_codes),
            "explanation": preview.explanation,
            "human_review_required": preview.human_review_required,
            "evidence": preview.evidence,
            "validated_path": actual.selected_path.value,
            "validated_reason_codes": list(actual.reason_codes),
            "decision_scope": decision_scope,
        },
    )
    final_decision = {
        "path": preview.path.value,
        "reason_codes": list(preview.reason_codes),
        "human_review_required": preview.human_review_required,
        "human_confirmation_required": preview.path.value != "FAILED",
        "decision_scope": decision_scope,
        "production_usable": False,
        "validated_path": actual.selected_path.value,
        "validated_reason_codes": list(actual.reason_codes),
    }
    trace_output = trace.to_dict(final_decision)

    return {
        "sample_id": sample_id,
        "agent_called": [step["agent"] for step in trace_output["execution_trace"]],
        "stages": [step["agent"] for step in trace_output["execution_trace"]],
        "path": preview.path.value,
        "reason_codes": list(preview.reason_codes),
        "explanation": preview.explanation,
        "human_review_required": preview.human_review_required,
        "human_confirmation_required": preview.path.value != "FAILED",
        "recommended_action": preview.recommended_action,
        "evidence_summary": preview.evidence_summary,
        "evidence": preview.evidence,
        "decision_scope": decision_scope,
        "demo_only": detection_result["demo_only"],
        "production_usable": False,
        "validation_status": validation.status.value,
        "validated_decision": actual.to_dict(),
        "execution_trace": trace_output["execution_trace"],
        "final_decision": trace_output["final_decision"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=sorted(DetectorAgent.MODES))
    parser.add_argument("--sample-id", default="001")
    parser.add_argument("--image-path", default="data/sample.png")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args()
    if args.scenario:
        output: object = run_inspection(args.sample_id, args.image_path, args.scenario)
    else:
        output = [
            run_inspection(sample_id, args.image_path, scenario)
            for sample_id, scenario in (("001", "normal"), ("002", "boundary"), ("003", "failure"))
        ]
    if args.format == "text":
        samples = output if isinstance(output, list) else [output]
        print("\n\n".join(format_trace(sample) for sample in samples))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
