"""Check the local MVTec AD bottle layout and test-mask pairing."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data/raw/mvtec_anomaly_detection/bottle"


def images(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.png")) if directory.is_dir() else []


def check(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    errors: list[str] = []
    test_root = root / "test"
    defect_dirs = (sorted(path for path in test_root.iterdir()
                          if path.is_dir() and path.name != "good")
                   if test_root.is_dir() else [])
    if not defect_dirs:
        errors.append("missing defect test directories")
    for relative in ("train/good", "test/good", *(f"test/{path.name}" for path in defect_dirs)):
        paths = images(root / relative)
        counts[relative] = len(paths)
        if not paths:
            errors.append(f"missing PNG images: {relative}")
        for path in paths:
            try:
                with Image.open(path) as image:
                    image.verify()
            except Exception as exc:
                errors.append(f"unreadable image {path}: {exc}")

    for defect_dir in defect_dirs:
        defect = defect_dir.name
        masks = images(root / "ground_truth" / defect)
        counts[f"ground_truth/{defect}"] = len(masks)
        expected = {f"{path.stem}_mask.png" for path in images(defect_dir)}
        actual = {path.name for path in masks}
        for name in sorted(expected - actual):
            errors.append(f"missing mask: {defect}/{name}")
        for name in sorted(actual - expected):
            errors.append(f"orphan mask: {defect}/{name}")
        for image_path in images(defect_dir):
            mask_path = root / "ground_truth" / defect / f"{image_path.stem}_mask.png"
            if not mask_path.is_file():
                continue
            try:
                with Image.open(image_path) as image, Image.open(mask_path) as mask:
                    if image.size != mask.size:
                        errors.append(f"size mismatch: {defect}/{image_path.name}")
                    mask.verify()
            except Exception as exc:
                errors.append(f"unreadable pair {defect}/{image_path.name}: {exc}")
    print("Dataset: bottle")
    for name, count in counts.items():
        print(f"{name}: {count} images" if "ground_truth" not in name else f"{name}: {count} masks")
    if errors:
        raise ValueError("Dataset check failed:\n" + "\n".join(errors))
    print("Check: PASS")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    check(args.root)


if __name__ == "__main__":
    main()
