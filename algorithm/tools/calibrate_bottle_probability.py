"""Exploratory, held-out calibration of saved MVTec bottle anomaly scores.

This does not produce an Agent-ready wafer defect probability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sigmoid(value: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(value, -40.0, 40.0)))


def _fit_logistic(scores: np.ndarray, labels: np.ndarray) -> tuple[float, float, float, float]:
    center = float(scores.mean())
    scale = float(scores.std())
    if scale <= 0:
        raise ValueError("calibration scores have no variation")
    x = (scores - center) / scale
    design = np.column_stack((np.ones(len(x)), x))
    weights = np.array([math.log(labels.mean() / (1 - labels.mean())), 0.0])
    penalty = np.diag([0.0, 1.0])  # keep intercept unpenalized
    for _ in range(100):
        probabilities = _sigmoid(design @ weights)
        gradient = design.T @ (probabilities - labels) + penalty @ weights
        curvature = probabilities * (1 - probabilities)
        hessian = design.T @ (design * curvature[:, None]) + penalty
        step = np.linalg.solve(hessian, gradient)
        weights -= step
        weights[1] = max(0.0, weights[1])  # anomaly probability cannot fall as distance grows
        if float(np.max(np.abs(step))) < 1e-8:
            break
    return center, scale, float(weights[0]), float(weights[1])


def _metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict:
    clipped = np.clip(probabilities, 1e-12, 1 - 1e-12)
    brier = float(np.mean((probabilities - labels) ** 2))
    log_loss = float(-np.mean(labels * np.log(clipped) + (1 - labels) * np.log(1 - clipped)))
    ece = 0.0
    for index in range(5):
        lower, upper = index / 5, (index + 1) / 5
        selected = (probabilities >= lower) & (probabilities <= upper if index == 4 else probabilities < upper)
        if selected.any():
            ece += float(selected.mean() * abs(probabilities[selected].mean() - labels[selected].mean()))
    positives = probabilities[labels == 1]
    negatives = probabilities[labels == 0]
    auc = float(((positives[:, None] > negatives).sum() +
                 0.5 * (positives[:, None] == negatives).sum()) / (len(positives) * len(negatives)))
    return {"count": len(labels), "positive_count": int(labels.sum()),
            "brier": brier, "log_loss": log_loss, "ece_5_bins": ece, "auroc": auc}


def calibrate(source: Path, *, seed: int = 42, calibration_fraction: float = 0.6) -> dict:
    if not 0 < calibration_fraction < 1:
        raise ValueError("calibration_fraction must be between 0 and 1")
    document = json.loads(source.read_text(encoding="utf-8"))
    records = document.get("results")
    if not isinstance(records, list) or not records:
        raise ValueError("source has no result records")
    by_label: dict[bool, list[dict]] = {False: [], True: []}
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("source contains a non-object result record")
        score = record.get("anomaly_score")
        sample_id = record.get("sample_id")
        label = record.get("actual_anomaly")
        if (record.get("status") != "success" or
                record.get("score_type") != "raw_nearest_patch_distance_not_probability" or
                record.get("model_version") != document.get("model_version") or
                not isinstance(sample_id, str) or not sample_id or sample_id in seen or
                type(label) is not bool or type(score) not in (int, float) or not math.isfinite(score)):
            raise ValueError("source contains an invalid or duplicate score record")
        seen.add(sample_id)
        by_label[label].append(record)
    calibration, holdout = [], []
    for label in (False, True):
        group = sorted(by_label[label], key=lambda row: hashlib.sha256(
            f"{seed}:{row['sample_id']}".encode("utf-8")).hexdigest())
        if len(group) < 4:
            raise ValueError("at least four samples per class are required")
        count = min(len(group) - 2, max(2, round(len(group) * calibration_fraction)))
        calibration.extend(group[:count])
        holdout.extend(group[count:])
    fit_scores = np.array([row["anomaly_score"] for row in calibration], dtype=float)
    fit_labels = np.array([row["actual_anomaly"] for row in calibration], dtype=float)
    center, scale, intercept, slope = _fit_logistic(fit_scores, fit_labels)
    held_scores = np.array([row["anomaly_score"] for row in holdout], dtype=float)
    held_labels = np.array([row["actual_anomaly"] for row in holdout], dtype=float)
    held_probabilities = _sigmoid(intercept + slope * (held_scores - center) / scale)
    return {
        "report_version": "bottle-probability-pilot/1.0",
        "dataset": "MVTec AD bottle",
        "decision_scope": "EXPLORATORY_PUBLIC_DATA",
        "agent_routing_usable": False,
        "production_usable": False,
        "source_report": str(source.resolve()),
        "source_sha256": _file_sha256(source),
        "model_version": document["model_version"],
        "split": {"seed": seed, "method": "stratified deterministic sample ID hash",
                  "calibration_sample_ids": [row["sample_id"] for row in calibration],
                  "holdout_sample_ids": [row["sample_id"] for row in holdout]},
        "calibrator": {"method": "L2 logistic, nonnegative slope", "score_center": center,
                       "score_scale": scale, "intercept": intercept, "slope": slope},
        "holdout_metrics": _metrics(held_labels, held_probabilities),
        "holdout_predictions": [
            {"sample_id": row["sample_id"], "actual_anomaly": row["actual_anomaly"],
             "raw_anomaly_score": row["anomaly_score"],
             "estimated_anomaly_probability": float(probability)}
            for row, probability in zip(holdout, held_probabilities)
        ],
        "limitations": ["MVTec bottle only", "small calibration and holdout sets",
                        "same source dataset and defect families across split",
                        "no wafer domain validation", "no defect class or four-grade severity model"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="saved full MVTec bottle evaluation JSON")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    report = calibrate(args.source, seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()),
                      "calibration_count": len(report["split"]["calibration_sample_ids"]),
                      "holdout_metrics": report["holdout_metrics"],
                      "agent_routing_usable": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
