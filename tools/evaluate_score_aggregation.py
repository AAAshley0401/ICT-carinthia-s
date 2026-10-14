"""Compare image scores from one fixed anomaly map without changing the detector."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

from bottle_patchcore import FeatureExtractor, anomaly_map


METHODS = ("max", "top_0.1pct", "top_1pct", "top_5pct")
FRACTIONS = {"top_0.1pct": 0.001, "top_1pct": 0.01, "top_5pct": 0.05}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_scores(score_map: np.ndarray) -> dict[str, float]:
    pixels = score_map.ravel()
    scores = {"max": float(pixels.max())}
    for method, fraction in FRACTIONS.items():
        count = max(1, round(len(pixels) * fraction))
        scores[method] = float(np.partition(pixels, -count)[-count:].mean())
    return scores


def auroc(rows: list[dict], method: str) -> float:
    positive = np.array([row["scores"][method] for row in rows if row["actual_anomaly"]])
    negative = np.array([row["scores"][method] for row in rows if not row["actual_anomaly"]])
    if not len(positive) or not len(negative):
        raise ValueError("AUROC requires both good and defect test images")
    differences = positive[:, None] - negative
    return float((np.count_nonzero(differences > 0) +
                  0.5 * np.count_nonzero(differences == 0)) / differences.size)


def evaluate(root: Path, checkpoint_path: Path, output_path: Path,
             low_quantile: float = 0.90, high_quantile: float = 0.99) -> dict:
    if not 0 < low_quantile < high_quantile < 1:
        raise ValueError("require 0 < low_quantile < high_quantile < 1")
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if checkpoint.get("dataset_category") != root.name:
        raise ValueError("checkpoint category does not match dataset root")
    if checkpoint.get("preprocessing") != "resize_full_image_256x256_imagenet_normalize":
        raise ValueError("unsupported checkpoint preprocessing")
    names = checkpoint.get("calibration_images")
    memory_names = checkpoint.get("memory_images")
    if not isinstance(names, list) or not isinstance(memory_names, list):
        raise ValueError("requires a fixed-calibration checkpoint with explicit image lists")
    if len(names) != checkpoint.get("image_calibration_count") or len(set(names)) != len(names):
        raise ValueError("invalid calibration image list")
    if set(names).intersection(memory_names):
        raise ValueError("memory and calibration images overlap")
    train_dir = root / "train/good"
    calibration_paths = [train_dir / name for name in names]
    if any(path.name != name or not path.is_file() for path, name in zip(calibration_paths, names)):
        raise ValueError("calibration image missing or invalid")

    torch.set_num_threads(min(torch.get_num_threads(), 8))
    extractor = FeatureExtractor(torch.device("cuda" if torch.cuda.is_available() else "cpu"))

    def score(path: Path) -> dict[str, float]:
        return image_scores(anomaly_map(extractor.patches(path), checkpoint["memory"],
                                        extractor.device))

    calibration = [score(path) for path in calibration_paths]
    thresholds = {
        method: {
            "low": float(np.quantile([row[method] for row in calibration], low_quantile)),
            "high": float(np.quantile([row[method] for row in calibration], high_quantile)),
        }
        for method in METHODS
    }
    rows = []
    for category_dir in sorted((root / "test").iterdir()):
        if not category_dir.is_dir():
            continue
        for image_path in sorted(category_dir.glob("*.png")):
            rows.append({
                "image": str(image_path.relative_to(root)).replace("\\", "/"),
                "category": category_dir.name,
                "actual_anomaly": category_dir.name != "good",
                "scores": score(image_path),
            })
    if not rows:
        raise ValueError("no test images")

    metrics = {}
    for method in METHODS:
        low, high = thresholds[method]["low"], thresholds[method]["high"]
        if low >= high:
            raise ValueError(f"calibration scores do not separate review band: {method}")
        paths = ["NORMAL_CANDIDATE" if row["scores"][method] < low else
                 "ANOMALY_CANDIDATE" if row["scores"][method] >= high else "REVIEW"
                 for row in rows]
        counts = Counter(paths)
        by_defect = defaultdict(lambda: Counter())
        for row, path in zip(rows, paths):
            by_defect[row["category"]][path] += 1
        metrics[method] = {
            "image_auroc": auroc(rows, method),
            "thresholds": thresholds[method],
            "path_counts": {path: counts[path] for path in
                            ("NORMAL_CANDIDATE", "REVIEW", "ANOMALY_CANDIDATE")},
            "false_normal_candidates": sum(row["actual_anomaly"] and path == "NORMAL_CANDIDATE"
                                           for row, path in zip(rows, paths)),
            "false_anomaly_candidates": sum(not row["actual_anomaly"] and path == "ANOMALY_CANDIDATE"
                                            for row, path in zip(rows, paths)),
            "by_category": {name: dict(counts) for name, counts in sorted(by_defect.items())},
        }
    report = {
        "dataset": "MVTec AD",
        "category": root.name,
        "split": "official test",
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "checkpoint_sha256": sha256(checkpoint_path),
        "source_sha256": sha256(Path(__file__)),
        "memory_images": len(memory_names),
        "calibration_images": names,
        "sample_count": len(rows),
        "score_type": "raw_nearest_patch_distance_not_probability",
        "decision_scope": "EXPLORATORY_PUBLIC_DATA",
        "routing_usable": False,
        "production_usable": False,
        "metrics": metrics,
        "samples": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(output_path.resolve()), "category": root.name,
                      "memory_images": len(memory_names),
                      "metrics": {name: {key: value for key, value in metric.items()
                                         if key in ("image_auroc", "path_counts",
                                                    "false_normal_candidates", "false_anomaly_candidates")}
                                  for name, metric in metrics.items()}},
                     ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.root, args.checkpoint, args.output)


if __name__ == "__main__":
    main()
