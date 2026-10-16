"""Read-only audit of human severity annotations and their source images.

This checks record integrity and adjudication state. It never assigns a grade.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image


GRADES = frozenset({"Acceptable", "Marginal NG", "NG", "Gross NG"})
LABELS = frozenset({"NORMAL", "DEFECT"})
FIELDS = frozenset({
    "annotation_version", "sample_id", "source_dataset", "image_ref",
    "image_sha256", "image_width", "image_height", "annotation_status",
    "image_label", "defects", "grade_standard_version", "reviewer_ids",
})
DEFECT_FIELDS = frozenset({"defect_id", "defect_type", "bbox_xyxy", "mask_ref", "severity"})


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative_path(value: Any) -> PurePosixPath | None:
    if not isinstance(value, str) or not value or "\\" in value or any(ord(char) < 32 for char in value):
        return None
    if any(part in {"", ".", ".."} for part in value.split("/")):
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(":" in part for part in path.parts):
        return None
    return path


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def audit_record(record: Any, image_root: Path, filename: str) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return {"file": filename, "status": "INVALID", "errors": ["RECORD_NOT_OBJECT"]}
    if set(record) != FIELDS:
        errors.append("FIELDS_MISMATCH")
    if record.get("annotation_version") != "1.0":
        errors.append("ANNOTATION_VERSION_INVALID")
    sample_id = record.get("sample_id")
    if not _text(sample_id):
        errors.append("SAMPLE_ID_INVALID")
    elif filename != f"{sample_id}.json":
        errors.append("FILENAME_SAMPLE_ID_MISMATCH")
    if not _text(record.get("source_dataset")):
        errors.append("SOURCE_DATASET_INVALID")

    image_ref = _relative_path(record.get("image_ref"))
    if image_ref is None:
        errors.append("IMAGE_REF_INVALID")
    image_hash = record.get("image_sha256")
    if not isinstance(image_hash, str) or len(image_hash) != 64 or any(char not in "0123456789abcdef" for char in image_hash):
        errors.append("IMAGE_SHA256_INVALID")
    width, height = record.get("image_width"), record.get("image_height")
    if type(width) is not int or width < 1 or type(height) is not int or height < 1:
        errors.append("IMAGE_DIMENSIONS_INVALID")
    if image_ref is not None:
        try:
            image_path = image_root.joinpath(*image_ref.parts).resolve()
            if image_root not in image_path.parents or not image_path.is_file():
                errors.append("IMAGE_MISSING_OR_OUTSIDE_ROOT")
            else:
                if isinstance(image_hash, str) and len(image_hash) == 64 and _digest(image_path) != image_hash:
                    errors.append("IMAGE_SHA256_MISMATCH")
                with Image.open(image_path) as image:
                    if image.size != (width, height):
                        errors.append("IMAGE_DIMENSIONS_MISMATCH")
                    image.verify()
        except (OSError, ValueError):
            errors.append("IMAGE_UNREADABLE")

    status = record.get("annotation_status")
    label = record.get("image_label")
    defects = record.get("defects")
    standard = record.get("grade_standard_version")
    reviewers = record.get("reviewer_ids")
    if not isinstance(status, str) or status not in {"PENDING", "ADJUDICATED"}:
        errors.append("ANNOTATION_STATUS_INVALID")
    if not isinstance(defects, list):
        errors.append("DEFECTS_INVALID")
        defects = []
    if not isinstance(reviewers, list) or any(not _text(item) for item in reviewers) or len(reviewers) != len(set(item for item in reviewers if isinstance(item, str))):
        errors.append("REVIEWERS_INVALID")
        reviewers = []
    if status == "PENDING":
        if label is not None or defects or standard is not None or reviewers:
            errors.append("PENDING_HAS_LABELS")
    elif status == "ADJUDICATED":
        if not isinstance(label, str) or label not in LABELS or not _text(standard) or len(reviewers) < 2:
            errors.append("ADJUDICATION_INCOMPLETE")
        if (label == "NORMAL" and defects) or (label == "DEFECT" and not defects):
            errors.append("IMAGE_LABEL_DEFECTS_CONFLICT")

    seen_defects: set[str] = set()
    for index, defect in enumerate(defects):
        prefix = f"DEFECT_{index + 1}"
        if not isinstance(defect, dict) or set(defect) != DEFECT_FIELDS:
            errors.append(f"{prefix}_FIELDS_INVALID")
            continue
        defect_id = defect.get("defect_id")
        if not _text(defect_id) or defect_id in seen_defects:
            errors.append(f"{prefix}_ID_INVALID_OR_DUPLICATE")
        else:
            seen_defects.add(defect_id)
        severity = defect.get("severity")
        if not _text(defect.get("defect_type")) or not isinstance(severity, str) or severity not in GRADES:
            errors.append(f"{prefix}_TYPE_OR_GRADE_INVALID")
        mask_ref = defect.get("mask_ref")
        if mask_ref is not None and _relative_path(mask_ref) is None:
            errors.append(f"{prefix}_MASK_REF_INVALID")
        box = defect.get("bbox_xyxy")
        if not isinstance(box, list) or len(box) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in box):
            errors.append(f"{prefix}_BBOX_INVALID")
        elif type(width) is int and type(height) is int:
            x1, y1, x2, y2 = box
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                errors.append(f"{prefix}_BBOX_OUT_OF_BOUNDS")

    return {
        "file": filename,
        "sample_id": sample_id if isinstance(sample_id, str) else None,
        "status": "INVALID" if errors else status,
        "errors": errors,
    }


def audit(image_root: Path, annotations: Path) -> dict[str, Any]:
    image_root = image_root.resolve()
    if not image_root.is_dir() or not annotations.is_dir():
        raise ValueError("image root and annotation directory must exist")
    records = []
    image_refs: dict[str, str] = {}
    for path in sorted(annotations.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            assessment = audit_record(record, image_root, path.name)
            if isinstance(record, dict) and isinstance(record.get("image_ref"), str):
                image_ref = record["image_ref"]
                if image_ref in image_refs:
                    assessment["errors"].append("DUPLICATE_IMAGE_REF")
                    assessment["status"] = "INVALID"
                    for previous in records:
                        if previous["file"] == image_refs[image_ref]:
                            previous["errors"].append("DUPLICATE_IMAGE_REF")
                            previous["status"] = "INVALID"
                            break
                else:
                    image_refs[image_ref] = path.name
            records.append(assessment)
        except (OSError, UnicodeError, json.JSONDecodeError):
            records.append({"file": path.name, "status": "INVALID", "errors": ["JSON_UNREADABLE"]})
    if not records:
        raise ValueError("no annotation JSON files found")
    counts = Counter(item["status"] for item in records)
    return {
        "report_version": "severity-annotation-audit/1.0",
        "scope": "image and annotation integrity only; grades and business criteria are not verified",
        "counts": dict(counts),
        "structurally_adjudicated_count": counts["ADJUDICATED"],
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_root", type=Path)
    parser.add_argument("annotations", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.annotations.resolve() in args.output.resolve().parents:
        parser.error("report output must be outside the annotation directory")
    report = audit(args.image_root, args.annotations)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
