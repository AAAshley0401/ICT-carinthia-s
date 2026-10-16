"""Create pending annotation records from a local image directory, without labels."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image


SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare(source: Path, destination: Path, dataset_name: str) -> dict:
    if not source.is_dir() or not dataset_name.strip():
        raise ValueError("an existing image directory and nonempty dataset name are required")
    source = source.resolve()
    destination = destination.resolve()
    if destination == source or source in destination.parents:
        raise ValueError("output directory must be outside the source image directory")
    images = sorted(path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in SUFFIXES)
    if not images:
        raise ValueError("no supported images found")
    destination.mkdir(parents=True, exist_ok=True)
    created = 0
    existing = 0
    for image_path in images:
        if source not in image_path.resolve().parents:
            raise ValueError(f"image resolves outside source directory: {image_path}")
        relative = image_path.relative_to(source).as_posix()
        sample_id = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24]
        output = destination / f"{sample_id}.json"
        image_digest = _sha256(image_path)
        if output.exists():
            saved = json.loads(output.read_text(encoding="utf-8"))
            if (not isinstance(saved, dict) or saved.get("sample_id") != sample_id
                    or saved.get("source_dataset") != dataset_name
                    or saved.get("image_ref") != relative
                    or saved.get("image_sha256") != image_digest):
                raise ValueError(f"existing annotation no longer matches source image: {output}")
            existing += 1
            continue
        with Image.open(image_path) as image:
            width, height = image.size
            image.verify()
        record = {
            "annotation_version": "1.0",
            "sample_id": sample_id,
            "source_dataset": dataset_name,
            "image_ref": relative,
            "image_sha256": image_digest,
            "image_width": width,
            "image_height": height,
            "annotation_status": "PENDING",
            "image_label": None,
            "defects": [],
            "grade_standard_version": None,
            "reviewer_ids": [],
        }
        with output.open("x", encoding="utf-8") as target:
            json.dump(record, target, ensure_ascii=False, indent=2)
            target.write("\n")
        created += 1
    return {"source_dataset": dataset_name, "image_count": len(images),
            "pending_records_created": created, "existing_records_preserved": existing,
            "output_directory": str(destination)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--dataset-name", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.destination, args.dataset_name),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
