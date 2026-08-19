#!/usr/bin/env python3
"""A true-colour thumbnail of the fjord for every scene the record used.

    AWS_NO_SIGN_REQUEST=YES python3 scripts/build_scene_thumbnails.py
    AWS_NO_SIGN_REQUEST=YES python3 scripts/build_scene_thumbnails.py --limit 10

WHAT IT IS FOR. The contact sheet in docs/contact-sheet.md gives every day its
numbers. This gives the days that carry a measurement their picture, so a reader
can look at the thing being classified rather than only at the classification.

WHY THE BANDS AND NOT TCI.jp2, WHICH IS ALREADY TRUE COLOUR. Measured over
/vsis3, a windowed read of the fjord costs

    TCI.jp2 (3 bands, one file)   233 s
    B04, B03, B02 separately       14 s together

which is a factor of seventeen and turns a forty hour job into a two hour one.
The 10 m band files are tiled in a way the composite is not.

WHY NOT THE L2A COG, which reads a window in 2.7 s. Because it is a different
product. The classifier reads L1C top-of-atmosphere reflectance, and a thumbnail
from Level 2A surface reflectance would be a picture of something adjacent to
the measurement rather than of the measurement. It also only reaches about four
scenes in five. The same photons at seventeen times the cost of the wrong ones
is the right trade here.

THE STRETCH IS FIXED, AND THAT IS THE POINT. An automatic per-scene contrast
stretch would make every thumbnail look correctly exposed, and in doing so would
erase the one thing the archive says loudest about these seasons: the surface
really does get darker. limitations.md measures 2023 at 34 percent below the
ten-season median across seventeen days that are certainly frozen, with 2025 and
2026 at 10 and 11 percent. Auto-levelling would hide exactly that. So every
scene gets the same fixed reflectance range, and a dark season looks dark.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from uummannaq_ice.config import DEFAULT_AOI  # noqa: E402
from uummannaq_ice.processing import (  # noqa: E402
    QUANTIFICATION_VALUE,
    RADIO_ADD_OFFSET_REFLECTANCE,
)

ARCHIVE = ROOT / "archive" / "reprocessed_2026"
OUT = ROOT / "docs" / "assets" / "thumbs"

BUCKET = "/vsis3/sentinel-s2-l1c/tiles"
RGB_BANDS = ("B04", "B03", "B02")
# 320 by 393, and the height is not a taste decision. The AOI is 14.73 by 18.11
# km in UTM 22N, so it is upright, aspect 0.814. The first version of this
# script drew it into 320 by 256, which is a landscape box, and every thumbnail
# in the archive came out stretched sideways by a factor of 1.54. Nothing in the
# picture announces that: a fjord has no straight lines to go crooked and an
# island has no shape you can check by eye. It surfaced only when the exported
# class rasters arrived at 368 by 453, the pipeline's own upright grid, and the
# photograph beside them did not agree.
#
# The rule that would have caught it: a picture of a place is a measurement of
# that place, and a measurement carries its geometry. Derive the second side
# from the first and the projected bounds, never pick both.
WIDTH, HEIGHT = 320, 393

# The reflectance range the stretch maps to black and white, fixed for every
# scene in the record. 0.02 is darker than open water at this latitude ever
# reads; 0.92 is above sunlit snow. Widening it flattens the seasons, narrowing
# it clips the ice.
STRETCH_LOW, STRETCH_HIGH = 0.02, 0.92

# A white balance, measured rather than dialled in, and the same for every scene.
# Raw top-of-atmosphere reflectance over this fjord is magenta: on the brightest
# quarter of the frame, on clear days that are certainly frozen, green sits about
# eleven percent below red and blue.
#
#     2017-03-01   R 0.724  G 0.623  B 0.726
#     2019-04-06   R 0.842  G 0.760  B 0.845
#     2022-04-09   R 0.851  G 0.768  B 0.858
#
# The ratio holds across the years and across the baseline 04.00 boundary, so it
# is a property of the atmosphere and the instrument rather than of a season.
# Snow is neutral to the eye, so the gain below makes it neutral on screen.
#
# Constant on purpose. A per-scene white balance would neutralise each frame
# against its own content, which for a fjord that is ice in March and water in
# June means correcting away the very thing the sheet is drawn to show.
GAIN = (0.890, 1.0, 0.885)

# ESA moved the radiometric offset at baseline 04.00, which took effect on
# 25 January 2022. Reading a scene from the wrong side of that date shifts every
# reflectance by 0.1, and the whole archive once had to be reprocessed because
# the sign was wrong. Here it only changes how a picture looks, but it changes
# it by the same amount, so the same rule applies.
BASELINE_0400 = date(2022, 1, 25)


def aoi_bounds() -> tuple[float, float, float, float]:
    ring = DEFAULT_AOI["coordinates"][0]
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    return min(xs), min(ys), max(xs), max(ys)


def href_for(tile_id: str) -> tuple[str, date]:
    """s3 prefix and acquisition date, both read out of the scene id.

    A scene id looks like S2A_22WDD_20170219_0_L1C: platform, MGRS tile,
    date, sequence. The bucket lays them out as tiles/22/W/DD/2017/2/19/0,
    with the month and day NOT zero padded, which is easy to get wrong and
    fails as a 404 rather than as an error.
    """
    platform, mgrs, stamp, sequence, _ = tile_id.split("_")
    utm, band, square = mgrs[:2], mgrs[2], mgrs[3:]
    day = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
    prefix = f"{BUCKET}/{int(utm)}/{band}/{square}/{day.year}/{day.month}/{day.day}/{sequence}"
    return prefix, day


def shift_for(day: date) -> float:
    return -RADIO_ADD_OFFSET_REFLECTANCE if day >= BASELINE_0400 else 0.0


def render(tile_id: str) -> Optional[str]:
    prefix, day = href_for(tile_id)
    shift = shift_for(day)
    west, south, east, north = aoi_bounds()

    planes = []
    with rasterio.Env(
        AWS_NO_SIGN_REQUEST="YES",
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        VSI_CACHE="TRUE",
    ):
        for band in RGB_BANDS:
            with rasterio.open(f"{prefix}/{band}.jp2") as src:
                left, bottom, right, top = transform_bounds(
                    "EPSG:4326", src.crs, west, south, east, north, densify_pts=21
                )
                window = from_bounds(left, bottom, right, top, src.transform)
                dn = src.read(
                    1,
                    out_shape=(HEIGHT, WIDTH),
                    window=window,
                    resampling=Resampling.average,
                    boundless=True,
                    fill_value=0,
                ).astype(np.float32)
            planes.append(dn / QUANTIFICATION_VALUE + shift)

    cube = np.stack(planes) * np.array(GAIN, dtype=np.float32)[:, None, None]
    stretched = (cube - STRETCH_LOW) / (STRETCH_HIGH - STRETCH_LOW)
    # Gamma, so the fjord is not a black rectangle with a white island in it.
    # Applied identically to every scene, so it does not undo the fixed range.
    eight_bit = (np.clip(stretched, 0, 1) ** (1 / 1.6) * 255).astype(np.uint8)

    image = Image.fromarray(np.transpose(eight_bit, (1, 2, 0)), "RGB")
    OUT.mkdir(parents=True, exist_ok=True)
    image.save(OUT / f"{tile_id}.webp", "WEBP", quality=72, method=5)
    return tile_id


def usable_scenes() -> list[str]:
    with (ARCHIVE / "summary.csv").open(newline="", encoding="utf-8") as handle:
        return [
            row["tile_id"] for row in csv.DictReader(handle) if row["usable"] == "1"
        ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--limit", type=int, default=None, help="stop after this many scenes"
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--force", action="store_true", help="re-render scenes already on disk"
    )
    args = parser.parse_args()

    os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")

    scenes = usable_scenes()
    if not args.force:
        scenes = [s for s in scenes if not (OUT / f"{s}.webp").exists()]
    if args.limit:
        scenes = scenes[: args.limit]

    if not scenes:
        print("nothing to render; every usable scene already has a thumbnail")
        return

    print(f"rendering {len(scenes)} scenes with {args.workers} workers")
    started = time.time()
    done = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(render, scene): scene for scene in scenes}
        for future in as_completed(futures):
            scene = futures[future]
            try:
                future.result()
                done += 1
            except Exception as error:  # a missing scene must not stop the run
                failed += 1
                print(f"  {scene}: {type(error).__name__} {str(error)[:90]}")
            if (done + failed) % 25 == 0:
                rate = (done + failed) / (time.time() - started)
                left = (len(scenes) - done - failed) / rate if rate else 0
                print(
                    f"  {done + failed}/{len(scenes)}  {rate:.2f}/s  noch {left / 60:.0f} min"
                )

    size = sum(f.stat().st_size for f in OUT.glob("*.webp"))
    print(
        f"\n{done} rendered, {failed} failed, in {(time.time() - started) / 60:.1f} min\n"
        f"{len(list(OUT.glob('*.webp')))} thumbnails, {size / 1024 / 1024:.1f} MB in "
        f"{OUT.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
