"""Validate saved detector contract samples before ModelAdapter integration."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.detection_validation import validate_detection_result


def inspect(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"file": path.name, "valid": False, "reason_code": "INVALID_SCHEMA",
                "error": type(exc).__name__}
    if not isinstance(payload, dict) or not isinstance(payload.get("sample_id"), str):
        return {"file": path.name, "kind": "not_sample", "valid": False,
                "reason_code": None}
    result = validate_detection_result(payload, payload["sample_id"])
    return {"file": path.name, "sample_id": payload["sample_id"],
            "valid": result.valid, "reason_code": result.reason_code,
            "status": payload.get("status"), "demo_only": payload.get("demo_only")}


def validate_directory(directory: Path, output: Path | None = None) -> dict[str, Any]:
    if not directory.is_dir():
        raise ValueError(f"sample directory does not exist: {directory}")
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ValueError(f"no JSON samples found in {directory}")
    all_records = [inspect(path) for path in paths]
    records = [record for record in all_records if record.get("kind") != "not_sample"]
    ignored = [record for record in all_records if record.get("kind") == "not_sample"]
    reasons = Counter(record["reason_code"] or "VALID" for record in records)
    report = {
        "report_version": "model-contract-validation/1.0",
        "directory": str(directory.resolve()),
        "record_count": len(records),
        "ignored_file_count": len(ignored),
        "valid_count": sum(record["valid"] for record in records),
        "invalid_count": sum(not record["valid"] for record in records),
        "reason_counts": dict(reasons),
        "agent_routing_enabled": bool(records) and all(record["valid"] for record in records),
        "ignored_files": ignored,
        "records": records,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    validate_directory(args.directory, args.output)


if __name__ == "__main__":
    main()
