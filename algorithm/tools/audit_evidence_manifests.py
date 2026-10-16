"""Audit saved baseline evidence manifests against a fixed experiment directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(root: Path, image_root: Path, checkpoint: Path) -> dict[str, Any]:
    records_dir = root / "json"
    masks_dir = root / "masks"
    if not records_dir.is_dir() or not masks_dir.is_dir() or not checkpoint.is_file():
        raise ValueError("experiment json, masks and checkpoint must exist")
    checkpoint_digest = sha256(checkpoint)
    outcomes: list[dict[str, Any]] = []
    for record_path in sorted(records_dir.glob("bottle_*.json")):
        errors: list[str] = []
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            sample_id = record.get("sample_id")
            manifest = record.get("evidence_manifest")
            image_path = Path(record.get("image_path", ""))
            mask_path = Path(record.get("predicted_mask", ""))
            match = re.fullmatch(r"bottle_(good|broken_large|broken_small|contamination)_([0-9]+)", sample_id or "")
            if not isinstance(sample_id, str) or record_path.stem != sample_id or match is None:
                errors.append("SAMPLE_ID_MISMATCH")
            if record.get("status") != "success":
                errors.append("RECORD_NOT_SUCCESS")
            if not isinstance(manifest, dict):
                errors.append("MANIFEST_MISSING")
            else:
                for key in ("image_sha256", "mask_sha256", "checkpoint_sha256"):
                    if not isinstance(manifest.get(key), str) or re.fullmatch(r"[0-9a-f]{64}", manifest[key]) is None:
                        errors.append(f"{key.upper()}_INVALID")
                if manifest.get("preprocessing") != "resize_full_image_256x256_imagenet_normalize":
                    errors.append("PREPROCESSING_INVALID")
                expected_image = image_root / "test" / match.group(1) / f"{match.group(2)}.png"
                if image_path.resolve() != expected_image.resolve():
                    errors.append("IMAGE_PATH_UNEXPECTED")
                expected_mask = (masks_dir / f"{sample_id}.png").resolve()
                if mask_path.resolve() != expected_mask:
                    errors.append("MASK_PATH_UNEXPECTED")
                if not errors:
                    if sha256(image_path) != manifest["image_sha256"]:
                        errors.append("IMAGE_DIGEST_MISMATCH")
                    if sha256(mask_path) != manifest["mask_sha256"]:
                        errors.append("MASK_DIGEST_MISMATCH")
                    if manifest["checkpoint_sha256"] != checkpoint_digest:
                        errors.append("CHECKPOINT_DIGEST_MISMATCH")
                    with Image.open(mask_path) as mask:
                        if mask.size != (256, 256):
                            errors.append("MASK_SIZE_INVALID")
        except (OSError, ValueError, TypeError, json.JSONDecodeError, AttributeError, IndexError):
            errors.append("RECORD_UNREADABLE")
            sample_id = None
        outcomes.append({"file": record_path.name, "sample_id": sample_id, "status": "INVALID" if errors else "CONTENT_MATCH", "errors": errors})
    if not outcomes:
        raise ValueError("no baseline records found")
    counts = Counter(item["status"] for item in outcomes)
    return {"report_version": "baseline-evidence-audit/1.0", "scope": "manifest and file integrity only; no model quality or Agent decision claim", "record_count": len(outcomes), "counts": dict(counts), "checkpoint_sha256": checkpoint_digest, "records": outcomes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment_root", type=Path)
    parser.add_argument("image_root", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.experiment_root.resolve(), args.image_root.resolve(), args.checkpoint.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(args.output.resolve()), "record_count": report["record_count"], "counts": report["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
