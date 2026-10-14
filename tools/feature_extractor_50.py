"""Optional ResNet50 feature extractor for controlled anomaly baseline experiments."""

from __future__ import annotations

from pathlib import Path

import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms
from torchvision.models import ResNet50_Weights, resnet50

from bottle_patchcore import FeatureExtractor, SIZE


RESNET18_NAME = "ResNet18 ImageNet1K V1 layer2+layer3"
RESNET50_NAME = "ResNet50 ImageNet1K V2 layer2+layer3"


class FeatureExtractor50:
    feature_backbone = RESNET50_NAME

    def __init__(self, device: torch.device) -> None:
        self.device = device
        self.network = resnet50(weights=ResNet50_Weights.IMAGENET1K_V2).to(device).eval()
        self.features: dict[str, torch.Tensor] = {}
        for name in ("layer2", "layer3"):
            getattr(self.network, name).register_forward_hook(
                lambda _module, _input, output, layer=name: self.features.__setitem__(layer, output)
            )
        self.transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
        ])

    @torch.inference_mode()
    def patches(self, path: Path) -> torch.Tensor:
        with Image.open(path) as image:
            image = image.convert("RGB").resize((SIZE, SIZE), Image.Resampling.BILINEAR)
            tensor = self.transform(image).unsqueeze(0).to(self.device)
        self.features.clear()
        self.network(tensor)
        low = F.avg_pool2d(self.features["layer2"], 3, stride=1, padding=1)
        high = F.avg_pool2d(self.features["layer3"], 3, stride=1, padding=1)
        high = F.interpolate(high, size=low.shape[-2:], mode="bilinear", align_corners=False)
        joined = torch.cat((low, high), dim=1)
        return joined.squeeze(0).permute(1, 2, 0).reshape(-1, joined.shape[1]).cpu()


def build_extractor(backbone: str, device: torch.device) -> FeatureExtractor | FeatureExtractor50:
    if backbone == RESNET18_NAME:
        return FeatureExtractor(device)
    if backbone == RESNET50_NAME:
        return FeatureExtractor50(device)
    raise ValueError(f"unsupported feature backbone: {backbone}")
