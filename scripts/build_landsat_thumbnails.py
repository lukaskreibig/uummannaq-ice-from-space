#!/usr/bin/env python3
"""A picture for the two Landsat layers, from the same product their numbers came from.

    python3 scripts/build_landsat_thumbnails.py
    python3 scripts/build_landsat_thumbnails.py --limit 10 --force

WHAT IT IS FOR. build_scene_thumbnails.py gives every usable Sentinel-2 scene its
picture. This does the same for the other two optical layers on the contact
sheet: the Landsat true-colour scene, and the thermal band of that same scene.

The gap it fills is large. Of the 1280 days in the analysed window, 543 carry a
Sentinel-2 scene and 545 carry Landsat, but only 241 carry both. 304 days have a
Landsat measurement in the panel and no picture at all.

WHY EACH INSTRUMENT KEEPS ITS OWN PICTURE, and why this does not simply fill the
Sentinel-2 slot on those 304 days. build_site_data.py refuses to merge
instruments and tests/test_site_data.py asserts that it cannot. A picture
standing in for another instrument's picture does at the image level exactly
what the data layer forbids at the number level: the reader sees "the fjord that
day" without registering which satellite. So the Landsat picture goes in the
Landsat row, under the Landsat number, and a day with no Landsat keeps saying so.

THE STRETCH IS FIXED, AND IT IS NOT SENTINEL-2's. Same rule as the other script,
different constants, because this is a different instrument. Measured here, on
four clear days that are certainly frozen, over the brightest quarter of the
frame:

    2017-03-10  sun 15.1  R 0.711  G 0.649  B 0.742
    2020-03-02  sun 12.1  R 0.655  G 0.584  B 0.700
    2023-04-03  sun 24.4  R 0.734  G 0.678  B 0.754
    2026-04-13  sun 28.3  R 0.726  G 0.677  B 0.754

The same magenta cast Sentinel-2 shows, green sitting below red and blue, which
is the atmosphere rather than the sensor. Snow is neutral to the eye, so the
gain below makes it neutral on screen. And on three clear days of open water,
the darkest quarter reads 0.026 to 0.030 in red, which is what sets the floor.

Sharing the numbers between the two instruments would be the mistake here.
OLI's bands are not MSI's, the atmospheric path is not the same, and the two
pictures are never to be compared on brightness. They are compared on what they
show.

WHY LEVEL 1 AND NOT LEVEL 2. Same reason build_scene_thumbnails.py gives:
landsat_season_series.py measures on collection02 level-1 top-of-atmosphere, so
the picture comes from the product the number came from. A surface-reflectance
thumbnail would be a picture of something adjacent to the measurement.

THE ONE CORRECTION LANDSAT LEVEL 1 DOES NOT CARRY. Sentinel-2 L1C reflectance is
already divided by the cosine of the solar zenith angle; Landsat Level 1 is not.
Skipping it makes a February scene at 12 degrees of sun elevation look four
times darker than an April scene of the same ice. landsat_l1_crosscheck.py
carries the same division for the same reason.

COST. This bucket is requester pays, unlike the Sentinel-2 one. Measured: a
windowed read touches 12 of 1225 tiles per band, about 3.2 MB per scene for four
bands, so roughly 1.7 GB and about 17 cents for the whole record.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from uummannaq_ice.config import DEFAULT_AOI  # noqa: E402

ARCHIVE = ROOT / "archive" / "reprocessed_2026"
OUT_RGB = ROOT / "docs" / "assets" / "thumbs-landsat"
OUT_THERMAL = ROOT / "docs" / "assets" / "thumbs-thermal"

BUCKET = "usgs-landsat"
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

# The window the contact sheet draws, matching build_site_data.py.
SEASON_START, SEASON_END = 53, 180
FIRST_SEASON, LAST_SEASON = 2017, 2026

# Which MTL band number each colour is, per instrument. Only OLI appears inside
# this window, 366 Landsat 8 scenes and 179 Landsat 9, but the map is here
# because reading an ETM+ scene with OLI's numbers applies the wrong gain to
# every band and produces a plausible picture rather than a crash.
RGB_NUMBER = {
    "LC": (4, 3, 2),  # OLI, Landsat 8 and 9
    "LE": (3, 2, 1),  # ETM+, Landsat 7
    "LT": (3, 2, 1),  # TM, Landsat 4 and 5
}
THERMAL_NUMBER = {"LC": 10, "LE": 6, "LT": 6}

# See the module docstring. 0.02 is below the darkest open water measured here,
# 0.92 is above sunlit snow, and both are held constant so a dark season looks
# dark rather than being levelled back to average.
STRETCH_LOW, STRETCH_HIGH = 0.02, 0.92

# Measured, not dialled in: the mean of G/R and G/B over the four clear frozen
# days above. Sentinel-2's own gain is (0.890, 1.0, 0.885), close in shape and
# different in value, which is the point of not sharing them.
GAIN = (0.915, 1.0, 0.877)

GAMMA = 1 / 1.6

# The thermal range, fixed like the optical stretch, but NOT set to the span of
# the record, and the first attempt here was wrong in a way worth recording.
#
# The archive's brightness temperatures run 244.6 to 282.1 K across ten seasons,
# so a range of 243 to 283 looked obviously right. It produced a flat rectangle.
# Measured inside one deep-winter scene, the whole fjord sits between 255.0 and
# 263.9 K: NINE kelvin of spread, against forty on the ramp. Every thermal
# picture was one colour because the variation within a scene is a fifth of the
# variation between seasons, and the band is 100 m data on a 30 m grid besides.
#
# So the colour resolution goes where the question is instead. The band is on
# this page to answer one thing, whether the fjord radiated below the freezing
# point of seawater, and these bounds put that line in the middle and let
# everything far from it saturate. A deep winter day is then uniformly deep blue,
# which is the honest reading of a fjord ten kelvin below freezing, and the 25
# contradicted days show their structure exactly where it matters.
#
# The exact median and the frozen share stay in the panel text beside the
# picture, so the magnitude the saturation gives up is not lost, only moved to
# where a number says it better than a colour can.
THERMAL_LOW, THERMAL_HIGH = 261.0, 281.0
SEAWATER_FREEZING_K = 271.35


def aoi_bounds() -> tuple[float, float, float, float]:
    ring = DEFAULT_AOI["coordinates"][0]
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    return min(xs), min(ys), max(xs), max(ys)


def prefix_for(scene: str) -> str:
    """The s3 key prefix, read straight out of the scene id.

    A scene id looks like LC08_L1TP_012010_20170310_20200905_02_T1: sensor,
    correction level, WRS path and row, acquisition date, processing date,
    collection, tier. The bucket lays them out by year, path and row, all zero
    padded exactly as they appear in the id, which is the one part of the
    Sentinel-2 layout that does NOT carry over.
    """
    path, row, year = scene[10:13], scene[13:16], scene[17:21]
    return f"collection02/level-1/standard/oli-tirs/{year}/{path}/{row}/{scene}/{scene}"


# Deep blue, through cyan, to white at the freezing point, then amber. The pivot
# is the lightest colour rather than an end, so the eye finds the boundary
# without reading a legend, and the two sides never share a hue.
COLD_END = (0.04, 0.12, 0.42)
COLD_MID = (0.16, 0.58, 0.82)
PIVOT = (0.97, 0.97, 0.95)
WARM_END = (0.85, 0.42, 0.08)


def diverging(value: np.ndarray) -> np.ndarray:
    """Brightness temperature, scaled to 0..1, to colour.

    Blue below the freezing point of seawater, amber above it, near white on the
    line itself. A single-hue ramp would read as "colder is darker" and hide the
    one boundary this band exists to test.
    """
    pivot = (SEAWATER_FREEZING_K - THERMAL_LOW) / (THERMAL_HIGH - THERMAL_LOW)

    def ramp(t: np.ndarray, a, b) -> np.ndarray:
        t = np.clip(t, 0, 1)
        return np.stack([a[i] + (b[i] - a[i]) * t for i in range(3)])

    below = value / pivot
    cold = np.where(
        below < 0.5,
        ramp(below * 2, COLD_END, COLD_MID),
        ramp((below - 0.5) * 2, COLD_MID, PIVOT),
    )
    warm = ramp((value - pivot) / (1 - pivot), PIVOT, WARM_END)
    return np.where(value < pivot, cold, warm)


def render(scene: str, want_rgb: bool, want_thermal: bool) -> str:
    west, south, east, north = aoi_bounds()
    key = prefix_for(scene)
    sensor = scene[:2]

    s3 = boto3.client("s3", region_name="us-west-2")
    body = s3.get_object(Bucket=BUCKET, Key=f"{key}_MTL.json", RequestPayer="requester")
    meta = json.loads(body["Body"].read())["LANDSAT_METADATA_FILE"]
    rescale = meta["LEVEL1_RADIOMETRIC_RESCALING"]
    sun = float(meta["IMAGE_ATTRIBUTES"]["SUN_ELEVATION"])
    cos_sza = math.sin(math.radians(sun))
    if cos_sza <= 0:
        raise ValueError(f"{scene}: sun below the horizon")

    def window_read(number: int) -> np.ndarray:
        with rasterio.open(f"/vsis3/{BUCKET}/{key}_B{number}.TIF") as src:
            left, bottom, right, top = transform_bounds(
                "EPSG:4326", src.crs, west, south, east, north, densify_pts=21
            )
            return src.read(
                1,
                out_shape=(HEIGHT, WIDTH),
                window=from_bounds(left, bottom, right, top, src.transform),
                resampling=Resampling.average,
                boundless=True,
                fill_value=0,
            ).astype(np.float32)

    with rasterio.Env(
        AWS_REQUEST_PAYER="requester",
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        VSI_CACHE="TRUE",
    ):
        if want_rgb:
            planes = []
            for number in RGB_NUMBER[sensor]:
                mult = float(rescale[f"REFLECTANCE_MULT_BAND_{number}"])
                add = float(rescale[f"REFLECTANCE_ADD_BAND_{number}"])
                planes.append((window_read(number) * mult + add) / cos_sza)
            cube = np.stack(planes) * np.array(GAIN, dtype=np.float32)[:, None, None]
            stretched = (cube - STRETCH_LOW) / (STRETCH_HIGH - STRETCH_LOW)
            eight = (np.clip(stretched, 0, 1) ** GAMMA * 255).astype(np.uint8)
            OUT_RGB.mkdir(parents=True, exist_ok=True)
            Image.fromarray(np.transpose(eight, (1, 2, 0)), "RGB").save(
                OUT_RGB / f"{scene}.webp", "WEBP", quality=72, method=5
            )

        if want_thermal:
            number = THERMAL_NUMBER[sensor]
            mult = float(rescale[f"RADIANCE_MULT_BAND_{number}"])
            add = float(rescale[f"RADIANCE_ADD_BAND_{number}"])
            constants = meta["LEVEL1_THERMAL_CONSTANTS"]
            k1 = float(constants[f"K1_CONSTANT_BAND_{number}"])
            k2 = float(constants[f"K2_CONSTANT_BAND_{number}"])
            dn = window_read(number)
            radiance = dn * mult + add
            with np.errstate(divide="ignore", invalid="ignore"):
                kelvin = k2 / np.log(k1 / np.maximum(radiance, 1e-6) + 1.0)
            kelvin = np.where(dn > 0, kelvin, np.nan)
            scaled = (kelvin - THERMAL_LOW) / (THERMAL_HIGH - THERMAL_LOW)
            rgb = diverging(np.clip(np.nan_to_num(scaled, nan=0.0), 0, 1))
            # A cell the sensor never filled is not cold, it is absent.
            rgb = np.where(np.isnan(kelvin)[None, :, :], 0.05, rgb)
            eight = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
            OUT_THERMAL.mkdir(parents=True, exist_ok=True)
            Image.fromarray(np.transpose(eight, (1, 2, 0)), "RGB").save(
                OUT_THERMAL / f"{scene}.webp", "WEBP", quality=72, method=5
            )

    return scene


def wanted() -> list[tuple[str, bool, bool]]:
    """Every in-window scene, and which of the two pictures it still needs."""

    def in_window(row: dict[str, str]) -> bool:
        return (
            FIRST_SEASON <= int(row["season"]) <= LAST_SEASON
            and SEASON_START <= int(row["doy"]) <= SEASON_END
        )

    def read(name: str) -> set[str]:
        with (ARCHIVE / name).open(newline="", encoding="utf-8") as handle:
            return {row["scene"] for row in csv.DictReader(handle) if in_window(row)}

    optical = read("landsat_season_series.csv")
    thermal = read("thermal_audit.csv")
    return [
        (scene, scene in optical, scene in thermal)
        for scene in sorted(optical | thermal)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    os.environ.setdefault("AWS_REQUEST_PAYER", "requester")

    jobs = []
    for scene, optical, thermal in wanted():
        need_rgb = optical and (args.force or not (OUT_RGB / f"{scene}.webp").exists())
        need_th = thermal and (
            args.force or not (OUT_THERMAL / f"{scene}.webp").exists()
        )
        if need_rgb or need_th:
            jobs.append((scene, need_rgb, need_th))
    if args.limit:
        jobs = jobs[: args.limit]

    if not jobs:
        print("nothing to render; every scene already has the pictures it needs")
        return

    print(f"rendering {len(jobs)} scenes with {args.workers} workers", flush=True)
    started = time.time()
    done = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(render, *job): job[0] for job in jobs}
        for future in as_completed(futures):
            scene = futures[future]
            try:
                future.result()
                done += 1
            except Exception as error:  # one missing scene must not stop the run
                failed += 1
                print(
                    f"  {scene}: {type(error).__name__} {str(error)[:90]}", flush=True
                )
            if (done + failed) % 25 == 0:
                rate = (done + failed) / (time.time() - started)
                left = (len(jobs) - done - failed) / rate if rate else 0
                print(
                    f"  {done + failed}/{len(jobs)}  {rate:.2f}/s  "
                    f"noch {left / 60:.0f} min",
                    flush=True,
                )

    rgb_n = len(list(OUT_RGB.glob("*.webp"))) if OUT_RGB.exists() else 0
    th_n = len(list(OUT_THERMAL.glob("*.webp"))) if OUT_THERMAL.exists() else 0
    size = sum(
        f.stat().st_size
        for d in (OUT_RGB, OUT_THERMAL)
        if d.exists()
        for f in d.glob("*.webp")
    )
    print(
        f"\n{done} rendered, {failed} failed, in {(time.time() - started) / 60:.1f} min\n"
        f"{rgb_n} true colour, {th_n} thermal, {size / 1024 / 1024:.1f} MB total"
    )


if __name__ == "__main__":
    main()
