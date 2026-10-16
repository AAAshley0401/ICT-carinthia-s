"""Reassemble the original Carinthia-S ZIP from checked repository chunks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def assemble(parts_dir: Path, output: Path) -> None:
    parts_dir = parts_dir.resolve(strict=True)
    output = output.resolve()
    spec = json.loads((parts_dir / "chunks.json").read_text(encoding="utf-8"))
    if spec["archive_name"] != "data.zip" or not spec["parts"]:
        raise ValueError("Unexpected chunk manifest")
    if output.exists():
        if output.stat().st_size != spec["archive_size"] or sha256(output) != spec["archive_sha256"]:
            raise ValueError(f"Existing archive differs; refusing to overwrite: {output}")
        print(f"Already verified: {output}")
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix="data.zip.", suffix=".tmp", delete=False) as dst:
            temporary = Path(dst.name)
            whole = hashlib.sha256()
            total = 0
            for index, part in enumerate(spec["parts"], start=1):
                expected_name = f"data.zip.part-{index:03d}"
                if part["name"] != expected_name:
                    raise ValueError(f"Unexpected chunk name: {part['name']}")
                part_path = parts_dir / expected_name
                if part_path.stat().st_size != part["size"]:
                    raise ValueError(f"Wrong chunk size: {expected_name}")
                part_hash = hashlib.sha256()
                with part_path.open("rb") as src:
                    for block in iter(lambda: src.read(1024 * 1024), b""):
                        dst.write(block)
                        whole.update(block)
                        part_hash.update(block)
                        total += len(block)
                if part_hash.hexdigest() != part["sha256"]:
                    raise ValueError(f"Wrong chunk SHA-256: {expected_name}")
        if total != spec["archive_size"] or whole.hexdigest() != spec["archive_sha256"]:
            raise ValueError("Reassembled ZIP hash or size does not match")
        os.replace(temporary, output)
        temporary = None
        print(f"Verified {total} bytes: {output}")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assemble(args.parts_dir, args.output)
