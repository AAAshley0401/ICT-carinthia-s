"""Audit localization evidence for a fixed PatchCore-style checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from bottle_patchcore import SIZE, FeatureExtractor, anomaly_map
from feature_extractor_50 import RESNET18_NAME, build_extractor


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mask_metrics(score_map: np.ndarray, ground_truth: np.ndarray,
                 threshold: float) -> dict:
    truth = ground_truth > 0
    prediction = score_map > threshold
    intersection = int(np.count_nonzero(prediction & truth))
    predicted = int(np.count_nonzero(prediction))
    actual = int(np.count_nonzero(truth))
    union = predicted + actual - intersection
    return {
        "iou": intersection / union if union else 1.0,
        "recall": intersection / actual if actual else None,
        "predicted_pixels": predicted,
        "ground_truth_pixels": actual,
        "ground_truth_fraction": actual / truth.size,
        "peak_inside_ground_truth": bool(truth[np.unravel_index(score_map.argmax(), score_map.shape)]),
    }


def audit(root: Path, checkpoint_path: Path, output_path: Path) -> dict:
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if checkpoint.get("dataset_category") != root.name:
        raise ValueError("checkpoint category does not match dataset root")
    if checkpoint.get("preprocessing") != "resize_full_image_256x256_imagenet_normalize":
        raise ValueError("unsupported checkpoint preprocessing")
    expected_transform_hash = checkpoint.get("input_transform_manifest_sha256")
    if expected_transform_hash is not None:
        manifest = root / "orientation_manifest.json"
        if not manifest.is_file() or sha256(manifest) != expected_transform_hash:
            raise ValueError("input transform manifest differs from checkpoint")
    torch.set_num_threads(min(torch.get_num_threads(), 8))
    extractor = build_extractor(checkpoint.get("feature_backbone", RESNET18_NAME),
                                torch.device("cuda" if torch.cuda.is_available() else "cpu"))
    rows = []
    for category in sorted((root / "test").iterdir()):
        if not category.is_dir() or category.name == "good":
            continue
        for image_path in sorted(category.glob("*.png")):
            truth_path = root / "ground_truth" / category.name / f"{image_path.stem}_mask.png"
            if not truth_path.is_file():
                raise ValueError(f"missing ground-truth mask: {truth_path}")
            with Image.open(truth_path) as source:
                ground_truth = np.asarray(source.convert("L").resize((SIZE, SIZE),
                                             Image.Resampling.NEAREST))
            if not np.any(ground_truth):
                raise ValueError(f"empty ground-truth mask after resize: {truth_path}")
            score_map = anomaly_map(extractor.patches(image_path), checkpoint["memory"],
                                    extractor.device)
            rows.append({
                "image": str(image_path.relative_to(root)).replace("\\", "/"),
                "category": category.name,
                "image_score": float(score_map.max()),
                **mask_metrics(score_map, ground_truth, checkpoint["pixel_threshold"]),
            })
    if not rows:
        raise ValueError("no defect test images")
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["category"]].append(row)

    def summarize(items: list[dict]) -> dict:
        return {
            "count": len(items),
            "mean_iou": float(np.mean([item["iou"] for item in items])),
            "mean_recall": float(np.mean([item["recall"] for item in items])),
            "mean_ground_truth_fraction": float(np.mean(
                [item["ground_truth_fraction"] for item in items])),
            "empty_predicted_masks": sum(item["predicted_pixels"] == 0 for item in items),
            "peak_inside_ground_truth": sum(item["peak_inside_ground_truth"] for item in items),
        }

    report = {
        "dataset": "MVTec AD",
        "category": root.name,
        "checkpoint": str(checkpoint_path.resolve()),
        "checkpoint_sha256": sha256(checkpoint_path),
        "feature_backbone": checkpoint.get("feature_backbone", RESNET18_NAME),
        "input_transform_manifest_sha256": checkpoint.get("input_transform_manifest_sha256"),
        "source_sha256": sha256(Path(__file__)),
        "pixel_threshold": checkpoint["pixel_threshold"],
        "decision_scope": "EXPLORATORY_PUBLIC_DATA",
        "routing_usable": False,
        "production_usable": False,
        "overall": summarize(rows),
        "by_category": {name: summarize(items) for name, items in sorted(grouped.items())},
        "samples": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(output_path.resolve()), "overall": report["overall"],
                      "by_category": report["by_category"]}, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.root, args.checkpoint, args.output)


if __name__ == "__main__":
    main()
