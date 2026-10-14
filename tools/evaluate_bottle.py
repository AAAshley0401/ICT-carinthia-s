"""Evaluate the frozen bottle baseline on the complete MVTec AD bottle/test split."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from bottle_patchcore import DATA_ROOT, MODEL_PATH, OUTPUT_ROOT, SIZE, FeatureExtractor, infer


def image_auc(positive: list[float], negative: list[float]) -> float:
    """Exact pairwise AUROC, including half credit for tied scores."""
    comparisons = np.subtract.outer(positive, negative)
    return float((np.count_nonzero(comparisons > 0) + 0.5 * np.count_nonzero(comparisons == 0))
                 / comparisons.size)


def evaluate(root: Path, output_root: Path, model_path: Path) -> dict:
    checkpoint = torch.load(model_path, map_location="cpu", weights_only=True)
    if not isinstance(checkpoint.get("model_version"), str) or not checkpoint["model_version"]:
        raise ValueError("checkpoint model version missing")
    if checkpoint.get("preprocessing") != "resize_full_image_256x256_imagenet_normalize":
        raise ValueError("checkpoint preprocessing mismatch")
    torch.set_num_threads(min(torch.get_num_threads(), 8))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    extractor = FeatureExtractor(device)
    categories = ("good", "broken_large", "broken_small", "contamination")
    results: list[dict] = []
    for category in categories:
        paths = sorted((root / "test" / category).glob("*.png"))
        if not paths:
            raise ValueError(f"no test images in {category}")
        for path in paths:
            result = infer(extractor, checkpoint, path, output_root, root)
            if category != "good" and result["ground_truth_mask"] is None:
                raise ValueError(f"ground-truth mask missing for {path}")
            result["category"] = category
            result["actual_anomaly"] = category != "good"
            results.append(result)

    positives = [x["anomaly_score"] for x in results if x["actual_anomaly"]]
    negatives = [x["anomaly_score"] for x in results if not x["actual_anomaly"]]
    tp = sum(x["is_anomaly"] and x["actual_anomaly"] for x in results)
    fn = sum(not x["is_anomaly"] and x["actual_anomaly"] for x in results)
    fp = sum(x["is_anomaly"] and not x["actual_anomaly"] for x in results)
    tn = sum(not x["is_anomaly"] and not x["actual_anomaly"] for x in results)
    intersection = union = normal_predicted_pixels = 0
    defect_ious: list[float] = []
    category_ious: dict[str, list[float]] = {name: [] for name in categories if name != "good"}
    for result in results:
        predicted = np.asarray(Image.open(result["predicted_mask"]).convert("L")) > 0
        if result["ground_truth_mask"]:
            with Image.open(result["ground_truth_mask"]) as image:
                actual = np.asarray(image.convert("L").resize((SIZE, SIZE), Image.Resampling.NEAREST)) > 0
            shared = int(np.count_nonzero(predicted & actual))
            combined = int(np.count_nonzero(predicted | actual))
            intersection += shared
            union += combined
            iou = shared / combined if combined else 1.0
            defect_ious.append(iou)
            category_ious[result["category"]].append(iou)
        else:
            normal_predicted_pixels += int(np.count_nonzero(predicted))

    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1],
                                         text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    report = {
        "dataset": "MVTec AD",
        "category": "bottle",
        "split": "official test",
        "dataset_license": "CC BY-NC-SA 4.0",
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": commit,
        "model_version": checkpoint["model_version"],
        "threshold_status": checkpoint["threshold_status"],
        "training": {
            "normal_memory_images": checkpoint["train_count"],
            "normal_calibration_images": checkpoint["calibration_count"],
            "memory_patches": checkpoint["memory_size"],
            "pixel_quantile": checkpoint.get("pixel_quantile", 0.995),
            "seed": checkpoint["seed"],
        },
        "thresholds": {
            "image_score": checkpoint["image_threshold"],
            "pixel_score": checkpoint["pixel_threshold"],
            "source": "normal train images only; not calibrated probabilities",
        },
        "sample_counts": {name: sum(x["category"] == name for x in results) for name in categories},
        "image_metrics": {
            "auroc": image_auc(positives, negatives),
            "lowest_defect_score": min(positives),
            "highest_normal_score": max(negatives),
            "true_positive": tp,
            "false_negative": fn,
            "false_positive": fp,
            "true_negative": tn,
            "accuracy_at_provisional_threshold": (tp + tn) / len(results),
        },
        "mask_metrics_256x256": {
            "micro_iou_defect_images": intersection / union if union else None,
            "mean_iou_defect_images": float(np.mean(defect_ious)),
            "mean_iou_by_defect_type": {name: float(np.mean(values)) for name, values in category_ious.items()},
            "normal_false_positive_pixel_fraction": normal_predicted_pixels / (len(negatives) * SIZE * SIZE),
        },
        "mean_inference_ms": float(np.mean([x["inference_ms"] for x in results])),
        "results": results,
    }
    destination = output_root / "evaluation" / f"{checkpoint['model_version']}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(destination.resolve()), "samples": len(results),
                      "image_metrics": report["image_metrics"],
                      "mask_metrics_256x256": report["mask_metrics_256x256"],
                      "mean_inference_ms": report["mean_inference_ms"]}, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DATA_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--model-path", type=Path, default=MODEL_PATH)
    args = parser.parse_args()
    evaluate(args.root, args.output_root, args.model_path)


if __name__ == "__main__":
    main()
