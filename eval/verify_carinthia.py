"""Independently verify the frozen Carinthia-S dataset and evaluation split."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def verify(data_dir: Path, lock_path: Path) -> dict[str, object]:
    data_dir = data_dir.resolve(strict=True)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    audit = json.loads((data_dir / "audit.json").read_text(encoding="utf-8"))
    assert audit["source_sha256"] == lock["source_sha256"], "Wrong source archive"
    assert audit["split_seed"] == lock["split_seed"], "Wrong split seed"
    assert sha256(data_dir / "manifest.csv") == lock["manifest_sha256"], "Manifest changed"

    manifest = load_csv(data_dir / "manifest.csv")
    splits = {s: load_csv(data_dir / f"{s}.csv") for s in ("train", "val", "test")}
    assert len(manifest) == audit["total_images"], "Row count changed"
    assert {s: len(rows) for s, rows in splits.items()} == lock["split_counts"]

    manifest_by_id = {r["image_id"]: r for r in manifest}
    assert len(manifest_by_id) == len(manifest), "Duplicate image ID"
    assert len({r["image_sha256"] for r in manifest}) == len(manifest), "Duplicate image bytes"
    split_ids: list[str] = []
    for split, rows in splits.items():
        for row in rows:
            image_id = row["image_id"]
            split_ids.append(image_id)
            assert row == manifest_by_id[image_id], f"{split}: row differs for {image_id}"
            assert row["split"] == split, f"Wrong split for {image_id}"
    assert len(split_ids) == len(set(split_ids)) == len(manifest), "Overlap or missing split ID"

    class_counts: dict[str, dict[str, int]] = {}
    for split, rows in splits.items():
        class_counts[split] = dict(sorted(Counter(r["label"] for r in rows).items()))
    assert class_counts == audit["split_counts"], "Class counts changed"

    binary_errors = []
    missing = []
    image_hash_errors = []
    for row in manifest:
        paths = [data_dir / row[k] for k in
                 ("image_path", "original_mask_path", "binary_mask_path")]
        if any(not p.is_file() for p in paths):
            missing.append(row["image_id"])
            continue
        if sha256(paths[0]) != row["image_sha256"]:
            image_hash_errors.append(row["image_id"])
        with Image.open(paths[2]) as mask:
            pixels = np.asarray(mask)
            if mask.mode != "L" or mask.size != (480, 480) or np.any(
                (pixels != 0) & (pixels != 255)
            ) or int(np.count_nonzero(pixels)) != int(row["mask_nonzero_pixels"]):
                binary_errors.append(row["image_id"])
    assert not missing, f"Missing image/mask files: {missing[:5]}"
    assert not image_hash_errors, f"Image hash mismatches: {image_hash_errors[:5]}"
    assert not binary_errors, f"Invalid binary masks: {binary_errors[:5]}"

    flagged = [r["image_id"] for r in manifest
               if "class_6_nonempty_mask" in r["audit_flags"]]
    assert flagged == [lock["class_6_mask_exception"]], "Class-6 exception changed"
    return {
        "status": "verified",
        "total_images": len(manifest),
        "split_counts": lock["split_counts"],
        "class_counts": class_counts,
        "source_sha256": lock["source_sha256"],
        "manifest_sha256": lock["manifest_sha256"],
        "class_6_mask_exception": flagged,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=Path(__file__).with_name("split_lock.json"))
    args = parser.parse_args()
    print(json.dumps(verify(args.data, args.lock), ensure_ascii=False, indent=2))
