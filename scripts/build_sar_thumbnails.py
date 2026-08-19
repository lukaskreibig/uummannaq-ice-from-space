#!/usr/bin/env python3
"""A radar picture for the days the optical chain and the thermometer disagreed.

    python3 scripts/build_sar_thumbnails.py

WHAT IT IS FOR. The contact sheet's fourth row carries Sentinel-1's verdict on
the 27 days where the chain called the fjord open and the thermal band said it
radiated below the freezing point of seawater. 13 of those read as neither fast
ice nor open water, which is the most careful finding this project has, and
until now it was the only row on the sheet with no picture at all.

WHICH ACQUISITION, and this is the part that had to be got right. A day can have
up to three passes, and the verdict was reached on exactly one of them. The
verdict table does not name it, but it does carry `value_db`, and that number is
the `water_median_db` of the acquisition it came from. So the scene is
identified by matching those two, and a day whose match is ambiguous or missing
is skipped rather than illustrated with a neighbouring pass. Showing a different
overpass than the one that produced the verdict would be a picture of a
different measurement.

WHY IT IS FREE, unlike the Landsat pictures. Sentinel-1 RTC comes from the
Microsoft Planetary Computer, which hands out anonymous SAS tokens, rather than
from a requester-pays bucket.

WHAT THE PICTURE IS. Terrain-corrected gamma0 in HH, the same product and the
same polarisation the analysis measured, in decibels on a fixed scale. Measured
across a fast-ice day, an open-water day and a between day, the fjord sits
between about -25 and -4 dB while the mountains return up to +19, so the range
below covers the water and lets the land saturate. Fixed for every scene, for
the same reason the optical stretches are: the difference between these days is
the whole point, and a per-scene stretch would level it away.

Radar is not a photograph and the sheet says so. Backscatter is roughness and
wetness, not brightness, which is why a smooth closed sheet reads dark and so
does calm open water, and why the analysis separates them on SPREAD rather than
on level.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
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
from uummannaq_ice.sar import SasToken  # noqa: E402

ARCHIVE = ROOT / "archive" / "reprocessed_2026"
OUT = ROOT / "docs" / "assets" / "thumbs-sar"

ITEM_URL = (
    "https://planetarycomputer.microsoft.com/api/stac/v1/collections/"
    "sentinel-1-rtc/items/{}"
)

# The same upright geometry as every other quicklook on this sheet. See the note
# in build_scene_thumbnails.py about the 1.54 stretch that hid here for a while.
WIDTH, HEIGHT = 320, 393

# Decibels, fixed for the record. Measured over three days chosen to differ,
# one reading as fast ice, one as open water and one as neither:
#
#     2016-04-17  like open water   p1 -24.6  median -19.6  p99  -4.1
#     2020-04-26  like fast ice     p1 -20.8  median -15.1  p99  -4.2
#     2021-02-24  between           p1 -24.4  median -19.0  p99  -5.2
#
# The medians are four decibels apart between ice and water, which is the signal
# this row exists to carry, and a per-scene stretch would erase it.
SAR_LOW, SAR_HIGH = -25.0, -3.0


def aoi_bounds() -> tuple[float, float, float, float]:
    ring = DEFAULT_AOI["coordinates"][0]
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    return min(xs), min(ys), max(xs), max(ys)


def scene_for_each_verdict() -> dict[str, str]:
    """Day to the scene id whose measurement became that day's verdict.

    Matched on `value_db` against `water_median_db`, because that is the only
    link the two tables share. A day with no unique match is left out entirely.
    """
    verdicts = list(csv.DictReader((ARCHIVE / "sar_thermal_verdicts.csv").open()))
    passes = [
        row
        for row in csv.DictReader((ARCHIVE / "sar_thermal_days.csv").open())
        if row["role"] == "suspect" and row["water_median_db"]
    ]

    chosen: dict[str, str] = {}
    for verdict in verdicts:
        day = verdict["day"][:10]
        if not verdict["value_db"]:
            continue
        target = float(verdict["value_db"])
        passes_here = [row for row in passes if row["target_day"][:10] == day]
        matches = [
            row
            for row in passes_here
            if abs(float(row["water_median_db"]) - target) < 1e-6
        ]
        if len(matches) == 1:
            chosen[day] = matches[0]["scene_id"]
        else:
            # Six days out of 27 land here, and they are not a fault. On four
            # of them the verdict is the mean of two passes, so no single
            # acquisition IS the measurement; on two more the value matches
            # neither a pass, their mean nor their median, and a picture chosen
            # without understanding that would be a guess presented as evidence.
            print(
                f"  {day}: value_db {target} is not any one acquisition "
                f"({len(passes_here)} on this day), so no single picture is the "
                "measurement; skipped"
            )
    return chosen


def render(day: str, scene_id: str, token: SasToken) -> Optional[str]:
    west, south, east, north = aoi_bounds()
    item = json.load(urllib.request.urlopen(ITEM_URL.format(scene_id), timeout=90))
    asset = item.get("assets", {}).get("hh")
    if asset is None:
        raise ValueError(f"{scene_id} carries no HH asset")

    with rasterio.open(f"{asset['href']}?{token.value()}") as src:
        left, bottom, right, top = transform_bounds(
            "EPSG:4326", src.crs, west, south, east, north, densify_pts=21
        )
        gamma = src.read(
            1,
            out_shape=(HEIGHT, WIDTH),
            window=from_bounds(left, bottom, right, top, src.transform),
            resampling=Resampling.average,
            boundless=True,
            fill_value=0,
        ).astype("float64")

    with np.errstate(divide="ignore", invalid="ignore"):
        decibels = 10 * np.log10(np.where(gamma > 0, gamma, np.nan))
    scaled = (decibels - SAR_LOW) / (SAR_HIGH - SAR_LOW)
    # A cell the radar never filled is absent, not dark, and drawing it as the
    # darkest value would put open water where there is no measurement.
    eight = np.where(np.isfinite(scaled), np.clip(scaled, 0, 1) * 255, 22).astype(
        np.uint8
    )

    OUT.mkdir(parents=True, exist_ok=True)
    Image.fromarray(eight, "L").save(OUT / f"{day}.webp", "WEBP", quality=74, method=5)
    return day


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    chosen = scene_for_each_verdict()
    todo = {
        day: scene
        for day, scene in chosen.items()
        if args.force or not (OUT / f"{day}.webp").exists()
    }
    if not todo:
        print("nothing to render; every adjudicated day already has its radar picture")
        return

    print(f"rendering {len(todo)} radar quicklooks", flush=True)
    token = SasToken()
    started = time.time()
    done = failed = 0
    for day, scene in sorted(todo.items()):
        try:
            render(day, scene, token)
            done += 1
        except Exception as error:
            failed += 1
            print(f"  {day}: {type(error).__name__} {str(error)[:90]}", flush=True)

    size = sum(f.stat().st_size for f in OUT.glob("*.webp")) if OUT.exists() else 0
    print(
        f"\n{done} rendered, {failed} failed, in {(time.time() - started) / 60:.1f} min\n"
        f"{len(list(OUT.glob('*.webp')))} radar quicklooks, {size / 1024:.0f} KB"
    )


if __name__ == "__main__":
    main()
