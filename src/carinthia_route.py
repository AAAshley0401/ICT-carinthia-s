"""Human-review routing for Carinthia-S class and mask evidence.

Thresholds were selected on the frozen validation split. A non-review route is
only a model candidate; it is not permission to take a production action.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


LABELS = frozenset({"1", "2", "3", "4", "5", "6"})


@dataclass(frozen=True)
class CarinthiaRoutePolicy:
    version: str = "carinthia-review-v1"
    low_class_score: float = 0.90
    minority_labels: tuple[str, ...] = ("1", "2", "4", "5")
    class3_large_mask_fraction: float = 0.06
    class6_mask_conflict_fraction: float = 0.003


def route_prediction(
    predicted_label: str, class_score: float, mask_fraction: float,
    *, policy: CarinthiaRoutePolicy | None = None,
) -> dict[str, object]:
    policy = policy or CarinthiaRoutePolicy()
    if predicted_label not in LABELS:
        raise ValueError("predicted_label must be one of 1..6")
    if not all(math.isfinite(x) and 0 <= x <= 1 for x in (class_score, mask_fraction)):
        raise ValueError("class_score and mask_fraction must be finite fractions")

    reasons = []
    if class_score < policy.low_class_score:
        reasons.append("LOW_CLASS_SCORE")
    if predicted_label in policy.minority_labels:
        reasons.append("MINORITY_CLASS_REVIEW")
    if predicted_label == "3" and mask_fraction > policy.class3_large_mask_fraction:
        reasons.append("CLASS_3_LARGE_MASK")
    if predicted_label == "6" and mask_fraction >= policy.class6_mask_conflict_fraction:
        reasons.append("CLASS_6_MASK_CONFLICT")
    if predicted_label != "6" and mask_fraction == 0:
        reasons.append("DEFECT_CLASS_WITH_EMPTY_MASK")

    review = bool(reasons)
    return {
        "route": "REVIEW_REQUIRED" if review else "MODEL_CANDIDATE",
        "human_review_required": review,
        "reason_codes": reasons,
        "policy": asdict(policy),
        "evidence": {
            "predicted_label": predicted_label,
            "class_score": class_score,
            "mask_fraction": mask_fraction,
            "score_semantics": "uncalibrated_softmax_score",
        },
        "production_action_allowed": False,
    }
