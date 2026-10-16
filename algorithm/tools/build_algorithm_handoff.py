"""Summarize measured public-data baselines for the algorithm handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VARIANTS = {
    "screw_resnet18_aligned": (
        "models/screw_aligned_fixed128.pt",
        "outputs/experiments/screw_aligned_fixed128/evaluation/screw_aligned_data_review_band.json",
        "outputs/experiments/screw_aligned_localization_audit.json",
    ),
    "screw_resnet50_aligned": (
        "models/screw_aligned_resnet50_fixed128.pt",
        "outputs/experiments/screw_aligned_resnet50_fixed128/evaluation/screw_aligned_data_review_band.json",
        "outputs/experiments/screw_aligned_resnet50_localization_audit.json",
    ),
    "screw_resnet50_fine_aligned": (
        "models/screw_aligned_resnet50fine_fixed128.pt",
        "outputs/experiments/screw_aligned_resnet50fine_fixed128/evaluation/screw_aligned_data_review_band.json",
        "outputs/experiments/screw_aligned_resnet50fine_localization_audit.json",
    ),
    "capsule_resnet18": (
        "models/capsule_fixed128.pt",
        "outputs/experiments/capsule_fixed128/evaluation/capsule_review_band.json",
        "outputs/experiments/capsule_localization_audit.json",
    ),
    "capsule_resnet50": (
        "models/capsule_resnet50_fixed128.pt",
        "outputs/experiments/capsule_resnet50_fixed128/evaluation/capsule_review_band.json",
        "outputs/experiments/capsule_resnet50_localization_audit.json",
    ),
    "capsule_resnet50_fine": (
        "models/capsule_resnet50fine_fixed128.pt",
        "outputs/experiments/capsule_resnet50fine_fixed128/evaluation/capsule_review_band.json",
        "outputs/experiments/capsule_resnet50fine_localization_audit.json",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def measured_variant(paths: tuple[str, str, str]) -> dict:
    model_ref, decision_ref, localization_ref = paths
    model_path, decision_path, localization_path = (
        ROOT / model_ref, ROOT / decision_ref, ROOT / localization_ref
    )
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    localization = json.loads(localization_path.read_text(encoding="utf-8"))
    checkpoint_digest = sha256(model_path)
    if decision["checkpoint_sha256"] != checkpoint_digest:
        raise ValueError(f"decision report checkpoint mismatch: {decision_ref}")
    if localization["checkpoint_sha256"] != checkpoint_digest:
        raise ValueError(f"localization report checkpoint mismatch: {localization_ref}")
    if decision["category"] != localization["category"]:
        raise ValueError(f"category mismatch: {decision_ref}")
    decision_backbone = decision.get("feature_backbone")
    localization_backbone = localization.get("feature_backbone")
    if (decision_backbone and localization_backbone and
            decision_backbone != localization_backbone):
        raise ValueError(f"backbone mismatch: {decision_ref}")
    if decision.get("input_transform_manifest_sha256") != localization.get(
        "input_transform_manifest_sha256"
    ):
        raise ValueError(f"transform mismatch: {decision_ref}")
    if decision["routing_usable"] or localization["routing_usable"]:
        raise ValueError("public-data report incorrectly permits Agent routing")
    return {
        "category": decision["category"],
        "split": decision["split"],
        "evaluation_code_commit": decision.get("code_commit"),
        "model_version": decision["model_version"],
        "feature_backbone": decision_backbone or localization_backbone,
        "normal_memory_images": decision["calibration"]["normal_memory_images"],
        "normal_calibration_images": decision["calibration"]["normal_image_calibration_images"],
        "sample_count": decision["sample_count"],
        "defect_count": localization["overall"]["count"],
        "image_auroc": decision["image_auroc"],
        "false_normal_candidates": decision["false_normal_candidates"],
        "false_anomaly_candidates": decision["false_anomaly_candidates"],
        "review_fraction": decision["review_fraction"],
        "mean_mask_iou": localization["overall"]["mean_iou"],
        "peak_inside_ground_truth": localization["overall"]["peak_inside_ground_truth"],
        "checkpoint": model_ref,
        "checkpoint_sha256": checkpoint_digest,
        "decision_report": decision_ref,
        "decision_report_sha256": sha256(decision_path),
        "localization_report": localization_ref,
        "localization_report_sha256": sha256(localization_path),
        "input_transform_manifest_sha256": decision.get("input_transform_manifest_sha256"),
    }


def build(output_path: Path) -> dict:
    variants = {name: measured_variant(paths) for name, paths in VARIANTS.items()}
    report = {
        "version": "algorithm-handoff/1.0",
        "dataset": "MVTec AD",
        "purpose": "exploratory baseline comparison and model-owner handoff",
        "selection_caveat": "Official test images were examined during method selection; obtain an independent final evaluation before claiming generalization.",
        "score_type": "raw_nearest_patch_distance_not_probability",
        "agent_routing_enabled": False,
        "production_usable": False,
        "variants": variants,
        "next_required_evidence": [
            "target-domain authorized images and held-out evaluation split",
            "model-predicted defect classes and per-defect confidence semantics",
            "approved four-grade severity labels and independent evaluation",
            "calibrated defect probability with calibration version",
            "native normal, defect, multiple-defect, and failure outputs",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({"output": str(output_path.resolve()),
                      "variants": len(variants), "agent_routing_enabled": False},
                     ensure_ascii=False))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "algorithm/outputs/baseline_handoff_v1.json")
    args = parser.parse_args()
    build(args.output)


if __name__ == "__main__":
    main()
