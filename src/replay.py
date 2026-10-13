"""Replay synthetic detector contracts against the existing routing engine."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from .routing_engine import route_detection
from .task_state import InspectionTask


DEFAULT_CASES_DIR = Path(__file__).resolve().parent.parent / "test_cases"


def _base_result(sample_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "sample_id": sample_id,
        "status": "success",
        "mode": "model",
        "demo_only": False,
        "image_analyzed": True,
        "model_version": "synthetic-replay-fixture-v1",
        "calibration_version": "synthetic-calibration-v1",
        "defect_probability": 0.95,
        "defects": [{
            "defect_id": "d1",
            "defect_type": "scratch",
            "detection_confidence": 0.96,
            "class_confidence": 0.93,
            "severity": "NG",
            "severity_confidence": 0.94,
            "severity_probabilities": {
                "Acceptable": 0.01,
                "Marginal NG": 0.03,
                "NG": 0.94,
                "Gross NG": 0.02,
            },
            "bbox_xyxy": [10, 20, 30, 40],
            "mask_ref": "fixture://mask/d1",
        }],
        "error": None,
    }


def _parent_and_key(document: dict[str, Any], pointer: str) -> tuple[Any, str | int]:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"invalid JSON pointer: {pointer!r}")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    current: Any = document
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    key: str | int = int(parts[-1]) if isinstance(current, list) else parts[-1]
    return current, key


def build_result(case: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(_base_result(case["sample_id"]))
    for pointer, value in case.get("set", {}).items():
        parent, key = _parent_and_key(result, pointer)
        parent[key] = copy.deepcopy(value)
    for pointer in case.get("remove", []):
        parent, key = _parent_and_key(result, pointer)
        del parent[key]
    return result


def load_cases(cases_dir: Path = DEFAULT_CASES_DIR) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(cases_dir.glob("*_cases.json")):
        group = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(group, list):
            raise ValueError(f"{path.name} must contain a JSON array")
        for case in group:
            case_id = case["case_id"]
            if case_id in seen:
                raise ValueError(f"duplicate replay case: {case_id}")
            seen.add(case_id)
            cases.append(case)
    if not cases:
        raise ValueError(f"no replay cases in {cases_dir}")
    return cases


def replay_case(case: dict[str, Any]) -> dict[str, Any]:
    result = build_result(case)
    decision = route_detection(InspectionTask(case["sample_id"]), result)
    actual = {
        "path": decision.selected_path.value,
        "reason_codes": list(decision.reason_codes),
        "state": decision.current_state.value,
        "human_review_required": decision.human_review_required,
    }
    expected = case["expected"]
    return {
        "case_id": case["case_id"],
        "sample_id": case["sample_id"],
        "synthetic_fixture": True,
        "production_usable": False,
        "passed": actual == expected,
        "expected": expected,
        "actual": actual,
    }


def run_replay(cases_dir: Path = DEFAULT_CASES_DIR) -> dict[str, Any]:
    results = [replay_case(case) for case in load_cases(cases_dir)]
    passed = sum(result["passed"] for result in results)
    return {"total": len(results), "passed": passed, "failed": len(results) - passed, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_DIR)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    report = run_replay(args.cases_dir)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for result in report["results"]:
            label = "PASS" if result["passed"] else "FAIL"
            print(f"{label} {result['case_id']}: {result['actual']['path']} {result['actual']['reason_codes']}")
        print(f"{report['passed']}/{report['total']} replay cases passed")
    if report["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
