"""Fit a PatchCore-style checkpoint with a fixed, disjoint normal calibration set."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch

from bottle_patchcore import FeatureExtractor, anomaly_map


def select_images(root: Path, train_count: int, calibration_count: int) -> tuple[list[Path], list[Path]]:
    images = sorted((root / "train/good").glob("*.png"))
    if min(train_count, calibration_count) < 1 or len(images) < train_count + calibration_count:
        raise ValueError("need disjoint positive memory and calibration image sets")
    return images[:train_count], images[-calibration_count:]


def fit_fixed(extractor: FeatureExtractor, root: Path, model_path: Path, *,
              train_count: int, calibration_count: int = 64,
              memory_size: int = 2048, seed: int = 42,
              pixel_quantile: float = 0.995) -> dict:
    if memory_size < 1 or not 0 < pixel_quantile < 1:
        raise ValueError("memory_size must be positive and pixel_quantile must be in (0, 1)")
    memory_images, calibration_images = select_images(root, train_count, calibration_count)
    patches = torch.cat([extractor.patches(path) for path in memory_images])
    indices = torch.randperm(len(patches), generator=torch.Generator().manual_seed(seed))[:memory_size]
    memory = patches[indices].contiguous()
    maps = [anomaly_map(extractor.patches(path), memory, extractor.device)
            for path in calibration_images]
    pixel_threshold = float(np.quantile(np.concatenate([item.ravel() for item in maps]),
                                        pixel_quantile))
    image_threshold = float(np.quantile([float(item.max()) for item in maps], 0.95))
    checkpoint = {
        "model_version": f"{root.name}-patchcore-fixed-calibration-v1",
        "dataset_category": root.name,
        "memory": memory,
        "pixel_threshold": pixel_threshold,
        "image_threshold": image_threshold,
        "train_count": train_count,
        "calibration_count": calibration_count,
        "image_calibration_count": calibration_count,
        "memory_size": len(memory),
        "pixel_quantile": pixel_quantile,
        "seed": seed,
        "memory_images": [path.name for path in memory_images],
        "calibration_images": [path.name for path in calibration_images],
        "feature_backbone": "ResNet18 ImageNet1K V1 layer2+layer3",
        "preprocessing": "resize_full_image_256x256_imagenet_normalize",
        "threshold_status": "PROVISIONAL_TRAIN_NORMAL_ONLY",
    }
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
    args = parser.parse_args()
    torch.set_num_threads(min(torch.get_num_threads(), 8))
    extractor = FeatureExtractor(torch.device("cuda" if torch.cuda.is_available() else "cpu"))
    checkpoint = fit_fixed(extractor, args.root, args.model_path,
                           train_count=args.train_count,
                           calibration_count=args.calibration_count,
                           memory_size=args.memory_size)
    print({"category": args.root.name, "memory_images": checkpoint["train_count"],
           "calibration_images": checkpoint["image_calibration_count"],
           "memory_patches": checkpoint["memory_size"], "model_path": str(args.model_path)})


if __name__ == "__main__":
    main()
