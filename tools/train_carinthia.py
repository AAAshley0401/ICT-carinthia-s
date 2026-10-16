"""Train an image-level class + pixel-level mask baseline on fixed Carinthia-S splits.

This is a public-data research baseline. It does not predict wafer severity grades.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, WeightedRandomSampler

from src.carinthia_baseline import LABELS, CarinthiaDataset, MultiTaskUNet, multitask_loss


ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def classification_metrics(matrix: np.ndarray) -> dict[str, object]:
    per_class = {}
    for i, label in enumerate(LABELS):
        tp = int(matrix[i, i])
        support = int(matrix[i, :].sum())
        predicted = int(matrix[:, i].sum())
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"support": support, "precision": precision, "recall": recall, "f1": f1}
    return {
        "accuracy": float(np.trace(matrix) / matrix.sum()),
        "macro_f1": float(np.mean([m["f1"] for m in per_class.values()])),
        "per_class": per_class,
        "confusion_matrix": matrix.tolist(),
    }


@torch.inference_mode()
def evaluate(
    model: MultiTaskUNet, loader: DataLoader, device: torch.device,
    *, max_batches: int | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    model.eval()
    matrix = np.zeros((len(LABELS), len(LABELS)), dtype=np.int64)
    dice_scores: list[float] = []
    iou_scores: list[float] = []
    empty_count = 0
    empty_false_positives = 0
    records: list[dict[str, object]] = []
    for batch_index, (images, masks, labels, ids) in enumerate(loader):
        if max_batches is not None and batch_index >= max_batches:
            break
        images = images.to(device)
        mask_logits, class_logits = model(images)
        class_scores = class_logits.softmax(1).cpu().numpy()
        mask_scores = mask_logits.sigmoid().cpu().numpy()[:, 0]
        true_masks = masks.numpy()[:, 0] > 0
        labels_np = labels.numpy()
        for i, image_id in enumerate(ids):
            predicted_label = int(class_scores[i].argmax())
            true_label = int(labels_np[i])
            matrix[true_label, predicted_label] += 1
            predicted_mask = mask_scores[i] >= 0.5
            truth = true_masks[i]
            intersection = int(np.logical_and(predicted_mask, truth).sum())
            predicted_pixels = int(predicted_mask.sum())
            true_pixels = int(truth.sum())
            if true_pixels:
                dice_scores.append(2 * intersection / (predicted_pixels + true_pixels)
                                   if predicted_pixels + true_pixels else 0.0)
                union = predicted_pixels + true_pixels - intersection
                iou_scores.append(intersection / union if union else 0.0)
            else:
                empty_count += 1
                empty_false_positives += int(predicted_pixels >= 50)
            records.append({
                "image_id": image_id,
                "true_label": LABELS[true_label],
                "predicted_label": LABELS[predicted_label],
                "class_score": float(class_scores[i, predicted_label]),
                "class_margin": float(np.sort(class_scores[i])[-1] - np.sort(class_scores[i])[-2]),
                "true_mask_pixels": true_pixels,
                "predicted_mask_pixels": predicted_pixels,
            })
    if not records:
        raise ValueError("Evaluation received no batches")
    metrics = classification_metrics(matrix)
    metrics.update({
        "positive_mask_images": len(dice_scores),
        "mean_dice_positive": float(np.mean(dice_scores)) if dice_scores else None,
        "mean_iou_positive": float(np.mean(iou_scores)) if iou_scores else None,
        "empty_mask_images": empty_count,
        "empty_mask_image_false_positive_rate_at_50_pixels": (
            empty_false_positives / empty_count if empty_count else None
        ),
        "mask_threshold": 0.5,
        "empty_mask_false_positive_min_pixels": 50,
        "evaluated_images": len(records),
    })
    return metrics, records


def train(args: argparse.Namespace) -> None:
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    data_root = args.data.resolve(strict=True)
    lock = json.loads((ROOT / "eval" / "split_lock.json").read_text(encoding="utf-8"))
    manifest_hash = file_sha256(data_root / "manifest.csv")
    if manifest_hash != lock["manifest_sha256"]:
        raise ValueError("Dataset manifest does not match frozen split")
    train_set = CarinthiaDataset(data_root, "train", size=args.size, augment=True)
    val_set = CarinthiaDataset(data_root, "val", size=args.size)
    counts = Counter(row["label"] for row in train_set.rows)
    weights = [counts[row["label"]] ** -0.5 for row in train_set.rows]
    sampler = WeightedRandomSampler(
        weights, num_samples=len(train_set), replacement=True,
        generator=torch.Generator().manual_seed(args.seed),
    )
    train_loader = DataLoader(train_set, batch_size=args.batch_size, sampler=sampler, num_workers=0)
    val_loader = DataLoader(val_set, batch_size=args.batch_size, shuffle=False, num_workers=0)
    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    model = MultiTaskUNet(base=args.base).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    use_amp = device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    args.output.mkdir(parents=True, exist_ok=True)
    config = {
        "dataset": "Carinthia-S", "split_manifest_sha256": manifest_hash,
        "seed": args.seed, "epochs": args.epochs, "batch_size": args.batch_size,
        "size": args.size, "base": args.base, "lr": args.lr,
        "device": str(device), "max_train_batches": args.max_train_batches,
        "labels": list(LABELS), "mask_threshold": 0.5,
        "note": "Raw softmax scores are not calibrated probabilities; do not use for automated disposition.",
    }
    (args.output / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    history = []
    best_score = float("-inf")
    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for batch_index, (images, masks, labels, _) in enumerate(train_loader):
            if args.max_train_batches is not None and batch_index >= args.max_train_batches:
                break
            images, masks, labels = images.to(device), masks.to(device), labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, enabled=use_amp):
                mask_logits, class_logits = model(images)
                loss = multitask_loss(mask_logits, class_logits, masks, labels)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            losses.append(float(loss.detach().cpu()))
        if not losses:
            raise ValueError("Training received no batches")
        metrics, predictions = evaluate(model, val_loader, device)
        score = float(metrics["macro_f1"]) + float(metrics["mean_dice_positive"] or 0.0)
        row = {"epoch": epoch, "train_loss": float(np.mean(losses)), "val": metrics}
        history.append(row)
        print(json.dumps({"epoch": epoch, "train_loss": row["train_loss"],
                          "val_macro_f1": metrics["macro_f1"],
                          "val_mean_dice": metrics["mean_dice_positive"]}, ensure_ascii=False), flush=True)
        (args.output / "history.json").write_text(
            json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if score > best_score:
            best_score = score
            torch.save({"state_dict": model.state_dict(), "config": config,
                        "epoch": epoch, "validation_metrics": metrics}, args.output / "best.pt")
            with (args.output / "val_predictions.csv").open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(predictions[0]))
                writer.writeheader()
                writer.writerows(predictions)
    print(f"Best validation score {best_score:.4f}; checkpoint: {args.output / 'best.pt'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--size", type=int, default=192)
    parser.add_argument("--base", type=int, default=24)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--max-train-batches", type=int)
    train(parser.parse_args())
