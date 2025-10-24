"""Model utilities for the cloud-segmentation backbone."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import logging

import torch
import segmentation_models_pytorch as smp


def resolve_device(preferred: Optional[str] = None) -> torch.device:
    """Pick the best available torch device, honouring a manual override."""
    if preferred:
        preferred = preferred.lower()
        if preferred in {"mps", "metal"}:
            if torch.backends.mps.is_available():
                return torch.device("mps")
            raise RuntimeError("MPS device requested but not available on this host.")
        if preferred in {"cuda", "gpu"}:
            if torch.cuda.is_available():
                return torch.device("cuda")
            raise RuntimeError("CUDA requested but no GPU is available.")
        if preferred == "cpu":
            return torch.device("cpu")
        raise ValueError(f"Unsupported device override: {preferred}")

    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def load_cloud_model(checkpoint_path: Path, device: torch.device) -> torch.nn.Module:
    """Load the UNet MobilenetV2 checkpoint."""
    logging.info("Loading cloud model from %s", checkpoint_path)
    checkpoint = torch.load(checkpoint_path, map_location=device)
    state = checkpoint.get("model_state_dict", checkpoint)
    model = smp.Unet(
        "mobilenet_v2",
        encoder_weights=None,
        in_channels=13,
        classes=4,
    ).to(device)
    cleaned = {
        k.removeprefix("module.").removeprefix("model."): v for k, v in state.items()
    }
    missing, unexpected = model.load_state_dict(cleaned, strict=False)
    if missing:
        logging.warning("Missing keys in checkpoint: %s", sorted(missing))
    if unexpected:
        logging.warning("Unexpected keys in checkpoint: %s", sorted(unexpected))
    model.eval()
    return model
