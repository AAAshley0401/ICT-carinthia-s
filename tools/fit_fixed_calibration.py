"""Fit a PatchCore-style checkpoint with a fixed, disjoint normal calibration set."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import numpy as np
import torch

from bottle_patchcore import FeatureExtractor, anomaly_map
from feature_extractor_50 import (RESNET18_NAME, RESNET50_FINE_NAME, RESNET50_NAME,
                                  build_extractor)


def select_images(root: Path, train_count: int, calibration_count: int) -> tuple[list[Path], list[Path]]:
    images = sorted((root / "train/good").glob("*.png"))
    if min(train_count, calibration_count) < 1 or len(images) < train_count + calibration_count:
        raise ValueError("need disjoint positive memory and calibration image sets")
    return images[:train_count], images[-calibration_count:]


def fit_fixed(extractor: FeatureExtractor, root: Path, model_path: Path, *,
              train_count: int, calibration_count: int = 64,
              memory_size: int = 2048, seed: int = 42,
              pixel_quantile: float = 0.995,
              patches_per_image: int = 1024) -> dict:
    if memory_size < 1 or patches_per_image < 1 or not 0 < pixel_quantile < 1:
        raise ValueError("memory_size and patches_per_image must be positive; pixel_quantile in (0, 1)")
    memory_images, calibration_images = select_images(root, train_count, calibration_count)
    generator = torch.Generator().manual_seed(seed)
    sampled = []
    for path in memory_images:
        image_patches = extractor.patches(path)
        if len(image_patches) > patches_per_image:
            selected = torch.randperm(len(image_patches), generator=generator)[:patches_per_image]
            image_patches = image_patches[selected]
        sampled.append(image_patches)
    patches = torch.cat(sampled)
    if len(patches) < memory_size:
        raise ValueError("memory_size exceeds available sampled patches")
    indices = torch.randperm(len(patches), generator=generator)[:memory_size]
    memory = patches[indices].contiguous()
    maps = [anomaly_map(extractor.patches(path), memory, extractor.device)
            for path in calibration_images]
    pixel_threshold = float(np.quantile(np.concatenate([item.ravel() for item in maps]),
                                        pixel_quantile))
    image_threshold = float(np.quantile([float(item.max()) for item in maps], 0.95))
    transform_manifest = root / "orientation_manifest.json"
    backbone = getattr(extractor, "feature_backbone", RESNET18_NAME)
    suffix = {RESNET18_NAME: "", RESNET50_NAME: "-resnet50",
              RESNET50_FINE_NAME: "-resnet50-fine"}[backbone]
    checkpoint = {
        "model_version": f"{root.name}-patchcore-fixed-calibration-v1{suffix}",
        "dataset_category": root.name,
        "memory": memory,
        "pixel_threshold": pixel_threshold,
        "image_threshold": image_threshold,
        "train_count": train_count,
        "calibration_count": calibration_count,
        "image_calibration_count": calibration_count,
        "memory_size": len(memory),
        "patches_per_image": patches_per_image,
        "pixel_quantile": pixel_quantile,
        "seed": seed,
        "memory_images": [path.name for path in memory_images],
        "calibration_images": [path.name for path in calibration_images],
        "feature_backbone": backbone,
        "preprocessing": "resize_full_image_256x256_imagenet_normalize",
        "threshold_status": "PROVISIONAL_TRAIN_NORMAL_ONLY",
    }
    if transform_manifest.is_file():
        checkpoint["input_transform_manifest_sha256"] = hashlib.sha256(
            transform_manifest.read_bytes()).hexdigest()
    model_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(checkpoint, model_path)
    return checkpoint


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--train-count", type=int, required=True)
    parser.add_argument("--calibration-count", type=int, default=64)
    parser.add_argument("--memory-size", type=int, default=2048)
    parser.add_argument("--backbone", choices=("resnet18", "resnet50", "resnet50fine"),
                        default="resnet18")
    parser.add_argument("--patches-per-image", type=int, default=1024)
    args = parser.parse_args()
    torch.set_num_threads(min(torch.get_num_threads(), 8))
    backbone = {"resnet18": RESNET18_NAME, "resnet50": RESNET50_NAME,
                "resnet50fine": RESNET50_FINE_NAME}[args.backbone]
    extractor = build_extractor(backbone,
                                torch.device("cuda" if torch.cuda.is_available() else "cpu"))
    checkpoint = fit_fixed(extractor, args.root, args.model_path,
                           train_count=args.train_count,
                           calibration_count=args.calibration_count,
                           memory_size=args.memory_size,
                           patches_per_image=args.patches_per_image)
    print({"category": args.root.name, "memory_images": checkpoint["train_count"],
           "calibration_images": checkpoint["image_calibration_count"],
           "memory_patches": checkpoint["memory_size"], "model_path": str(args.model_path)})


if __name__ == "__main__":
    main()
