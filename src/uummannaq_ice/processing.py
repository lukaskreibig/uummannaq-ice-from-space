"""Core data-processing steps for each Sentinel-2 tile."""

from __future__ import annotations

import logging
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn.functional as fn
from PIL import Image
from scipy.ndimage import binary_closing
from torch.amp import autocast

from .config import Thresholds

BANDS = [
    "coastal",
    "blue",
    "green",
    "red",
    "rededge1",
    "rededge2",
    "rededge3",
    "nir",
    "nir08",
    "nir09",
    "cirrus",
    "swir16",
    "swir22",
]

GREEN_IDX, RED_IDX, NIR_IDX, SWIR_IDX = map(
    BANDS.index, ["green", "red", "nir", "swir16"]
)


@dataclass
class TileClassification:
    overlay: Image.Image
    panel: plt.Figure
    masks: Dict[str, np.ndarray]
    ndsi: np.ndarray
    ndwi: np.ndarray
    baseline: str
    rgb_preview: Image.Image


def build_rgb_preview(ds) -> Image.Image:
    """Generate a 512×512 RGB preview for plotting."""
    red_band, green_band, blue_band = [
        np.asarray(ds[channel][0].values, dtype=np.float32).squeeze()
        for channel in ("red", "green", "blue")
    ]
    scale = 255.0 if red_band.max() <= 1.0 else 255.0 / 10000.0
    rgb = [
        Image.fromarray(np.clip(channel * scale, 0, 255).astype(np.uint8), "L")
        for channel in (red_band, green_band, blue_band)
    ]
    return Image.merge("RGB", rgb).resize((512, 512), Image.BILINEAR)


def reflectance_cube(ds, baseline_major: int) -> np.ndarray:
    """Stack the 13 Sentinel-2 bands into a reflectance cube."""

    def toa_reflectance(band, name: str) -> np.ndarray:
        dn = band[0].values.astype(np.float32)
        refl = dn * 0.0001
        if baseline_major < 4:
            refl += 0.1
        logging.debug(
            "   %-7s baseline=%s shift=%+.3f",
            name,
            baseline_major,
            0.1 if baseline_major < 4 else 0.0,
        )
        return refl

    return np.stack([toa_reflectance(ds[band], band) for band in BANDS])


def downsample_cube(cube: np.ndarray) -> torch.Tensor:
    """Average-pool the reflectance cube to 40 m resolution."""
    tensor = torch.from_numpy(cube[None])
    height_aligned = (cube.shape[1] // 4) * 4
    width_aligned = (cube.shape[2] // 4) * 4
    pooled = fn.avg_pool2d(tensor[..., :height_aligned, :width_aligned], 4, 4).squeeze(
        0
    )
    return pooled


def make_land_mask(template: Image.Image, width: int, height: int) -> np.ndarray:
    return (
        np.array(template.resize((width, height), Image.NEAREST), dtype=np.uint8) > 127
    )


def pad32(tensor: torch.Tensor) -> torch.Tensor:
    _, h, w = tensor.shape
    return fn.pad(tensor, (0, (-w) % 32, 0, (-h) % 32))


def compute_cloud_mask(
    model: torch.nn.Module, small: torch.Tensor, device: torch.device
) -> np.ndarray:
    h4, w4 = small.shape[-2:]
    autocast_ctx = (
        autocast(device_type=device.type)
        if device.type in {"cuda", "mps"}
        else nullcontext()
    )
    with autocast_ctx, torch.no_grad():
        logits = model(pad32(small)[None].to(device))
        prob = torch.softmax(logits, 1)[0, 1].cpu().numpy()
    return binary_closing(prob[:h4, :w4] > 0.5, structure=np.ones((3, 3)))


def classify_tile(
    cube_small: torch.Tensor,
    land_mask: np.ndarray,
    thresholds: Thresholds,
    model: torch.nn.Module,
    device: torch.device,
    rgb_preview: Image.Image,
    baseline: str,
) -> TileClassification:
    s_np = cube_small.numpy()
    _, h4, w4 = s_np.shape

    nodata = s_np.sum(0) < 1e-6
    cloud = compute_cloud_mask(model, cube_small, device)
    land = land_mask

    ndsi = (s_np[GREEN_IDX] - s_np[SWIR_IDX]) / (
        s_np[GREEN_IDX] + s_np[SWIR_IDX] + 1e-6
    )
    ndwi = (s_np[GREEN_IDX] - s_np[NIR_IDX]) / (s_np[GREEN_IDX] + s_np[NIR_IDX] + 1e-6)

    ice_solid = (ndsi > thresholds.ndsi_solid) & ~cloud & ~land & ~nodata
    ice_light = (
        (ndsi > thresholds.ndsi_light)
        & (ndsi < thresholds.ndsi_solid)
        & ~cloud
        & ~land
        & ~nodata
    )
    water = (
        (ndwi > thresholds.ndwi) & ~ice_light & ~ice_solid & ~cloud & ~land & ~nodata
    )

    overlay = overlay_rgb(
        rgb_preview,
        ice_solid,
        ice_light,
        water,
        cloud,
        land,
        nodata,
    )
    panel = build_panel(rgb_preview, ice_solid, ice_light, cloud, land, overlay)

    masks = {
        "ice_solid": ice_solid,
        "ice_light": ice_light,
        "water": water,
        "cloud": cloud,
        "land": land,
        "nodata": nodata,
    }

    return TileClassification(
        overlay=overlay,
        panel=panel,
        masks=masks,
        ndsi=ndsi,
        ndwi=ndwi,
        baseline=baseline,
        rgb_preview=rgb_preview,
    )


def overlay_rgb(
    rgb: Image.Image,
    solid: np.ndarray,
    light: np.ndarray,
    water: np.ndarray,
    cloud: np.ndarray,
    land: np.ndarray,
    nodata: np.ndarray,
) -> Image.Image:
    base = rgb.convert("RGBA")
    overlay = np.zeros((*base.size[::-1], 4), np.uint8)
    layers = [
        (solid, (255, 255, 0)),
        (light & ~solid, (0, 255, 255)),
        (water, (0, 0, 255)),
        (cloud, (200, 200, 200)),
        (land, (150, 75, 0)),
        (nodata, (255, 0, 255)),
    ]
    for mask, colour in layers:
        arr = Image.fromarray((mask * 255).astype(np.uint8)).resize(
            base.size, Image.NEAREST
        )
        overlay[np.array(arr) > 127] = (*colour, 120)
    return Image.alpha_composite(base, Image.fromarray(overlay, "RGBA")).convert("RGB")


def build_panel(
    rgb_preview: Image.Image,
    ice_solid: np.ndarray,
    ice_light: np.ndarray,
    cloud: np.ndarray,
    land: np.ndarray,
    overlay: Image.Image,
) -> plt.Figure:
    fig, ax = plt.subplots(2, 3, figsize=(13, 8))
    ax[0, 0].imshow(rgb_preview)
    ax[0, 0].set_title("RGB")
    ax[0, 0].axis("off")

    ax[0, 1].imshow(preview(cloud), cmap="gray")
    ax[0, 1].set_title("Cloud")
    ax[0, 1].axis("off")

    ax[0, 2].imshow(preview(land), cmap="gray")
    ax[0, 2].set_title("Land")
    ax[0, 2].axis("off")

    ax[1, 0].imshow(preview(ice_solid), cmap="gray")
    ax[1, 0].set_title("Solid ice")
    ax[1, 0].axis("off")

    ax[1, 1].imshow(preview(ice_light), cmap="gray")
    ax[1, 1].set_title("Light ice")
    ax[1, 1].axis("off")

    ax[1, 2].imshow(overlay)
    ax[1, 2].set_title("Overlay")
    ax[1, 2].axis("off")

    fig.tight_layout()
    return fig


def preview(mask: np.ndarray) -> Image.Image:
    hi = Image.fromarray((mask * 255).astype(np.uint8), "L")
    return hi.resize((2048, 2048), Image.NEAREST).resize((512, 512), Image.BILINEAR)


def summarise_masks(
    masks: Dict[str, np.ndarray],
    ndsi: np.ndarray,
    ndwi: np.ndarray,
    nodata_threshold: float,
) -> Dict[str, float | int | str]:
    ice_solid = masks["ice_solid"]
    ice_light = masks["ice_light"]
    water = masks["water"]
    cloud = masks["cloud"]
    land = masks["land"]
    nodata = masks["nodata"]

    total = ice_solid.size
    cnt_solid = int(ice_solid.sum())
    cnt_light = int(ice_light.sum())
    cnt_water = int(water.sum())
    cnt_cloud = int(cloud.sum())
    cnt_land = int(land.sum())
    cnt_nodata = int(nodata.sum())
    occupied = ice_solid | ice_light | water | cloud | land | nodata
    unknown = int((~occupied).sum())

    def pct(count: int) -> float:
        return round(count / total, 4) if total else 0.0

    def safe_mean(arr: np.ndarray, mask: np.ndarray) -> str | float:
        return round(float(np.nanmean(arr[mask])), 4) if mask.any() else ""

    stats: Dict[str, float | int | str] = {
        "solid_px": cnt_solid,
        "light_px": cnt_light,
        "water_px": cnt_water,
        "cloud_px": cnt_cloud,
        "land_px": cnt_land,
        "nodata_px": cnt_nodata,
        "unknown_px": unknown,
        "solid_pct": pct(cnt_solid),
        "light_pct": pct(cnt_light),
        "water_pct": pct(cnt_water),
        "cloud_pct": pct(cnt_cloud),
        "land_pct": pct(cnt_land),
        "nodata_pct": pct(cnt_nodata),
        "mean_ndsi_solid": safe_mean(ndsi, ice_solid),
        "mean_ndsi_light": safe_mean(ndsi, ice_light),
        "mean_ndwi_water": safe_mean(ndwi, water),
        "edge_gap": int((cnt_nodata / total) >= nodata_threshold),
    }
    return stats


def refresh_landmask(template_path: Path) -> Image.Image:
    """Load the landmask template once upfront."""
    return Image.open(template_path).convert("L")
