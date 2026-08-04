#!/usr/bin/env python3
"""Derive the land mask from the imagery instead of stretching a painted PNG.

WHY THIS EXISTS
---------------
`processing.make_land_mask` resized a 512x512 template with NEAREST onto whatever
grid each scene produced. That covers the same FRACTION of the frame rather than
the same geography: measured, it masked exactly 9.00 percent of every scene,
whether the grid was 166,704 cells (tile 22WDD) or 186,835 (21WXU), and even for
two scenes that came from West Africa and the North Pacific. Checked against a
summer scene, 9.9 percent of the cells it called land looked like open water, and
a diagonal band of it sat over the fjord.

The consequence is small but one-directional: with the clear-sky denominator,
land is excluded, so water wrongly called land removes water from the
denominator and lifts every ice fraction by an estimated 2.8 to 4.2 percent. It
largely cancels in an early-against-late ratio, but it biases every absolute
number the story prints.

THE METHOD
----------
Water is nearly black in the near infrared; rock and tundra are not. Sea ice is
bright there too, but it moves, and land does not. So over several clear summer
scenes, taken when the fjord is open, the per-pixel near-infrared reflectance
separates the two cleanly, and a drifting floe cannot survive an aggregate over
several dates.

The aggregate is a high PERCENTILE rather than the median, and that is the whole
subtlety. At 70 degrees north the heart-shaped mountain casts a large shadow onto
its own eastern face, and a shadowed slope is as dark in the near infrared as
water is. With the median that slope drops out of the mask, which is visible in
the quicklook as a dark band through the middle of the island. The sun azimuth
differs between scenes, so a face shadowed in one is lit in another: taking the
75th percentile recovers it while still needing most scenes to disagree before a
single drifting floe can be promoted to land.

The result is written as a GeoTIFF carrying the CRS and transform of the scene
grid it was derived on, so it can be reprojected onto any future grid rather than
stretched to fit. That is the part the painted template could never do.

    python3 scripts/derive_landmask.py --out src/uummannaq_ice/assets/landmask.tif

Every parameter is reported, and a quicklook PNG is written next to the GeoTIFF so
the result can be judged by eye rather than trusted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import odc.stac  # noqa: E402
import pystac_client  # noqa: E402
import rasterio  # noqa: E402
from PIL import Image  # noqa: E402
from rasterio.transform import Affine  # noqa: E402
from scipy.ndimage import (  # noqa: E402
    binary_closing,
    binary_fill_holes,
    binary_opening,
)

from uummannaq_ice.config import (  # noqa: E402
    DEFAULT_AOI,
    DEFAULT_COLLECTION,
    DEFAULT_STAC_URL,
)
from uummannaq_ice.processing import (  # noqa: E402
    QUANTIFICATION_VALUE,
    RADIO_ADD_OFFSET_BASELINE,
    RADIO_ADD_OFFSET_REFLECTANCE,
)
from uummannaq_ice.stac import fix_l1c_hrefs, mgrs_zone_of  # noqa: E402

# High summer, when the fjord is reliably open and the sun is high enough that
# rock is unambiguously brighter than water in the near infrared.
DEFAULT_WINDOWS = [
    ("2019-08-01", "2019-08-31"),
    ("2021-08-01", "2021-08-31"),
    ("2023-08-01", "2023-08-31"),
    ("2024-08-01", "2024-08-31"),
]
# Open fjord water sits around 0.005 to 0.02 in the near infrared; bare rock and
# tundra sit well above 0.10. The cut is deliberately placed in the empty middle.
NIR_LAND_FLOOR = 0.06
# The tile the record is built on. Fixing it keeps the derivation on one grid.
HOME_TILE = "22WDD"
# Remove single stray pixels, then close pinholes inside the island.
MORPHOLOGY_CELLS = 3


def load_nir(item, aoi) -> tuple[np.ndarray, object]:
    baseline = int(float(item.properties.get("s2:processing_baseline", "0.0")))
    shift = (
        -RADIO_ADD_OFFSET_REFLECTANCE if baseline >= RADIO_ADD_OFFSET_BASELINE else 0.0
    )
    ds = odc.stac.load([item], bands=["nir"], geopolygon=aoi, chunks={})
    nir = ds["nir"][0].values.astype(np.float32) / QUANTIFICATION_VALUE + shift
    return nir, ds.odc.geobox


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scenes-per-window", type=int, default=2)
    parser.add_argument("--nir-floor", type=float, default=NIR_LAND_FLOOR)
    parser.add_argument(
        "--percentile",
        type=float,
        default=75.0,
        help="Per-pixel aggregate across scenes. 50 is the median; higher "
        "recovers slopes that are shadowed in only some scenes.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = pystac_client.Client.open(DEFAULT_STAC_URL)
    picked = []
    for start, end in DEFAULT_WINDOWS:
        found = [
            i
            for i in client.search(
                collections=[DEFAULT_COLLECTION],
                intersects=DEFAULT_AOI,
                datetime=f"{start}/{end}",
            ).items()
            if str(i.id).split("_")[1] == HOME_TILE and mgrs_zone_of(i.id) == 22
        ]
        found.sort(key=lambda i: (i.properties.get("eo:cloud_cover", 100.0), i.id))
        picked.extend(found[: args.scenes_per_window])

    if not picked:
        print("[FAIL] no scenes found", file=sys.stderr)
        return 1

    print(f"  {len(picked)} clear summer scenes on tile {HOME_TILE}:")
    for item in picked:
        print(
            f"    {item.id}  cloud {item.properties.get('eo:cloud_cover', float('nan')):.1f} %"
        )
    if args.dry_run:
        print("\n[DRY-RUN] stopping before download")
        return 0

    # Typed explicitly: inferred from `None` alone the geobox reads as `object`
    # further down, and the transform and CRS reads that write the GeoTIFF are
    # exactly the part that must not be guessed at. A mask written on the wrong
    # transform is the defect this script exists to fix.
    stack: list[np.ndarray] = []
    geobox: Any = None
    for item in picked:
        nir, box = load_nir(fix_l1c_hrefs(item), DEFAULT_AOI)
        if geobox is None:
            geobox = box
        elif nir.shape != stack[0].shape:
            print(f"  skipping {item.id}: grid {nir.shape} differs")
            continue
        stack.append(nir)

    cube = np.stack(stack)
    median = np.percentile(cube, args.percentile, axis=0)
    land = median > args.nir_floor
    # The shadowed face can still leave pinholes; they are enclosed by land.
    land = binary_fill_holes(land)

    structure = np.ones((MORPHOLOGY_CELLS, MORPHOLOGY_CELLS))
    land = binary_opening(land, structure=structure)
    land = binary_closing(land, structure=structure)

    print(f"\n  grid {land.shape}, land share {land.mean():.4f}")
    print(f"  aggregate: {args.percentile:.0f}th percentile over {len(stack)} scenes")
    print(
        f"  near-infrared median: water side {np.median(median[~land]):.4f}, "
        f"land side {np.median(median[land]):.4f}"
    )
    gap = np.median(median[land]) / max(np.median(median[~land]), 1e-9)
    print(f"  separation factor: {gap:.1f}x")
    print(f"  separation at the cut: {args.nir_floor}")

    transform = Affine(*geobox.transform[:6])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        args.out,
        "w",
        driver="GTiff",
        height=land.shape[0],
        width=land.shape[1],
        count=1,
        dtype="uint8",
        crs=geobox.crs.to_wkt(),
        transform=transform,
        compress="deflate",
    ) as dst:
        dst.write(land.astype(np.uint8) * 255, 1)
        dst.update_tags(
            method="median near-infrared over clear summer scenes",
            nir_floor=str(args.nir_floor),
            scenes=",".join(i.id for i in picked),
            tile=HOME_TILE,
        )
    print(f"\n  written: {args.out}  ({args.out.stat().st_size / 1000:.0f} kB)")

    preview = args.out.with_suffix(".png")
    scaled = np.clip(median / np.percentile(median, 98), 0, 1)
    rgb = np.dstack([scaled, scaled, scaled])
    rgb[land] = rgb[land] * 0.4 + np.array([1.0, 0.0, 0.0]) * 0.6
    Image.fromarray((rgb * 255).astype(np.uint8)).resize((900, 900)).save(preview)
    print(f"  quicklook: {preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
