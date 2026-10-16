"""Read-only inventory of saved model outputs against the Agent input requirements.

This is an interface readiness audit, not model evaluation or probability calibration.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


REQUIRED_CAPABILITIES = (
    "calibrated_defect_probability",
    "localized_defect_type_and_confidences",
    "four_grade_severity_distribution",
    "model_and_calibration_versions",
    "image_evidence_binding",
)


def inspect_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {"kind": "invalid", "available": [], "missing": list(REQUIRED_CAPABILITIES)}

    if record.get("score_type") == "raw_nearest_patch_distance_not_probability":
        score = record.get("anomaly_score")
        if (record.get("status") != "success" or type(score) not in (int, float)
                or not math.isfinite(score) or not isinstance(record.get("predicted_mask"), str)
                or not record["predicted_mask"]):
            return {"kind": "invalid_baseline_record", "available": [],
                    "missing": list(REQUIRED_CAPABILITIES)}
        manifest = record.get("evidence_manifest")
        available = []
        if isinstance(record.get("model_version"), str) and record["model_version"]:
            available.append("model_version")
        available.append("predicted_mask")
        if isinstance(manifest, dict) and manifest.get("image_sha256") and manifest.get("mask_sha256"):
            available.append("image_and_mask_digest_fields_present")
        if isinstance(manifest, dict) and manifest.get("checkpoint_sha256") and manifest.get("preprocessing"):
            available.append("checkpoint_digest_and_preprocessing_fields_present")
        return {"kind": "raw_anomaly_baseline", "available": available,
                "missing": list(REQUIRED_CAPABILITIES)}

    # A schema-compatible payload is not enough to claim semantic calibration.
    from src.detection_validation import has_valid_shape

    sample_id = record.get("sample_id")
    if not isinstance(sample_id, str) or not has_valid_shape(record, sample_id):
        return {"kind": "invalid_agent_shape", "available": [],
                "missing": list(REQUIRED_CAPABILITIES)}
    if record.get("demo_only") is True or record.get("mode") != "model" or record.get("image_analyzed") is not True:
        return {"kind": "demo_or_unbound", "available": ["agent_schema_shape"],
                "missing": list(REQUIRED_CAPABILITIES)}
    return {
        "kind": "agent_shape_unverified",
        "available": ["agent_schema_shape"],
        "missing": ["calibration_evaluation", "four_grade_label_evaluation",
                    "image_evidence_binding_verification"],
    }


def audit(directory: Path) -> dict[str, Any]:
    if not directory.is_dir():
        raise ValueError(f"input directory does not exist: {directory}")
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ValueError(f"no JSON records found in {directory}")
    kinds: Counter[str] = Counter()
    details = []
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            assessment = inspect_record(record)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            assessment = {"kind": "unreadable", "available": [],
                          "missing": list(REQUIRED_CAPABILITIES), "error": type(exc).__name__}
        kinds[assessment["kind"]] += 1
        details.append({"file": path.name, **assessment})
    return {
        "report_version": "model-readiness/1.0",
        "scope": "interface inventory only; no model quality claim",
        "agent_routing_enabled": False,
        "record_count": len(details),
        "kinds": dict(kinds),
        "records": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="directory containing saved model JSON outputs")
    parser.add_argument("--output", type=Path, help="optional JSON report destination")
    args = parser.parse_args()
    report = audit(args.directory)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
