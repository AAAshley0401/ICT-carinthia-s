"""Evaluate frozen human-review routing on saved model predictions."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from src.carinthia_route import CarinthiaRoutePolicy, route_prediction


def evaluate(predictions: Path, *, image_size: int) -> dict[str, object]:
    with predictions.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("No predictions")
    reviewed = 0
    errors = 0
    captured_errors = 0
    reasons: Counter[str] = Counter()
    for row in rows:
        route = route_prediction(
            row["predicted_label"], float(row["class_score"]),
            int(row["predicted_mask_pixels"]) / (image_size * image_size),
        )
        is_review = bool(route["human_review_required"])
        is_error = row["true_label"] != row["predicted_label"]
        reviewed += is_review
        errors += is_error
        captured_errors += is_review and is_error
        reasons.update(route["reason_codes"])
    return {
        "policy": CarinthiaRoutePolicy().__dict__,
        "samples": len(rows),
        "review_count": reviewed,
        "review_fraction": reviewed / len(rows),
        "classification_errors": errors,
        "errors_sent_to_review": captured_errors,
        "error_capture_rate": captured_errors / errors if errors else None,
        "reason_counts": dict(sorted(reasons.items())),
        "warning": "Selected on validation data; test figures are only an independent check, not a threshold-tuning signal.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--image-size", type=int, default=128)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.predictions, image_size=args.image_size)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "samples", "review_count", "classification_errors", "errors_sent_to_review"
    )}, ensure_ascii=False))
