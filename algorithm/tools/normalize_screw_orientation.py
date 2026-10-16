"""Build an isolated MVTec screw copy aligned by image-only object geometry."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


SIZE = 256


def rotation_degrees(image: Image.Image) -> tuple[float, float]:
    gray = np.asarray(image.convert("L"), dtype=np.uint8)
    foreground = gray < 160
    labels, count = ndimage.label(foreground)
    if count == 0:
        raise ValueError("no dark object found")
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    mask = labels == sizes.argmax()
    pixels = np.column_stack(np.nonzero(mask)).astype(np.float64)
    fraction = len(pixels) / mask.size
    if not 0.02 < fraction < 0.60:
        raise ValueError(f"implausible object area fraction: {fraction:.4f}")
    centered = pixels - pixels.mean(axis=0)
    _, _, vectors = np.linalg.svd(centered, full_matrices=False)
    axis_yx = vectors[0]
    projections = centered @ axis_yx
    perpendicular = centered @ vectors[1]
    low, high = np.quantile(projections, [0.1, 0.9])
    low_width = np.ptp(perpendicular[projections < low])
    high_width = np.ptp(perpendicular[projections > high])
    # The screw head is wider than the tip; place it at the bottom.
    if high_width < low_width:
        axis_yx = -axis_yx
    angle = -math.degrees(math.atan2(float(axis_yx[1]), float(axis_yx[0])))
    return angle, fraction


def normalize(image: Image.Image, angle: float, *, mask: bool = False) -> Image.Image:
    resized = image.convert("L" if mask else "RGB").resize(
        (SIZE, SIZE), Image.Resampling.NEAREST if mask else Image.Resampling.BILINEAR
    )
    return resized.rotate(angle, resample=Image.Resampling.NEAREST if mask else
                          Image.Resampling.BILINEAR, fillcolor=0 if mask else (230, 230, 230))


def build(root: Path, output_root: Path) -> dict:
    if root.name != "screw":
        raise ValueError("orientation normalization is defined only for screw")
    if output_root.resolve() == root.resolve():
        raise ValueError("output must be separate from the source dataset")
    records = []
    for split in ("train", "test"):
        for image_path in sorted((root / split).glob("*/*.png")):
            with Image.open(image_path) as source:
                source = source.convert("RGB")
                small = source.resize((SIZE, SIZE), Image.Resampling.BILINEAR)
                angle, fraction = rotation_degrees(small)
                aligned = normalize(source, angle)
                residual_angle, _ = rotation_degrees(aligned)
                if abs(residual_angle) > 15:
                    raise ValueError(f"failed to align screw orientation: {image_path}")
            relative = image_path.relative_to(root)
            destination = output_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            aligned.save(destination)
            if split == "test" and image_path.parent.name != "good":
                truth_path = root / "ground_truth" / image_path.parent.name / f"{image_path.stem}_mask.png"
                if not truth_path.is_file():
                    raise ValueError(f"missing ground-truth mask: {truth_path}")
                with Image.open(truth_path) as truth:
                    aligned_truth = normalize(truth, angle, mask=True)
                truth_destination = (output_root / "ground_truth" / image_path.parent.name /
                                     truth_path.name)
                truth_destination.parent.mkdir(parents=True, exist_ok=True)
                aligned_truth.save(truth_destination)
            records.append({"image": str(relative).replace("\\", "/"),
                            "rotation_degrees": angle,
                            "residual_angle_degrees": residual_angle,
                            "object_fraction": fraction})
    manifest = {"source": str(root.resolve()), "output": str(output_root.resolve()),
                "image_only_transform": True, "mask_used_to_estimate_rotation": False,
                "records": records}
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "orientation_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output_root.resolve()), "images": len(records),
                      "rotation_range": [min(row["rotation_degrees"] for row in records),
                                         max(row["rotation_degrees"] for row in records)]},
                     ensure_ascii=False))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    build(args.root, args.output_root)


if __name__ == "__main__":
    main()
