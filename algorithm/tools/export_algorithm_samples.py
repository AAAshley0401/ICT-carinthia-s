"""Export three measured bottle baseline examples without claiming Agent-ready evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch

from bottle_patchcore import DATA_ROOT, MODEL_PATH, PROJECT_ROOT, FeatureExtractor, infer


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_path(path: str | None) -> str | None:
    if path is None:
        return None
    return str(Path(path).resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")


def export(root: Path, model_path: Path, output_dir: Path) -> dict[str, Path]:
    checkpoint_digest = sha256(model_path)
    checkpoint = torch.load(model_path, map_location="cpu", weights_only=True)
    if sha256(model_path) != checkpoint_digest:
        raise ValueError("checkpoint changed while loading")
    if checkpoint.get("dataset_category", "bottle") != "bottle" or root.name != "bottle":
        raise ValueError("this export is defined for the bottle baseline only")
    if checkpoint.get("preprocessing") != "resize_full_image_256x256_imagenet_normalize":
        raise ValueError("unsupported checkpoint preprocessing")
    torch.set_num_threads(min(torch.get_num_threads(), 8))
    extractor = FeatureExtractor(torch.device("cuda" if torch.cuda.is_available() else "cpu"))
    examples = {
        "normal_sample": root / "test/good/000.png",
        "defect_sample": root / "test/broken_large/000.png",
    }
    destination = {}
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, image_path in examples.items():
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        result = infer(extractor, checkpoint, image_path, PROJECT_ROOT / "outputs", root,
                       checkpoint_sha256=checkpoint_digest, include_ground_truth=True)
        for field in ("image_path", "predicted_mask", "ground_truth_mask", "visualization"):
            result[field] = relative_path(result[field])
        result.update({
            "image_sha256": sha256(image_path),
            "predicted_mask_sha256": sha256(PROJECT_ROOT / result["predicted_mask"]),
            "model_checkpoint_sha256": checkpoint_digest,
            "decision_scope": "EXPLORATORY_PUBLIC_DATA",
            "production_usable": False,
            "routing_usable": False,
            "unavailable_evidence": ["calibrated_defect_probability", "defect_classification",
                                     "four_level_severity"],
        })
        target = output_dir / f"{name}.json"
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        destination[name] = target

    missing = root / "test/good/does_not_exist.png"
    try:
        infer(extractor, checkpoint, missing, PROJECT_ROOT / "outputs", root)
    except FileNotFoundError:
        failure = {
            "sample_id": "bottle_missing_image",
            "image_path": relative_path(str(missing)),
            "status": "failed",
            "anomaly_score": None,
            "predicted_mask": None,
            "model_version": checkpoint["model_version"],
            "model_checkpoint_sha256": checkpoint_digest,
            "decision_scope": "EXPLORATORY_PUBLIC_DATA",
            "production_usable": False,
            "routing_usable": False,
            "error": {"code": "IMAGE_NOT_FOUND", "message": "image file does not exist"},
        }
    else:
        raise AssertionError("missing image unexpectedly produced a result")
    target = output_dir / "failed_sample.json"
    target.write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
    destination["failed_sample"] = target
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DATA_ROOT)
    parser.add_argument("--model-path", type=Path, default=MODEL_PATH)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "algorithm/outputs")
    args = parser.parse_args()
    print(json.dumps({name: str(path.resolve()) for name, path in
                      export(args.root, args.model_path, args.output_dir).items()},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
