"""Evaluate a frozen Carinthia-S checkpoint on validation or held-out test data."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from src.carinthia_baseline import CarinthiaDataset, MultiTaskUNet
from tools.train_carinthia import evaluate, file_sha256


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--split", choices=("val", "test"), default="test")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()

    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    config = checkpoint["config"]
    manifest_sha = file_sha256(args.data / "manifest.csv")
    if manifest_sha != config["split_manifest_sha256"]:
        raise ValueError("Checkpoint was trained with a different split manifest")
    dataset = CarinthiaDataset(args.data, args.split, size=int(config["size"]))
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=False, num_workers=0)
    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    model = MultiTaskUNet(base=int(config["base"])).to(device)
    model.load_state_dict(checkpoint["state_dict"])
    metrics, predictions = evaluate(model, loader, device)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "dataset": "Carinthia-S", "split": args.split,
        "checkpoint": str(args.checkpoint.resolve()),
        "checkpoint_sha256": file_sha256(args.checkpoint),
        "checkpoint_epoch": checkpoint["epoch"],
        "manifest_sha256": manifest_sha,
        "input_size": config["size"],
        "metrics": metrics,
        "limits": [
            "The split is image-level; source metadata does not include wafer/lot identifiers.",
            "Classes 2 and 5 have one validation and one test image each.",
            "Raw softmax score is not a calibrated probability.",
        ],
    }
    (output / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "predictions.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    print(json.dumps({"split": args.split, "images": metrics["evaluated_images"],
                      "macro_f1": metrics["macro_f1"],
                      "mean_dice_positive": metrics["mean_dice_positive"],
                      "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
