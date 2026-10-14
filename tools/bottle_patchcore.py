"""Small PatchCore-style nearest-neighbor baseline for an MVTec AD category."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms
from torchvision.models import ResNet18_Weights, resnet18


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data/raw/mvtec_anomaly_detection/bottle"
OUTPUT_ROOT = PROJECT_ROOT / "outputs"
MODEL_PATH = PROJECT_ROOT / "models/bottle_patchcore_v1.pt"
SIZE = 256
MODEL_VERSION = "bottle-patchcore-style-resnet18-v1"


class FeatureExtractor:
    def __init__(self, device: torch.device) -> None:
        self.device = device
        self.network = resnet18(weights=ResNet18_Weights.IMAGENET1K_V1).to(device).eval()
        self.features: dict[str, torch.Tensor] = {}
        for name in ("layer2", "layer3"):
            getattr(self.network, name).register_forward_hook(
                lambda _module, _input, output, layer=name: self.features.__setitem__(layer, output)
            )
        # Preserve the full image so the patch map aligns with MVTec masks.
        self.transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
        ])

    @torch.inference_mode()
    def patches(self, path: Path) -> torch.Tensor:
        with Image.open(path) as image:
            image = image.convert("RGB").resize((SIZE, SIZE), Image.Resampling.BILINEAR)
            tensor = self.transform(image).unsqueeze(0).to(self.device)
        self.features.clear()
        self.network(tensor)
        low = F.avg_pool2d(self.features["layer2"], 3, stride=1, padding=1)
        high = F.avg_pool2d(self.features["layer3"], 3, stride=1, padding=1)
        high = F.interpolate(high, size=low.shape[-2:], mode="bilinear", align_corners=False)
        joined = torch.cat((low, high), dim=1)
        return joined.squeeze(0).permute(1, 2, 0).reshape(-1, joined.shape[1]).cpu()


def anomaly_map(patches: torch.Tensor, memory: torch.Tensor, device: torch.device) -> np.ndarray:
    memory = memory.to(device)
    nearest: list[torch.Tensor] = []
    for batch in patches.split(256):
        distances = torch.cdist(batch.to(device).unsqueeze(0), memory.unsqueeze(0)).squeeze(0)
        nearest.append(distances.min(dim=1).values.cpu())
    side = int(len(patches) ** 0.5)
    low_res = torch.cat(nearest).reshape(1, 1, side, side)
    full = F.interpolate(low_res, size=(SIZE, SIZE), mode="bilinear", align_corners=False)
    return full.squeeze().numpy()


def fit(extractor: FeatureExtractor, root: Path, model_path: Path, *, train_count: int,
        calibration_count: int, memory_size: int, pixel_quantile: float = 0.995,
        model_version: str = MODEL_VERSION) -> dict:
    normal_images = sorted((root / "train/good").glob("*.png"))
    if len(normal_images) < train_count + calibration_count:
        raise ValueError("not enough train/good images for the selected fit and calibration counts")
    if min(train_count, calibration_count, memory_size) < 1:
        raise ValueError("train_count, calibration_count, and memory_size must be positive")
    if not 0 < pixel_quantile < 1:
        raise ValueError("pixel_quantile must be between 0 and 1")
    generator = torch.Generator().manual_seed(42)
    # Both memory and provisional thresholds use normal training images only.
    memory_patches = torch.cat([extractor.patches(path) for path in normal_images[:train_count]])
    chosen = torch.randperm(len(memory_patches), generator=generator)[:memory_size]
    memory = memory_patches[chosen].contiguous()
    calibration_maps = [
        anomaly_map(extractor.patches(path), memory, extractor.device)
        for path in normal_images[train_count:train_count + calibration_count]
    ]
    pixel_threshold = float(np.quantile(np.concatenate([x.ravel() for x in calibration_maps]), pixel_quantile))
    image_threshold = float(np.quantile([float(x.max()) for x in calibration_maps], 0.95))
    checkpoint = {
        "model_version": model_version,
        "dataset_category": root.name,
        "memory": memory,
        "pixel_threshold": pixel_threshold,
        "image_threshold": image_threshold,
        "train_count": train_count,
        "calibration_count": calibration_count,
        "memory_size": len(memory),
        "pixel_quantile": pixel_quantile,
        "seed": 42,
        "feature_backbone": "ResNet18 ImageNet1K V1 layer2+layer3",
        "preprocessing": "resize_full_image_256x256_imagenet_normalize",
        "threshold_status": "PROVISIONAL_TRAIN_NORMAL_ONLY",
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(checkpoint, model_path)
    return checkpoint


def infer(extractor: FeatureExtractor, checkpoint: dict, image_path: Path,
          output_root: Path, root: Path) -> dict:
    started = time.perf_counter()
    if not image_path.is_file():
        raise FileNotFoundError(image_path)
    relative = image_path.resolve().relative_to(root.resolve())
    if checkpoint.get("dataset_category", "bottle") != root.name:
        raise ValueError("checkpoint category does not match dataset root")
    if (len(relative.parts) != 3 or relative.parts[0] != "test"
            or not (root / "test" / relative.parts[1]).is_dir()):
        raise ValueError("image must be in a test subdirectory of the dataset category")
    sample_id = f"{root.name}_{relative.parts[1]}_{image_path.stem}"
    score_map = anomaly_map(extractor.patches(image_path), checkpoint["memory"], extractor.device)
    anomaly_score = float(score_map.max())
    binary_mask = (score_map > checkpoint["pixel_threshold"]).astype(np.uint8) * 255
    output_root.mkdir(parents=True, exist_ok=True)
    for part in ("json", "masks", "visualization"):
        (output_root / part).mkdir(exist_ok=True)
    mask_path = output_root / "masks" / f"{sample_id}.png"
    Image.fromarray(binary_mask).save(mask_path)
    with Image.open(image_path) as source:
        original = source.convert("RGB").resize((SIZE, SIZE), Image.Resampling.BILINEAR)
    overlay = np.asarray(original).copy()
    overlay[binary_mask > 0] = (
        0.55 * overlay[binary_mask > 0] + 0.45 * np.array([255, 0, 0])
    ).astype(np.uint8)
    ground_truth_path = None
    if relative.parts[1] != "good":
        candidate = root / "ground_truth" / relative.parts[1] / f"{image_path.stem}_mask.png"
        if candidate.is_file():
            ground_truth_path = candidate
    if ground_truth_path:
        with Image.open(ground_truth_path) as ground_truth:
            gt = ground_truth.convert("L").resize((SIZE, SIZE), Image.Resampling.NEAREST)
        gt_view = Image.fromarray(np.repeat(np.asarray(gt)[:, :, None], 3, axis=2))
    else:
        gt_view = Image.new("RGB", (SIZE, SIZE))
    canvas = Image.new("RGB", (SIZE * 3, SIZE))
    for index, part in enumerate((original, Image.fromarray(overlay), gt_view)):
        canvas.paste(part, (index * SIZE, 0))
    visualization_path = output_root / "visualization" / f"{sample_id}.png"
    canvas.save(visualization_path)
    result = {
        "sample_id": sample_id,
        "image_path": str(image_path.resolve()),
        "status": "success",
        "anomaly_score": anomaly_score,
        "score_type": "raw_nearest_patch_distance_not_probability",
        "is_anomaly": anomaly_score > checkpoint["image_threshold"],
        "image_threshold": checkpoint["image_threshold"],
        "predicted_mask": str(mask_path.resolve()),
        "mask_threshold": checkpoint["pixel_threshold"],
        "ground_truth_mask": str(ground_truth_path.resolve()) if ground_truth_path else None,
        "visualization": str(visualization_path.resolve()),
        "model_version": checkpoint["model_version"],
        "threshold_status": checkpoint["threshold_status"],
        "inference_ms": round((time.perf_counter() - started) * 1000, 2),
        "error": None,
    }
    result_path = output_root / "json" / f"{sample_id}.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DATA_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--model-path", type=Path, default=MODEL_PATH)
    parser.add_argument("--train-count", type=int, default=32)
    parser.add_argument("--calibration-count", type=int, default=8)
    parser.add_argument("--memory-size", type=int, default=2048)
    parser.add_argument("--pixel-quantile", type=float, default=0.995)
    parser.add_argument("--model-version", default=MODEL_VERSION)
    parser.add_argument("--refit", action="store_true")
    parser.add_argument("images", nargs="*", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(min(torch.get_num_threads(), 8))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    extractor = FeatureExtractor(device)
    if args.refit or not args.model_path.is_file():
        checkpoint = fit(extractor, args.root, args.model_path,
                         train_count=args.train_count, calibration_count=args.calibration_count,
                         memory_size=args.memory_size, pixel_quantile=args.pixel_quantile,
                         model_version=args.model_version)
    else:
        checkpoint = torch.load(args.model_path, map_location="cpu", weights_only=True)
        if (checkpoint.get("model_version") != args.model_version or
                checkpoint.get("preprocessing") != "resize_full_image_256x256_imagenet_normalize"):
            raise ValueError("checkpoint version does not match this baseline")
    defect_dirs = sorted(path for path in (args.root / "test").iterdir()
                         if path.is_dir() and path.name != "good")
    images = args.images or [
        next(iter(sorted((args.root / "test/good").glob("*.png")))),
        next(iter(sorted(defect_dirs[0].glob("*.png")))),
    ]
    for path in images:
        try:
            result = infer(extractor, checkpoint, path, args.output_root, args.root)
        except (FileNotFoundError, OSError, ValueError) as exc:
            result = {
                "sample_id": path.stem,
                "image_path": str(path),
                "status": "failed",
                "anomaly_score": None,
                "predicted_mask": None,
                "model_version": checkpoint["model_version"],
                "error": {"code": "IMAGE_NOT_FOUND" if isinstance(exc, FileNotFoundError)
                          else "INVALID_IMAGE", "message": str(exc)},
            }
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
