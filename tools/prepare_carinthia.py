"""Prepare the Carinthia-S archive and a fixed, image-level evaluation split.

Usage:
    python scripts/prepare_carinthia.py --archive PATH_TO_DATA_ZIP --output OUTPUT_DIR

The source archive is never modified. Existing output files are checked before
writing so that a previous run cannot silently mix with another archive/seed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from PIL import Image


OFFICIAL_MD5 = "3a41242574635cf1302fab15accb7730"
FIELDS = [
    "image_id", "label", "split", "image_path", "original_mask_path",
    "binary_mask_path", "image_sha256", "original_mask_sha256",
    "width", "height", "original_mask_mode", "mask_nonzero_pixels",
    "mask_fraction", "mask_has_intermediate_values", "audit_flags",
]


def digest_file(path: Path, algorithm: str) -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def write_bytes_checked(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Existing output differs; choose another output directory: {path}")
    else:
        path.write_bytes(data)


def write_csv_checked(path: Path, rows: list[dict[str, object]]) -> None:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    write_bytes_checked(path, output.getvalue().encode("utf-8"))


def prepare(archive: Path, output: Path, seed: int) -> None:
    archive = archive.resolve(strict=True)
    output = output.resolve()
    if not archive.is_file() or archive.suffix.lower() != ".zip":
        raise ValueError(f"Expected a ZIP archive: {archive}")
    source_md5 = digest_file(archive, "md5")
    if source_md5 != OFFICIAL_MD5:
        raise ValueError(f"Unexpected archive MD5: {source_md5}; expected {OFFICIAL_MD5}")

    records: list[dict[str, object]] = []
    modes: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    image_hashes: dict[str, str] = {}
    image_ids: set[str] = set()
    intermediate_count = 0
    empty_count = 0
    nonempty_class6: list[str] = []

    with ZipFile(archive) as source:
        bad_member = source.testzip()
        if bad_member:
            raise ValueError(f"ZIP CRC failure: {bad_member}")
        source_csv = source.read("data/carinthia-s.csv")
        write_bytes_checked(output / "source_labels.csv", source_csv)
        reader = csv.DictReader(io.StringIO(source_csv.decode("utf-8-sig")), delimiter=";")
        if reader.fieldnames != ["image_path", "mask_path", "filename", "label"]:
            raise ValueError(f"Unexpected source columns: {reader.fieldnames}")

        for source_row in reader:
            image_id = source_row["filename"]
            label = source_row["label"]
            if not re.fullmatch(r"[0-9a-f]{32}", image_id):
                raise ValueError(f"Invalid image ID: {image_id}")
            if image_id in image_ids:
                raise ValueError(f"Repeated image ID: {image_id}")
            image_ids.add(image_id)
            if label not in {"1", "2", "3", "4", "5", "6"}:
                raise ValueError(f"Unexpected label: {label}")
            if source_row["image_path"] != f"images/{image_id}.jpg":
                raise ValueError(f"Unexpected image path for {image_id}")
            if source_row["mask_path"] != f"masks/{image_id}.png":
                raise ValueError(f"Unexpected mask path for {image_id}")

            image_data = source.read(f"data/images/{image_id}.jpg")
            mask_data = source.read(f"data/masks/{image_id}.png")
            image_sha = hashlib.sha256(image_data).hexdigest()
            if image_sha in image_hashes:
                raise ValueError(
                    f"Duplicate image pixels/files may leak across splits: "
                    f"{image_hashes[image_sha]}, {image_id}"
                )
            image_hashes[image_sha] = image_id

            with Image.open(io.BytesIO(image_data)) as image:
                width, height = image.size
                if image.mode != "L" or (width, height) != (480, 480):
                    raise ValueError(f"Unexpected image format for {image_id}")
            with Image.open(io.BytesIO(mask_data)) as mask:
                mask_mode = mask.mode
                if mask.size != (width, height):
                    raise ValueError(f"Mask size differs from image: {image_id}")
                # Alpha in two original RGBA masks is fully opaque; the colour
                # channels contain the actual annotation signal.
                grey = np.asarray(mask.convert("L"))
                nonzero = int(np.count_nonzero(grey))
                has_intermediate = bool(np.any((grey > 0) & (grey < 255)))
                binary = Image.fromarray(np.where(grey > 0, 255, 0).astype(np.uint8), "L")
                buffer = io.BytesIO()
                binary.save(buffer, format="PNG")
                binary_data = buffer.getvalue()

            image_rel = f"images/{image_id}.jpg"
            original_mask_rel = f"masks_original/{image_id}.png"
            binary_mask_rel = f"masks_binary/{image_id}.png"
            write_bytes_checked(output / image_rel, image_data)
            write_bytes_checked(output / original_mask_rel, mask_data)
            write_bytes_checked(output / binary_mask_rel, binary_data)

            flags = []
            if label == "6" and nonzero:
                flags.append("class_6_nonempty_mask")
                nonempty_class6.append(image_id)
            if mask_mode != "L":
                flags.append("original_mask_non_grayscale")
            if has_intermediate:
                flags.append("original_mask_has_intermediate_values")
                intermediate_count += 1
            if not nonzero:
                empty_count += 1
            labels[label] += 1
            modes[mask_mode] += 1
            records.append({
                "image_id": image_id,
                "label": label,
                "split": "",
                "image_path": image_rel,
                "original_mask_path": original_mask_rel,
                "binary_mask_path": binary_mask_rel,
                "image_sha256": image_sha,
                "original_mask_sha256": hashlib.sha256(mask_data).hexdigest(),
                "width": width,
                "height": height,
                "original_mask_mode": mask_mode,
                "mask_nonzero_pixels": nonzero,
                "mask_fraction": f"{nonzero / (width * height):.8f}",
                "mask_has_intermediate_values": int(has_intermediate),
                "audit_flags": "|".join(flags),
            })

    if len(records) != 4591:
        raise ValueError(f"Unexpected source row count: {len(records)}")

    by_label: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        by_label[str(record["label"])].append(record)
    for label, group in by_label.items():
        group.sort(key=lambda row: hashlib.sha256(
            f"{seed}:{row['image_id']}".encode("ascii")
        ).hexdigest())
        n = len(group)
        if n < 3:
            raise ValueError(f"Class {label} has too few cases for three splits")
        n_test = max(1, round(n * 0.15))
        n_val = max(1, round(n * 0.15))
        if n - n_test - n_val < 1:
            raise ValueError(f"Class {label} has no training cases")
        for record in group[:n_test]:
            record["split"] = "test"
        for record in group[n_test:n_test + n_val]:
            record["split"] = "val"
        for record in group[n_test + n_val:]:
            record["split"] = "train"

    records.sort(key=lambda row: str(row["image_id"]))
    write_csv_checked(output / "manifest.csv", records)
    for split in ("train", "val", "test"):
        write_csv_checked(output / f"{split}.csv", [r for r in records if r["split"] == split])

    split_counts = {
        split: dict(sorted(Counter(str(r["label"]) for r in records
                                   if r["split"] == split).items()))
        for split in ("train", "val", "test")
    }
    audit = {
        "dataset": "Carinthia-S",
        "source_archive": str(archive),
        "source_md5": source_md5,
        "source_sha256": digest_file(archive, "sha256"),
        "source_url": "https://zenodo.org/records/16895427",
        "split_unit": "image",
        "split_seed": seed,
        "split_rule": "Within each class, sort by SHA256(seed:image_id); first round(15%) test, next round(15%) val, rest train; minimum one val and test image per class.",
        "total_images": len(records),
        "image_size": [480, 480],
        "image_mode": "L",
        "label_counts": dict(sorted(labels.items())),
        "split_counts": split_counts,
        "original_mask_modes": dict(sorted(modes.items())),
        "empty_masks": empty_count,
        "original_masks_with_intermediate_values": intermediate_count,
        "duplicate_image_hashes": 0,
        "missing_image_mask_pairs": 0,
        "class_6_nonempty_masks": nonempty_class6,
        "binary_mask_rule": "Convert original mask to grayscale L; nonzero -> 255, zero -> 0. Original masks are retained.",
        "limitations": [
            "No wafer/lot/group identifier exists in source metadata; split is image-level only.",
            "Classes 2 and 5 have only one validation and one test image each; their individual metrics have high uncertainty.",
            "One class-6 image has a nonempty original mask; it is flagged, not altered or removed.",
        ],
    }
    write_bytes_checked(output / "audit.json", (
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8"))
    print(json.dumps({
        "output": str(output),
        "total": len(records),
        "labels": audit["label_counts"],
        "splits": {key: sum(value.values()) for key, value in split_counts.items()},
        "class_6_nonempty_masks": nonempty_class6,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261016)
    args = parser.parse_args()
    prepare(args.archive, args.output, args.seed)
