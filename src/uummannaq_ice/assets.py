"""Helpers for working with packaged assets and model weights."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import cast


def package_path(*parts: str) -> Path:
    """Return a resolved path inside the package (works in editable installs)."""
    traversable = resources.files("uummannaq_ice")
    for part in parts:
        traversable = traversable.joinpath(part)
    return cast(Path, traversable)


def default_landmask_path() -> Path:
    return package_path("assets", "landmask_template.png")


def default_checkpoint_path() -> Path:
    return package_path("models", "unet_mobv2_v2.pt")
