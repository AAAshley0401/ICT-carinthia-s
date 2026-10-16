"""Real Carinthia-S image inference with bound image/mask/checkpoint evidence."""

from __future__ import annotations

import csv
import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import torch

from .carinthia_baseline import LABELS, MultiTaskUNet


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class CarinthiaPredictor:
    def __init__(
        self, data_root: Path, checkpoint_path: Path,
        artifact_root: Path, *, cpu: bool = False,
    ) -> None:
        self.data_root = data_root.resolve(strict=True)
        self.checkpoint_path = checkpoint_path.resolve(strict=True)
        self.artifact_root = artifact_root.resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        with (self.data_root / "manifest.csv").open(encoding="utf-8", newline="") as f:
            self.rows = {row["image_id"]: row for row in csv.DictReader(f)}
        checkpoint = torch.load(self.checkpoint_path, map_location="cpu", weights_only=True)
        self.config = checkpoint["config"]
        if sha256(self.data_root / "manifest.csv") != self.config["split_manifest_sha256"]:
            raise ValueError("Checkpoint and dataset split do not match")
        self.model_sha256 = sha256(self.checkpoint_path)
        self.device = torch.device("cuda" if torch.cuda.is_available() and not cpu else "cpu")
        self.model = MultiTaskUNet(base=int(self.config["base"])).to(self.device)
        self.model.load_state_dict(checkpoint["state_dict"])
        self.model.eval()
        self._lock = threading.Lock()

    def predict(self, image_id: str, case_id: str) -> dict[str, object]:
        if image_id not in self.rows:
            raise KeyError(image_id)
        if not isinstance(case_id, str) or not case_id.isalnum():
            raise ValueError("case_id must be alphanumeric")
        row = self.rows[image_id]
        image_path = self.data_root / row["image_path"]
        image_sha = sha256(image_path)
        if image_sha != row["image_sha256"]:
            raise ValueError("Image hash differs from frozen manifest")
        original = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if original is None or original.shape != (480, 480):
            raise ValueError("Unreadable or unexpected image shape")
        size = int(self.config["size"])
        resized = cv2.resize(original, (size, size), interpolation=cv2.INTER_AREA)
        tensor = torch.from_numpy(resized).float().unsqueeze(0).unsqueeze(0).div_(255).to(self.device)
        with self._lock, torch.inference_mode():
            mask_logits, class_logits = self.model(tensor)
        class_scores = class_logits.softmax(1)[0].cpu().numpy()
        mask_scores = mask_logits.sigmoid()[0, 0].cpu().numpy()
        mask_small = (mask_scores >= 0.5).astype(np.uint8)
        mask_full = cv2.resize(mask_small, (480, 480), interpolation=cv2.INTER_NEAREST) * 255
        mask_dir = self.artifact_root / "masks"
        mask_dir.mkdir(parents=True, exist_ok=True)
        mask_path = mask_dir / f"{case_id}.png"
        if mask_path.exists():
            raise FileExistsError(mask_path)
        if not cv2.imwrite(str(mask_path), mask_full):
            raise OSError(f"Failed to save predicted mask: {mask_path}")
        ys, xs = np.where(mask_full > 0)
        bbox = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1] if len(xs) else None
        index = int(class_scores.argmax())
        positive_scores = mask_scores[mask_small.astype(bool)]
        return {
            "case_id": case_id,
            "image_id": image_id,
            "image_path": str(image_path),
            "image_sha256": image_sha,
            "model_version": "carinthia-unet-" + self.model_sha256[:12],
            "model_sha256": self.model_sha256,
            "split_manifest_sha256": self.config["split_manifest_sha256"],
            "inference_timestamp": datetime.now(timezone.utc).isoformat(),
            "predicted_label": LABELS[index],
            "class_score": float(class_scores[index]),
            "class_scores": {label: float(class_scores[i]) for i, label in enumerate(LABELS)},
            "class_score_semantics": "uncalibrated_softmax_score",
            "predicted_mask_path": str(mask_path),
            "predicted_mask_sha256": sha256(mask_path),
            "mask_fraction": float(mask_small.mean()),
            "mask_mean_score_positive": float(positive_scores.mean()) if len(positive_scores) else None,
            "bbox_xyxy": bbox,
            "image_size": [480, 480],
            "model_input_size": [size, size],
            "severity": None,
        }
