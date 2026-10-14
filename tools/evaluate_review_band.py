"""Evaluate a train-calibrated normal/review/anomaly band on one MVTec category."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

from bottle_patchcore import DATA_ROOT, FeatureExtractor, anomaly_map, infer


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def thresholds_from_normal_training(
    extractor: FeatureExtractor, checkpoint: dict, root: Path,
    low_quantile: float, high_quantile: float,
) -> tuple[float, float]:
    if not 0 < low_quantile < high_quantile < 1:
        raise ValueError("require 0 < low_quantile < high_quantile < 1")
    train_count = checkpoint["train_count"]
    count = checkpoint["image_calibration_count"]
    normal_images = sorted((root / "train/good").glob("*.png"))
    selected = normal_images[train_count:train_count + count]
    if len(selected) != count:
        raise ValueError("checkpoint requires more normal calibration images than available")
    scores = [float(anomaly_map(extractor.patches(path), checkpoint["memory"], extractor.device).max())
              for path in selected]
    low, high = (float(np.quantile(scores, quantile))
                 for quantile in (low_quantile, high_quantile))
    if low >= high:
        raise ValueError("normal calibration scores do not separate the review band")
    return low, high


def evaluate(root: Path, model_path: Path, output_root: Path,
             low_quantile: float, high_quantile: float,
             expected_image_calibration_count: int | None = None) -> dict:
    checkpoint = torch.load(model_path, map_location="cpu", weights_only=True)
    if checkpoint.get("dataset_category") != root.name:
        raise ValueError("checkpoint category does not match dataset root")
    if checkpoint.get("preprocessing") != "resize_full_image_256x256_imagenet_normalize":
        raise ValueError("unsupported checkpoint preprocessing")
    if expected_image_calibration_count is not None and (
        checkpoint.get("image_calibration_count") != expected_image_calibration_count
    ):
        raise ValueError("image calibration count differs from checkpoint; refit first")
    torch.set_num_threads(min(torch.get_num_threads(), 8))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    extractor = FeatureExtractor(device)
    low, high = thresholds_from_normal_training(
        extractor, checkpoint, root, low_quantile, high_quantile
    )
    categories = sorted(path for path in (root / "test").iterdir() if path.is_dir())
    if not any(path.name == "good" for path in categories) or len(categories) < 2:
        raise ValueError("test split needs good and at least one defect category")
    results: list[dict] = []
    for category in categories:
        images = sorted(category.glob("*.png"))
        if not images:
            raise ValueError(f"no test images in {category}")
        for image_path in images:
            result = infer(extractor, checkpoint, image_path, output_root, root)
            if category.name != "good" and result["ground_truth_mask"] is None:
                raise ValueError(f"ground-truth mask missing for {image_path}")
            score = result["anomaly_score"]
            path = "NORMAL_CANDIDATE" if score < low else (
                "ANOMALY_CANDIDATE" if score >= high else "REVIEW"
            )
            result.update({
                "actual_anomaly": category.name != "good",
                "triage_path": path,
                "human_review_required": path == "REVIEW",
                "review_band": {"low_score": low, "high_score": high},
            })
            result_path = output_root / "json" / f"{result['sample_id']}.json"
            temporary_path = result_path.with_suffix(".json.tmp")
            temporary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary_path.replace(result_path)
            results.append(result)

    observed = Counter(item["triage_path"] for item in results)
    counts = {path: observed[path] for path in (
        "NORMAL_CANDIDATE", "REVIEW", "ANOMALY_CANDIDATE"
    )}
    false_normal = sum(item["actual_anomaly"] and item["triage_path"] == "NORMAL_CANDIDATE"
                       for item in results)
    false_anomaly = sum(not item["actual_anomaly"] and item["triage_path"] == "ANOMALY_CANDIDATE"
                        for item in results)
    review_defects = sum(item["actual_anomaly"] and item["triage_path"] == "REVIEW"
                         for item in results)
    review_normals = counts["REVIEW"] - review_defects
    baseline_false_normal = sum(item["actual_anomaly"] and not item["is_anomaly"]
                                for item in results)
    baseline_false_anomaly = sum(not item["actual_anomaly"] and item["is_anomaly"]
                                 for item in results)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True,
                                         cwd=Path(__file__).resolve().parents[1],
                                         stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    report = {
        "dataset": "MVTec AD",
        "category": root.name,
        "split": "official test",
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": commit,
        "source_sha256": {
            "bottle_patchcore.py": file_sha256(Path(__file__).with_name("bottle_patchcore.py")),
            "evaluate_review_band.py": file_sha256(Path(__file__)),
        },
        "checkpoint_sha256": file_sha256(model_path),
        "model_version": checkpoint["model_version"],
        "score_type": "raw_nearest_patch_distance_not_probability",
        "calibration": {
            "normal_memory_images": checkpoint["train_count"],
            "normal_image_calibration_images": checkpoint["image_calibration_count"],
            "low_quantile": low_quantile,
            "high_quantile": high_quantile,
            "low_score": low,
            "high_score": high,
            "source": "normal training images only",
        },
        "sample_count": len(results),
        "path_counts": dict(counts),
        "review_fraction": counts["REVIEW"] / len(results),
        "false_normal_candidates": false_normal,
        "false_anomaly_candidates": false_anomaly,
        "review_defects": review_defects,
        "review_normals": review_normals,
        "forced_single_threshold": {
            "threshold": checkpoint["image_threshold"],
            "false_normal": baseline_false_normal,
            "false_anomaly": baseline_false_anomaly,
        },
        "results": results,
    }
    destination = output_root / "evaluation" / f"{root.name}_review_band.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(destination.resolve()),
                      **{key: report[key] for key in (
                          "sample_count", "path_counts", "review_fraction",
                          "false_normal_candidates", "false_anomaly_candidates",
                          "review_defects", "review_normals", "forced_single_threshold"
                      )}}, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DATA_ROOT)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--low-quantile", type=float, default=0.90)
    parser.add_argument("--high-quantile", type=float, default=0.99)
    parser.add_argument("--expect-image-calibration-count", type=int)
    args = parser.parse_args()
    evaluate(args.root, args.model_path, args.output_root,
             args.low_quantile, args.high_quantile,
             args.expect_image_calibration_count)


if __name__ == "__main__":
    main()
