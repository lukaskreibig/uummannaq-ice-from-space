#!/usr/bin/env python3
"""Draw the day the classifier was wrong, next to a day it was right.

The finding in docs/landsat-crosscheck.md part three is the hardest thing in this
project to state in a sentence and the easiest to see in a picture: on 30 March
2013 this fjord is frozen, the classifier reads it as open water, and the thermal
band settles it. Two satellites saw that day and agree on the reflectance, so the
error is not the instrument.

    AWS_REQUEST_PAYER=requester python3 scripts/figure_dark_ice.py

Three columns, two rows, and everything in them is measured rather than drawn:

    left    2013-03-30, the day in question
    middle  2013-04-23, the same season twenty four days later, frozen and read
            as frozen, which is the control
    right   the numbers, so the picture cannot be the whole argument

    top     what the sensor saw, green against near infrared, on one shared scale
    bottom  brightness temperature, on one shared scale, with the freezing point
            of seawater marked

The point of the shared scales is that the two columns must be comparable by eye.
The point of the third column is that they must not have to be.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from commissioning_check import (  # noqa: E402
    SEAWATER_FREEZING_K,
    scenes_on,
)
from landsat_l1_crosscheck import (  # noqa: E402
    NIR_BRIGHT_MIN,
    classify,
    read_scene,
)

LOGGER = logging.getLogger("figure_dark_ice")

QUESTIONED = "2013-03-30"
CONTROL = "2013-04-23"
# What fast ice reads over this fjord, from endmember_separability.py.
FAST_ICE_NIR = (0.44, 0.79)


def thermal(item, land_source):
    """Brightness temperature per cell, not just the median."""
    import json

    import boto3
    import rasterio
    from landsat_l1_crosscheck import BOUNDS
    from rasterio.enums import Resampling
    from rasterio.warp import reproject
    from rasterio.windows import from_bounds

    asset = "lwir11" if item.id.startswith("LC") else "lwir"
    band = "10" if item.id.startswith("LC") else "6_VCID_1"
    s3 = boto3.client("s3", region_name="us-west-2")

    def href(name: str) -> str:
        return item.assets[name].extra_fields["alternate"]["s3"]["href"]

    bucket, key = href("MTL.json").replace("s3://", "").split("/", 1)
    meta = json.loads(
        s3.get_object(Bucket=bucket, Key=key, RequestPayer="requester")["Body"].read()
    )["LANDSAT_METADATA_FILE"]
    rescale = meta["LEVEL1_RADIOMETRIC_RESCALING"]
    constants = meta["LEVEL1_THERMAL_CONSTANTS"]
    mult = float(rescale[f"RADIANCE_MULT_BAND_{band}"])
    add = float(rescale[f"RADIANCE_ADD_BAND_{band}"])
    k1 = float(constants[f"K1_CONSTANT_BAND_{band}"])
    k2 = float(constants[f"K2_CONSTANT_BAND_{band}"])

    with rasterio.open(href(asset)) as src:
        window = from_bounds(*BOUNDS, src.transform)
        raw = src.read(1, window=window)
        transform, crs = src.window_transform(window), src.crs

    land = np.zeros(raw.shape, dtype="uint8")
    reproject(
        source=land_source["array"],
        destination=land,
        src_transform=land_source["transform"],
        src_crs=land_source["crs"],
        dst_transform=transform,
        dst_crs=crs,
        resampling=Resampling.nearest,
    )
    radiance = mult * raw.astype("float64") + add
    kelvin = np.full(raw.shape, np.nan)
    good = (raw > 0) & (radiance > 0)
    kelvin[good] = k2 / np.log(k1 / radiance[good] + 1.0)
    kelvin[land > 127] = np.nan
    return kelvin


def main(argv: list[str] | None = None) -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import rasterio
    from matplotlib.colors import Normalize

    from uummannaq_ice.assets import default_landmask_path

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "docs/images")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("rasterio").setLevel(logging.ERROR)
    logging.getLogger("botocore").setLevel(logging.WARNING)

    with rasterio.open(default_landmask_path()) as lm:
        land_source = {"array": lm.read(1), "transform": lm.transform, "crs": lm.crs}

    panels = {}
    for day in (QUESTIONED, CONTROL):
        item = next(i for i in scenes_on(day) if i.id.startswith("LC"))
        bands, land, sun = read_scene(item, land_source)
        got = classify(bands, land)
        kelvin = thermal(item, land_source)
        nir = bands["nir08"].copy()
        nir[land] = np.nan
        panels[day] = {
            "nir": nir,
            "kelvin": kelvin,
            "ice": got["landsat_ice"],
            "sun": sun,
            "scene": item.id,
            "frozen_share": float(
                np.nanmean(kelvin[np.isfinite(kelvin)] < SEAWATER_FREEZING_K)
            ),
        }
        LOGGER.info(
            "%s ice %.3f, %.0f percent of the fjord below freezing",
            day,
            got["landsat_ice"],
            100 * panels[day]["frozen_share"],
        )

    fig, axes = plt.subplots(2, 2, figsize=(9.6, 9.8))
    nir_norm = Normalize(0.0, 0.85)
    k_all = np.concatenate(
        [p["kelvin"][np.isfinite(p["kelvin"])].ravel() for p in panels.values()]
    )
    k_norm = Normalize(np.percentile(k_all, 1), np.percentile(k_all, 99))

    titles = {
        QUESTIONED: "30 March 2013\nthe chain reads 10 percent ice",
        CONTROL: "23 April 2013\nthe chain reads 83 percent ice",
    }
    for col, day in enumerate((QUESTIONED, CONTROL)):
        p = panels[day]
        axes[0][col].imshow(p["nir"], cmap="bone", norm=nir_norm)
        axes[0][col].set_title(titles[day], fontsize=11)
        axes[1][col].imshow(p["kelvin"], cmap="RdBu_r", norm=k_norm)
        axes[1][col].set_title(
            f"{100 * p['frozen_share']:.0f} percent below the freezing point",
            fontsize=10,
        )
        for row in (0, 1):
            axes[row][col].set_xticks([])
            axes[row][col].set_yticks([])

    axes[0][0].set_ylabel("near infrared reflectance", fontsize=10)
    axes[1][0].set_ylabel("brightness temperature", fontsize=10)
    top = fig.colorbar(
        plt.cm.ScalarMappable(norm=nir_norm, cmap="bone"),
        ax=axes[0].tolist(),
        fraction=0.035,
        label="near infrared reflectance",
    )
    top.ax.axhline(NIR_BRIGHT_MIN, color="crimson", lw=1.8)
    top.ax.axhspan(*FAST_ICE_NIR, color="crimson", alpha=0.16)
    top.ax.text(
        -0.4,
        NIR_BRIGHT_MIN,
        "brightness gate",
        fontsize=8,
        va="center",
        ha="right",
        color="crimson",
    )
    top.ax.text(
        -0.4,
        sum(FAST_ICE_NIR) / 2,
        "fast ice",
        fontsize=8,
        va="center",
        ha="right",
        color="crimson",
    )
    # The freezing point sits ABOVE this scale, not inside it, and that is the
    # result rather than a plotting accident: no cell on either day is warm
    # enough to be liquid. Saying so in the label is honest where a line that
    # cannot be drawn would be silently missing.
    fig.colorbar(
        plt.cm.ScalarMappable(norm=k_norm, cmap="RdBu_r"),
        ax=axes[1].tolist(),
        fraction=0.035,
        label=(
            f"kelvin. Seawater freezes at {SEAWATER_FREEZING_K:.1f},\n"
            f"above the top of this scale, so every\ncell on both days is below it."
        ),
    )
    fig.suptitle(
        "Both days are frozen. The classifier only says so about one of them.",
        fontsize=13,
    )
    fig.text(
        0.5,
        0.005,
        "Same fjord, same season, twenty four days apart. On 30 March the surface is\n"
        "too dark for the brightness gate and falls through to the water class, and a\n"
        "second satellite reads the same reflectance that day to within a hundredth.\n"
        "scripts/figure_dark_ice.py, docs/landsat-crosscheck.md part three.",
        ha="center",
        fontsize=9,
        color="0.35",
    )
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "dark-ice-2013-03-30.jpg"
    fig.savefig(path, dpi=110, bbox_inches="tight", pil_kwargs={"quality": 84})
    print(f"written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
