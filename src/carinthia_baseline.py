"""Small, reproducible segmentation + six-class baseline for Carinthia-S."""

from __future__ import annotations

import csv
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import nn
from torch.utils.data import Dataset


LABELS = ("1", "2", "3", "4", "5", "6")


class CarinthiaDataset(Dataset):
    def __init__(
        self, root: Path, split: str, *, size: int = 192,
        augment: bool = False, cache: bool = True,
    ) -> None:
        if split not in {"train", "val", "test"}:
            raise ValueError("split must be train, val, or test")
        if size < 32 or size % 8:
            raise ValueError("size must be >= 32 and divisible by 8")
        self.root = root.resolve(strict=True)
        self.size = size
        self.augment = augment
        with (self.root / f"{split}.csv").open(encoding="utf-8", newline="") as f:
            self.rows = list(csv.DictReader(f))
        if not self.rows or any(row["split"] != split for row in self.rows):
            raise ValueError(f"Invalid or empty {split} manifest")
        self.cache = [self._read(row) for row in self.rows] if cache else None

    def _read(self, row: dict[str, str]) -> tuple[np.ndarray, np.ndarray]:
        image = cv2.imread(str(self.root / row["image_path"]), cv2.IMREAD_GRAYSCALE)
        mask = cv2.imread(str(self.root / row["binary_mask_path"]), cv2.IMREAD_GRAYSCALE)
        if image is None or mask is None or image.shape != (480, 480) or mask.shape != image.shape:
            raise ValueError(f"Unreadable image or mask: {row['image_id']}")
        image = cv2.resize(image, (self.size, self.size), interpolation=cv2.INTER_AREA)
        mask = cv2.resize(mask, (self.size, self.size), interpolation=cv2.INTER_NEAREST)
        return image, (mask > 0).astype(np.uint8)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor, int, str]:
        row = self.rows[index]
        image, mask = self.cache[index] if self.cache is not None else self._read(row)
        if self.augment:
            if np.random.random() < 0.5:
                image, mask = np.fliplr(image), np.fliplr(mask)
            if np.random.random() < 0.5:
                image, mask = np.flipud(image), np.flipud(mask)
            turns = np.random.randint(0, 4)
            image, mask = np.rot90(image, turns), np.rot90(mask, turns)
        image_tensor = torch.from_numpy(image.copy()).float().unsqueeze(0).div_(255.0)
        mask_tensor = torch.from_numpy(mask.copy()).float().unsqueeze(0)
        return image_tensor, mask_tensor, LABELS.index(row["label"]), row["image_id"]


class DoubleConv(nn.Sequential):
    def __init__(self, channels_in: int, channels_out: int) -> None:
        super().__init__(
            nn.Conv2d(channels_in, channels_out, 3, padding=1, bias=False),
            nn.BatchNorm2d(channels_out), nn.ReLU(inplace=True),
            nn.Conv2d(channels_out, channels_out, 3, padding=1, bias=False),
            nn.BatchNorm2d(channels_out), nn.ReLU(inplace=True),
        )


class MultiTaskUNet(nn.Module):
    def __init__(self, base: int = 24, classes: int = 6) -> None:
        super().__init__()
        self.enc1 = DoubleConv(1, base)
        self.enc2 = DoubleConv(base, base * 2)
        self.enc3 = DoubleConv(base * 2, base * 4)
        self.bottleneck = DoubleConv(base * 4, base * 8)
        self.pool = nn.MaxPool2d(2)
        self.up3 = nn.ConvTranspose2d(base * 8, base * 4, 2, 2)
        self.dec3 = DoubleConv(base * 8, base * 4)
        self.up2 = nn.ConvTranspose2d(base * 4, base * 2, 2, 2)
        self.dec2 = DoubleConv(base * 4, base * 2)
        self.up1 = nn.ConvTranspose2d(base * 2, base, 2, 2)
        self.dec1 = DoubleConv(base * 2, base)
        self.mask_head = nn.Conv2d(base, 1, 1)
        self.class_head = nn.Linear(base * 8, classes)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))
        b = self.bottleneck(self.pool(e3))
        class_logits = self.class_head(b.mean(dim=(2, 3)))
        d3 = self.dec3(torch.cat([self.up3(b), e3], dim=1))
        d2 = self.dec2(torch.cat([self.up2(d3), e2], dim=1))
        d1 = self.dec1(torch.cat([self.up1(d2), e1], dim=1))
        return self.mask_head(d1), class_logits


def multitask_loss(
    mask_logits: torch.Tensor, class_logits: torch.Tensor,
    masks: torch.Tensor, labels: torch.Tensor,
) -> torch.Tensor:
    pos_weight = torch.tensor(5.0, device=mask_logits.device)
    bce = nn.functional.binary_cross_entropy_with_logits(
        mask_logits, masks, pos_weight=pos_weight,
    )
    probabilities = mask_logits.sigmoid().flatten(1)
    targets = masks.flatten(1)
    dice_loss = 1 - ((2 * (probabilities * targets).sum(1) + 1) /
                     (probabilities.sum(1) + targets.sum(1) + 1)).mean()
    classification = nn.functional.cross_entropy(class_logits, labels)
    return 0.5 * bce + 0.5 * dice_loss + 0.5 * classification
