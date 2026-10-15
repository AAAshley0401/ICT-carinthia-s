"""Recompute MVTec localization failures from a frozen checkpoint and test images."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from .bottle_patchcore import SIZE, FeatureExtractor, anomaly_map


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evaluate(root: Path, checkpoint_path: Path) -> dict:
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if (checkpoint.get("dataset_category", "bottle") != root.name or
            checkpoint.get("preprocessing") != "resize_full_image_256x256_imagenet_normalize"):
        raise ValueError("checkpoint does not match dataset category or preprocessing")
    threshold = checkpoint.get("pixel_threshold")
    if type(threshold) not in (float, int) or not np.isfinite(threshold):
        raise ValueError("checkpoint pixel threshold is invalid")
    torch.set_num_threads(min(torch.get_num_threads(), 8))
    extractor = FeatureExtractor(torch.device("cuda" if torch.cuda.is_available() else "cpu"))
    rows = []
    normal_predicted_pixels = 0
    normal_count = 0
    for category in sorted((root / "test").iterdir()):
        if not category.is_dir():
            continue
        for image_path in sorted(category.glob("*.png")):
            if category.name == "good":
                score_map = anomaly_map(extractor.patches(image_path), checkpoint["memory"],
                                        extractor.device)
                normal_predicted_pixels += int(np.count_nonzero(score_map > threshold))
                normal_count += 1
                continue
            truth_path = root / "ground_truth" / category.name / f"{image_path.stem}_mask.png"
            if not truth_path.is_file():
                raise ValueError(f"missing ground-truth mask: {truth_path}")
            with Image.open(truth_path) as image:
                truth = np.asarray(image.convert("L").resize(
                    (SIZE, SIZE), Image.Resampling.NEAREST)) > 0
            if not np.any(truth):
                raise ValueError(f"empty ground-truth mask: {truth_path}")
            score_map = anomaly_map(extractor.patches(image_path), checkpoint["memory"],
                                    extractor.device)
            predicted = score_map > threshold
            overlap = int(np.count_nonzero(predicted & truth))
            pred_count = int(np.count_nonzero(predicted))
            truth_count = int(np.count_nonzero(truth))
            union = pred_count + truth_count - overlap
            rows.append({
                "sample_id": f"{root.name}_{category.name}_{image_path.stem}",
                "defect_type": category.name,
                "image_ref": image_path.relative_to(root).as_posix(),
                "image_score": float(score_map.max()),
                "iou": overlap / union if union else 1.0,
                "pixel_precision": overlap / pred_count if pred_count else None,
                "pixel_recall": overlap / truth_count,
                "predicted_pixels": pred_count,
                "ground_truth_pixels": truth_count,
                "ground_truth_fraction": truth_count / truth.size,
                "peak_inside_ground_truth": bool(truth[np.unravel_index(score_map.argmax(), score_map.shape)]),
            })
    if not rows:
        raise ValueError("no defect test images")
    if not normal_count:
        raise ValueError("no normal test images")
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["defect_type"]].append(row)

    def summarize(items: list[dict]) -> dict:
        return {
            "count": len(items),
            "mean_iou": float(np.mean([item["iou"] for item in items])),
            "median_iou": float(np.median([item["iou"] for item in items])),
            "mean_pixel_recall": float(np.mean([item["pixel_recall"] for item in items])),
            "empty_predicted_masks": sum(item["predicted_pixels"] == 0 for item in items),
            "peak_inside_ground_truth": sum(item["peak_inside_ground_truth"] for item in items),
        }

    return {
        "report_version": "localization-failures/1.0",
        "dataset": "MVTec AD",
        "category": root.name,
        "split": "official test",
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "checkpoint_sha256": _sha256(checkpoint_path),
        "checkpoint_model_version": checkpoint["model_version"],
        "pixel_threshold": float(threshold),
        "decision_scope": "EXPLORATORY_PUBLIC_DATA",
        "agent_routing_usable": False,
        "production_usable": False,
        "overall": summarize(rows),
        "normal_test": {"count": normal_count,
                        "false_positive_pixel_fraction": normal_predicted_pixels / (normal_count * SIZE * SIZE)},
        "by_defect_type": {key: summarize(value) for key, value in sorted(grouped.items())},
        "worst_10_iou": sorted(rows, key=lambda row: (row["iou"], row["sample_id"]))[:10],
        "samples": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.root, args.checkpoint)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "overall": report["overall"],
                      "normal_test": report["normal_test"],
                      "by_defect_type": report["by_defect_type"],
                      "worst_3_iou": report["worst_10_iou"][:3]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
