"""Render an evidence panel for two frozen MVTec localization checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

from .bottle_patchcore import SIZE, FeatureExtractor, anomaly_map


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _overlay(base: Image.Image, mask: np.ndarray, color: tuple[int, int, int]) -> Image.Image:
    pixels = np.asarray(base).copy()
    pixels[mask] = (0.55 * pixels[mask] + 0.45 * np.array(color)).astype(np.uint8)
    return Image.fromarray(pixels)


def render(root: Path, sample_id: str, first: Path, second: Path, destination: Path) -> dict:
    prefix = f"{root.name}_"
    if not sample_id.startswith(prefix):
        raise ValueError("sample ID does not match dataset category")
    remainder = sample_id[len(prefix):]
    defect_type, separator, stem = remainder.rpartition("_")
    if (not separator or re.fullmatch(r"[A-Za-z0-9_]+", defect_type) is None
            or not stem.isdigit()):
        raise ValueError("sample ID must name a defect test image")
    image_path = root / "test" / defect_type / f"{stem}.png"
    truth_path = root / "ground_truth" / defect_type / f"{stem}_mask.png"
    if not image_path.is_file() or not truth_path.is_file():
        raise ValueError("image or ground-truth mask is missing")
    with Image.open(image_path) as image:
        base = image.convert("RGB").resize((SIZE, SIZE), Image.Resampling.BILINEAR)
    with Image.open(truth_path) as image:
        truth = np.asarray(image.convert("L").resize((SIZE, SIZE), Image.Resampling.NEAREST)) > 0
    checkpoints = [torch.load(path, map_location="cpu", weights_only=True) for path in (first, second)]
    if (any(checkpoint.get("dataset_category", "bottle") != root.name for checkpoint in checkpoints)
            or not torch.equal(checkpoints[0]["memory"], checkpoints[1]["memory"])):
        raise ValueError("checkpoints must share dataset category and feature memory")
    torch.set_num_threads(min(torch.get_num_threads(), 8))
    extractor = FeatureExtractor(torch.device("cuda" if torch.cuda.is_available() else "cpu"))
    score_map = anomaly_map(extractor.patches(image_path), checkpoints[0]["memory"], extractor.device)
    masks = [score_map > checkpoint["pixel_threshold"] for checkpoint in checkpoints]
    views = [base, _overlay(base, truth, (50, 230, 112)),
             _overlay(base, masks[0], (255, 84, 65)),
             _overlay(base, masks[1], (255, 173, 65))]
    labels = ["ORIGINAL", "GROUND TRUTH",
              f"PREDICTED t={checkpoints[0]['pixel_threshold']:.3f}",
              f"PREDICTED t={checkpoints[1]['pixel_threshold']:.3f}"]
    canvas = Image.new("RGB", (SIZE * 4 + 5 * 16, SIZE + 100), (15, 25, 34))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, (view, label) in enumerate(zip(views, labels)):
        x = 16 + index * (SIZE + 16)
        canvas.paste(view, (x, 48))
        draw.text((x, 21), label, fill=(229, 240, 247), font=font)
    draw.text((16, SIZE + 67),
              f"{sample_id} | MVTec AD bottle | original distance, not probability | Agent NOT RUN",
              fill=(168, 195, 210), font=font)
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination)
    return {
        "sample_id": sample_id,
        "image_sha256": _hash(image_path),
        "ground_truth_sha256": _hash(truth_path),
        "checkpoint_sha256": [_hash(first), _hash(second)],
        "predicted_pixels": [int(np.count_nonzero(mask)) for mask in masks],
        "ground_truth_pixels": int(np.count_nonzero(truth)),
        "output": str(destination.resolve()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--second", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = render(args.root, args.sample_id, args.first, args.second, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
