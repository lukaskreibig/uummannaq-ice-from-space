"""Core data-processing steps for each Sentinel-2 tile."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn.functional as fn
from PIL import Image
from scipy.ndimage import binary_closing

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


# The preview is 512 square because that is what six matplotlib panels want. A
# viewer wants the opposite: the sensor's own detail, so a reader can see the
# 40 m decision grid sitting on top of a 10 m photograph and judge for
# themselves how coarse the judgement is. Capped so one scene stays a few
# hundred kilobytes rather than a few megabytes.
EXPORT_RGB_MAX_EDGE = 1600


def export_rgb(ds, max_edge: int = EXPORT_RGB_MAX_EDGE) -> Image.Image:
    """True colour at close to native resolution, for the scene viewer."""
    red_band, green_band, blue_band = [
        np.asarray(ds[channel][0].values, dtype=np.float32).squeeze()
        for channel in ("red", "green", "blue")
    ]
    scale = 255.0 if red_band.max() <= 1.0 else 255.0 / 10000.0
    rgb = Image.merge(
        "RGB",
        [
            Image.fromarray(np.clip(channel * scale, 0, 255).astype(np.uint8), "L")
            for channel in (red_band, green_band, blue_band)
        ],
    )
    longest = max(rgb.size)
    if longest > max_edge:
        ratio = max_edge / longest
        rgb = rgb.resize(
            (round(rgb.width * ratio), round(rgb.height * ratio)), Image.LANCZOS
        )
    return rgb


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


# Radiometric offset introduced with Sentinel-2 processing baseline 04.00,
# operational since 25 January 2022. From then on L1C digital numbers carry
# RADIO_ADD_OFFSET = -1000, so the documented conversion is
#     reflectance = (DN + RADIO_ADD_OFFSET) / QUANTIFICATION_VALUE
# that is DN/10000 - 0.1. Before 04.00 it is simply DN/10000.
#
# This used to be implemented with the sign the other way round: nothing was
# subtracted for baseline 4 and later, and +0.1 was ADDED to everything older.
# Both eras therefore came out 0.1 above true reflectance. The series stayed
# internally consistent, with no step at the 2022 boundary, which is why it went
# unnoticed, but every NDSI and NDWI value was compressed toward zero, and the
# void detector below silently stopped working for the older era.
RADIO_ADD_OFFSET_BASELINE = 4
RADIO_ADD_OFFSET_REFLECTANCE = 0.1
QUANTIFICATION_VALUE = 10000.0


def void_reflectance(baseline_major: int) -> float:
    """Per-band reflectance of a DN = 0 pixel, which ESA defines as NO_DATA."""
    if baseline_major >= RADIO_ADD_OFFSET_BASELINE:
        return -RADIO_ADD_OFFSET_REFLECTANCE
    return 0.0


def reflectance_cube(ds, baseline_major: int) -> np.ndarray:
    """Stack the 13 Sentinel-2 bands into a reflectance cube."""
    shift = (
        -RADIO_ADD_OFFSET_REFLECTANCE
        if baseline_major >= RADIO_ADD_OFFSET_BASELINE
        else 0.0
    )

    def toa_reflectance(band, name: str) -> np.ndarray:
        dn = band[0].values.astype(np.float32)
        refl = dn / QUANTIFICATION_VALUE + shift
        logging.debug(
            "   %-7s baseline=%s shift=%+.3f",
            name,
            baseline_major,
            shift,
        )
        return refl

    return np.stack([toa_reflectance(ds[band], band) for band in BANDS])


def downsample_cube(cube: np.ndarray) -> torch.Tensor:
    """Average-pool the reflectance cube to 40 m resolution."""
    tensor = torch.from_numpy(cube[None])
    height_aligned = (cube.shape[1] // 4) * 4
    width_aligned = (cube.shape[2] // 4) * 4
    if height_aligned == 0 or width_aligned == 0:
        return tensor.squeeze(0)
    pooled = fn.avg_pool2d(tensor[..., :height_aligned, :width_aligned], 4, 4).squeeze(
        0
    )
    return pooled


def make_land_mask(template: Image.Image, width: int, height: int) -> np.ndarray:
    """Resize a painted template onto a grid.

    DEPRECATED, and kept only so an old run configuration still works. This
    covers the same FRACTION of the frame rather than the same geography: it
    masked exactly 9.00 percent of every scene regardless of grid size, and 9.9
    percent of the cells it called land looked like open water when checked
    against a summer scene. It also masks about twice as much as the island
    actually occupies; the mask derived from imagery comes out at 5.1 percent.

    Use land_mask_from_raster with assets/landmask.tif instead.
    """
    return (
        np.array(template.resize((width, height), Image.NEAREST), dtype=np.uint8) > 127
    )


def land_mask_from_raster(
    raster_path: Path, geobox, width: int, height: int
) -> np.ndarray:
    """Reproject a georeferenced land mask onto the analysis grid.

    The mask is a GeoTIFF carrying its own CRS and transform, derived from the
    imagery by scripts/derive_landmask.py: land is what stays bright in the near
    infrared across eight clear summer scenes, since open water is nearly black
    there and drifting ice cannot hold a pixel across four years.

    Reprojecting rather than resizing is the whole point. It puts the mask on the
    same ground it was derived from no matter what grid the scene arrives on, and
    the two tiles over this fjord produce grids that differ by 12 percent.

    Enclosed inland water counts as land, deliberately. Uummannaq has lakes and
    ponds, they are dark in the near infrared like the sea, and ice on them is
    lake ice. Measured, that is 4032 cells in 80 patches, the largest 0.12 km².
    The published series is a sea-ice measurement, so they are excluded.
    """
    import rasterio
    from affine import Affine as _Affine
    from rasterio.warp import Resampling, reproject

    with rasterio.open(raster_path) as src:
        source = src.read(1)
        source_crs = src.crs
        source_transform = src.transform

    # The geobox describes the 10 m grid the scene arrived on, but classification
    # happens on the 4x4 average-pooled 40 m grid. Pooling keeps the origin and
    # multiplies the pixel size, so the destination transform has to be scaled to
    # match, or the mask lands in the top-left corner of the frame. That failure
    # is quiet: it produced a land share of 0.0001 instead of 0.05, and every
    # number downstream still looked plausible.
    pool = max(1, round(geobox.width / width)) if width else 1
    dst_transform = geobox.transform * _Affine.scale(pool, pool)

    destination = np.zeros((height, width), dtype=np.uint8)
    reproject(
        source=source,
        destination=destination,
        src_transform=source_transform,
        src_crs=source_crs,
        dst_transform=dst_transform,
        dst_crs=geobox.crs.to_wkt(),
        resampling=Resampling.nearest,
    )
    return destination > 127


def pad32(tensor: torch.Tensor) -> torch.Tensor:
    _, h, w = tensor.shape
    return fn.pad(tensor, (0, (-w) % 32, 0, (-h) % 32))


# A scene has to show enough of the fjord before its number means anything.
# Measured on the published archive: 318 of 1552 scenes report more than 80
# percent cloud, and they enter the daily series with a mean reported ice
# fraction of 0.014. Those are pictures of cloud, not measurements of ice.
#
# The threshold is deliberately generous. It is not a quality judgement, it only
# separates "this scene saw the fjord" from "this scene saw the weather".
# Override with UUMMANNAQ_MIN_CLEAR_SHARE for a sensitivity run.
MIN_CLEAR_SHARE = float(os.getenv("UUMMANNAQ_MIN_CLEAR_SHARE", "0.30"))

# Smallest band sum for which a normalised difference still means something.
# Below it the ratio is dominated by noise and can leave [-1, 1] entirely.
INDEX_DENOMINATOR_FLOOR = 0.02

# CloudSEN12 label set, which the checkpoint was trained on.
#
# KNOWN LIMITATION, and it is currently the largest single error source in this
# pipeline. The model does not reliably find cloud over this fjord. On
# 2023-08-18 ESA reports 48.4 percent for the tile and the model finds 22.6
# percent over the AOI with the fjord visibly overcast; on 2019-08-08 ESA reports
# 22.4 percent and the model finds 50.4 percent. The error is not one-directional
# so it cannot be calibrated away with an offset. The thin-cloud and shadow
# classes almost never win the argmax (0.2 and 0.0 percent on 2023-08-18), so the
# four-class head effectively behaves as a two-class one.
#
# Physical supplements were tried and rejected: the cirrus band B10 adds
# essentially nothing here, and a brightness/whiteness test flags 27.8 percent of
# April FAST ICE as cloud, because ice and cloud are both white and bright. That
# is the fundamental difficulty of optical cloud detection over ice.
#
# What follows from that: the ice fraction correlates with detected cloud at
# r = -0.42 across the published archive, and Sentinel-1 radar, which sees
# through cloud, is the only practical way to bound this error rather than
# guess at it.
CLOUD_CLASS_CLEAR = 0
CLOUD_CLASS_THICK = 1
CLOUD_CLASS_THIN = 2
CLOUD_CLASS_SHADOW = 3


def compute_cloud_mask(
    model: torch.nn.Module, small: torch.Tensor, device: torch.device
) -> np.ndarray:
    """Mask everything the cloud model does not consider clear sky.

    This used to take softmax(...)[0, 1], a single channel of a four class head,
    so only THICK cloud was ever masked. Thin cloud and cloud shadow were left
    in, and over a summer fjord that is most of what there is. The consequence
    was measured on the published archive: the reported ice fraction correlates
    with cloud cover at r = -0.42, and in February and March the days reporting
    almost no ice have a median cloud cover of 0.72 while the rest have 0.00. On
    2023-08-18 ESA reports 48.4 percent cloud for the tile and the single channel
    version found 19.5 percent over the AOI, with the fjord visibly overcast.

    Taking the argmax over all four classes and masking every non-clear one is
    what the label set is for.

    Inference runs in full precision on every device. autocast used to be enabled
    for cuda and mps only, and since the probability is then hard thresholded,
    the same scene produced masks differing on about 1.9 percent of cells between
    CPU and MPS. A published series must not depend on which machine produced it.
    """
    h4, w4 = small.shape[-2:]
    with torch.no_grad():
        logits = model(pad32(small)[None].to(device))
        classes = torch.argmax(logits, dim=1)[0].cpu().numpy()
    obscured = classes[:h4, :w4] != CLOUD_CLASS_CLEAR
    return binary_closing(obscured, structure=np.ones((3, 3)))


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

    try:
        baseline_major = int(float(baseline))
    except (TypeError, ValueError):
        baseline_major = 0

    # A void pixel is DN = 0 in every band, which after the offset correction is
    # a known per-band constant.  Testing every band against that constant rather
    # than summing the cube matters: from baseline 04.00 the void value is
    # negative, and a genuinely dark open-water pixel sums to almost the same
    # total as an empty one, so a sum test would discard real water.
    void = void_reflectance(baseline_major)
    nodata = np.all(np.abs(s_np - void) < 1e-4, axis=0)

    cloud = compute_cloud_mask(model, cube_small, device)
    land = land_mask

    green = s_np[GREEN_IDX]
    nir = s_np[NIR_IDX]

    # Correcting the radiometric offset made both indices fragile at the dark
    # end, and that is new. Before the fix every reflectance sat 0.1 too high, so
    # no denominator ever came near zero. Now the darkest water can land slightly
    # BELOW zero, which is unphysical and is simply the offset applied to sensor
    # noise. A negative term breaks the arithmetic that keeps a normalised
    # difference inside [-1, 1]: with green 0.05 and nir -0.02 the ratio is 2.33.
    # A real scene produced mean_ndwi_water of 1.65 this way.
    #
    # Clamping at zero before forming the ratio is the standard treatment and it
    # restores the guarantee: with both terms non-negative the result cannot
    # leave [-1, 1]. The unclamped values stay in use for the brightness gate,
    # where "darker than zero" is still correctly just "dark".
    swir = s_np[SWIR_IDX]
    green_pos = np.maximum(green, 0.0)
    nir_pos = np.maximum(nir, 0.0)
    swir_pos = np.maximum(swir, 0.0)

    ndsi = (green_pos - swir_pos) / (green_pos + swir_pos + 1e-6)
    ndwi = (green_pos - nir_pos) / (green_pos + nir_pos + 1e-6)

    # And a floor on the denominator, because a ratio of two near-zero numbers is
    # noise even when it is inside the range.
    ndsi_stable = (green_pos + swir_pos) > INDEX_DENOMINATOR_FLOOR
    ndwi_stable = (green_pos + nir_pos) > INDEX_DENOMINATOR_FLOOR

    # NDSI alone does not separate ice from water at top of atmosphere.  Open
    # water is nearly black in the SWIR, so the normalised ratio runs about 0.8,
    # HIGHER than April fast ice at about 0.72.  The classic Dozier snow test,
    # which the MODIS lineage still uses, therefore pairs NDSI with a brightness
    # floor: snow and ice are bright in the visible and the near infrared, water
    # is dark in both.  Without this, every threshold below classifies the open
    # fjord as ice.
    bright = (green > thresholds.vis_bright_min) & (nir > thresholds.nir_bright_min)

    usable = ~cloud & ~land & ~nodata

    ice_solid = (ndsi > thresholds.ndsi_solid) & ndsi_stable & bright & usable
    ice_light = (
        (ndsi > thresholds.ndsi_light)
        & (ndsi < thresholds.ndsi_solid)
        & ndsi_stable
        & bright
        & usable
    )
    water = (ndwi > thresholds.ndwi) & ndwi_stable & ~ice_light & ~ice_solid & usable

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
    sum_counts = cnt_solid + cnt_light + cnt_water + cnt_cloud + cnt_land + cnt_nodata
    unknown = max(sum_counts - int(occupied.sum()), 0)

    # Cells where the surface could actually be judged: everything that is not
    # cloud, not land and not a data gap.
    #
    # Why this matters more than it looks. The published percentages divide by
    # the WHOLE grid, so a cloudy day mechanically reports less ice even when the
    # fjord underneath is unchanged. Cloud cover is not evenly spread over the
    # record: in the analysed window the 2017 to 2020 seasons average 21.3
    # percent cloud and the 2021 to 2025 seasons 29.7 percent. Measured on the
    # published archive, the early-to-late seasonal loss comes out at 35.7
    # percent with the whole-grid denominator and 22.7 percent with this one, so
    # roughly a third of the headline was cloud, not ice.
    #
    # Both are emitted. The whole-grid columns stay so nothing downstream breaks
    # and the change stays auditable; the _clear columns are the ones to build
    # on. A clear share below about 0.3 means the day says little either way.
    cnt_clear = int((~cloud & ~land & ~nodata).sum())
    clear_share = cnt_clear / total if total else 0.0

    def pct(count: int) -> float:
        return round(count / total, 4) if total else 0.0

    def pct_clear(count: int) -> float | str:
        return round(count / cnt_clear, 4) if cnt_clear else ""

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
        "clear_px": cnt_clear,
        "clear_pct": pct(cnt_clear),
        "usable": int(clear_share >= MIN_CLEAR_SHARE),
        "solid_pct_clear": pct_clear(cnt_solid),
        "light_pct_clear": pct_clear(cnt_light),
        "water_pct_clear": pct_clear(cnt_water),
        "mean_ndsi_solid": safe_mean(ndsi, ice_solid),
        "mean_ndsi_light": safe_mean(ndsi, ice_light),
        "mean_ndwi_water": safe_mean(ndwi, water),
        "edge_gap": int((cnt_nodata / total) >= nodata_threshold),
    }
    return stats


def refresh_landmask(template_path: Path) -> Image.Image:
    """Load the landmask template once upfront."""
    return Image.open(template_path).convert("L")
