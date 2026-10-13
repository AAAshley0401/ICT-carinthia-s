"""Run the local detector → validation → router demonstration workflow."""

from __future__ import annotations

import argparse
import json
from typing import Any

from src.detection_validation import validate_detection_result
from src.detector_agent import DetectorAgent
from src.router_agent import RouterAgent
from src.task_state import InspectionTask


def run_inspection(sample_id: str, image_path: str, scenario: str) -> dict[str, Any]:
    task = InspectionTask(sample_id)
    detection_result = DetectorAgent(mode=scenario).detect(sample_id, image_path)
    validation = validate_detection_result(detection_result, task.task_id)
    actual, preview = RouterAgent().decide(task, detection_result)

    return {
        "sample_id": sample_id,
        "agent_called": ["DetectorAgent", "RouterAgent"],
        "stages": ["DetectorAgent", "DetectionValidation", "RouterAgent"],
        "path": preview.selected_path.value,
        "reason_codes": list(preview.reason_codes),
        "explanation": preview.explanation,
        "human_review_required": preview.human_review_required,
        "human_confirmation_required": preview.selected_path.value != "FAILED",
        "decision_scope": "SIMULATION_PREVIEW",
        "demo_only": detection_result["demo_only"],
        "production_usable": False,
        "validation_status": validation.status.value,
        "validated_decision": actual.to_dict(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=sorted(DetectorAgent.MODES))
    parser.add_argument("--sample-id", default="001")
    parser.add_argument("--image-path", default="data/sample.png")
    args = parser.parse_args()
    if args.scenario:
        output: object = run_inspection(args.sample_id, args.image_path, args.scenario)
    else:
        output = [
            run_inspection(sample_id, args.image_path, scenario)
            for sample_id, scenario in (("001", "normal"), ("002", "boundary"), ("003", "failure"))
        ]
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
