"""Inventory material for human review of real Agent integration.

Presence of files or fields never approves routing or proves platform access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def evidence_file(path: Path | None) -> dict[str, str] | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest()}


def required_file(path: Path) -> dict[str, str]:
    reference = evidence_file(path)
    if reference is None:
        raise ValueError(f"input file is missing: {path}")
    return reference


def model_gate(report: dict[str, Any]) -> tuple[bool, list[str]]:
    count, kinds = report.get("record_count"), report.get("kinds")
    if (report.get("report_version") != "model-readiness/1.0"
            or type(count) is not int or count < 1 or not isinstance(kinds, dict)
            or any(type(value) is not int or value < 0 for value in kinds.values())
            or sum(kinds.values()) != count):
        return False, ["MODEL_REPORT_INVALID"]
    if kinds != {"agent_shape_unverified": count}:
        return False, ["MODEL_OUTPUTS_NOT_AGENT_SHAPED"]
    return True, []


def annotation_gate(report: dict[str, Any]) -> tuple[bool, list[str]]:
    counts = report.get("counts")
    if (report.get("report_version") != "severity-annotation-audit/1.0"
            or not isinstance(counts, dict)
            or any(type(value) is not int or value < 0 for value in counts.values())
            or any(key not in {"ADJUDICATED", "PENDING", "INVALID"} for key in counts)):
        return False, ["ANNOTATION_REPORT_INVALID"]
    if counts.get("ADJUDICATED", 0) < 1 or counts.get("PENDING", 0) or counts.get("INVALID", 0):
        return False, ["ANNOTATIONS_INCOMPLETE_OR_INVALID"]
    return True, []


def evaluate(model_reports: list[dict[str, Any]], annotation_report: dict[str, Any] | None,
             evidence: dict[str, dict[str, str] | None]) -> dict[str, Any]:
    model_results = []
    for report in model_reports:
        present, reasons = model_gate(report)
        model_results.append({"material_present": present, "reasons": reasons,
                              "record_count": report.get("record_count"), "kinds": report.get("kinds")})
    annotation_present, annotation_reasons = (
        annotation_gate(annotation_report) if annotation_report is not None
        else (False, ["ANNOTATION_REPORT_MISSING"])
    )
    reasons = [reason for item in model_results for reason in item["reasons"]] + annotation_reasons
    if not model_results:
        reasons.append("MODEL_REPORT_MISSING")
    for key, reason in (
        ("model_evaluation", "MODEL_EVALUATION_EVIDENCE_MISSING"),
        ("business_criteria", "BUSINESS_CRITERIA_EVIDENCE_MISSING"),
        ("agentarts_access", "AGENTARTS_ACCESS_EVIDENCE_MISSING"),
    ):
        if evidence.get(key) is None:
            reasons.append(reason)
    return {
        "report_version": "agent-readiness-gate/1.1",
        "status": "BLOCKED" if reasons else "PENDING_TECHNICAL_REVIEW",
        "agent_routing_enabled": False,
        "gates": {
            "model_outputs": {"material_present": bool(model_results) and all(item["material_present"] for item in model_results),
                              "details": model_results},
            "severity_annotations": {"material_present": annotation_present, "reasons": annotation_reasons},
            "supporting_evidence": evidence,
        },
        "blocking_reasons": sorted(set(reasons)),
        "review_required": ["model calibration and independent evaluation", "four-grade business criteria and labels",
                            "image evidence binding", "actual AgentArts access and tool behavior", "routing safety"],
        "scope": "material inventory only; no quality, business approval or platform access is verified",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_reports", nargs="+", type=Path)
    parser.add_argument("--annotation-report", type=Path)
    parser.add_argument("--model-evaluation-evidence", type=Path)
    parser.add_argument("--business-criteria-evidence", type=Path)
    parser.add_argument("--agentarts-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reports = [read_json(path) for path in args.model_reports]
    annotation = read_json(args.annotation_report) if args.annotation_report else None
    evidence = {
        "model_evaluation": evidence_file(args.model_evaluation_evidence),
        "business_criteria": evidence_file(args.business_criteria_evidence),
        "agentarts_access": evidence_file(args.agentarts_evidence),
    }
    result = evaluate(reports, annotation, evidence)
    result["source_reports"] = {
        "model": [required_file(path) for path in args.model_reports],
        "severity_annotations": required_file(args.annotation_report) if args.annotation_report else None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "blocking_reasons": result["blocking_reasons"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
