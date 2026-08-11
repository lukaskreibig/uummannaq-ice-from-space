#!/usr/bin/env python3
"""Ask a second instrument about the regime the first cross-check cannot reach.

landsat_crosscheck.py compares against Collection 2 Level 2, and Level 2 surface
reflectance is not produced above a solar zenith of 76 degrees. Its 82 pairs
therefore span sun elevations of 14.3 to 42.5 degrees, while the 28 February and
March scenes that report almost no ice under a sky the pipeline itself calls
clear all sit below that floor. The second instrument was never asked about the
one regime where the first one is unexplained.

Level 1 has no such floor. It is also the closer product: the pipeline reads
Sentinel-2 L1C, which is top of atmosphere, so a Level 1 comparison changes the
sensor and nothing else, where Level 2 changes the sensor and the atmospheric
correction together.

    python3 scripts/landsat_l1_crosscheck.py --regime winter
    python3 scripts/landsat_l1_crosscheck.py --regime all

Access: the assets live on s3://usgs-landsat, which is requester pays. Set up an
AWS profile with s3:GetObject on that bucket and nothing else, and the run costs
cents. The https mirror at landsatlook.usgs.gov redirects to a USGS login and is
not anonymous.

THE FACTOR OF SEVEN, and it is the reason this script exists as its own file.
Sentinel-2 L1C reflectance is already divided by the cosine of the solar zenith
angle. Landsat Level 1 is NOT: the REFLECTANCE_MULT and REFLECTANCE_ADD
coefficients in the MTL give reflectance without that division, and it has to be
applied by hand. On 2019-02-19, at a sun elevation of 7.75 degrees, the factor is
7.4. Measured on that scene, fast ice reads 0.081 in green uncorrected and 0.601
corrected, against 0.44 to 0.74 for Sentinel-2 over fast ice.

Skipping it would not have produced an obvious error. It would have put every
February scene below the 0.10 brightness floor, so Landsat would have reported no
ice all winter, and that would have looked like a triumphant confirmation of the
very anomalies this script is meant to test. A wrong answer that agrees with the
hypothesis is the worst kind, and this one was one line away.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

LOGGER = logging.getLogger("landsat_l1_crosscheck")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / "archive/reprocessed_2026/summary.csv"

USGS_STAC = "https://landsatlook.usgs.gov/stac-server"
AOI = [-52.374, 70.629, -51.905, 70.799]
BOUNDS = (450540, 7836200, 465280, 7854320)  # the land mask's own extent

# OLI band numbers behind the STAC asset names.
BAND_NUMBER = {"green": 3, "nir08": 5, "swir16": 6}

# The pipeline's own cuts, unchanged, so only the instrument differs.
NDSI_SOLID, NDSI_LIGHT, NDWI_MIN = 0.70, 0.40, 0.20
VIS_BRIGHT_MIN, NIR_BRIGHT_MIN = 0.10, 0.17
INDEX_FLOOR = 0.02

# Measured on the Level 2 run: below this share of the fjord classified, the
# comparison is reading a hole rather than a surface.
MIN_CLASSIFIED_SHARE = 0.90
LEVEL2_FLOOR = 14.06
SEASON_WINDOW = (45, 180)


def read_scene(item, land_source):
    """Windowed read of one Landsat Level 1 scene, in reflectance."""
    import boto3
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import reproject
    from rasterio.windows import from_bounds

    s3 = boto3.client("s3", region_name="us-west-2")

    def s3href(name: str) -> str:
        return item.assets[name].extra_fields["alternate"]["s3"]["href"]

    bucket, key = s3href("MTL.json").replace("s3://", "").split("/", 1)
    body = s3.get_object(Bucket=bucket, Key=key, RequestPayer="requester")["Body"]
    meta = json.loads(body.read())["LANDSAT_METADATA_FILE"]
    rescale = meta["LEVEL1_RADIOMETRIC_RESCALING"]
    sun = float(meta["IMAGE_ATTRIBUTES"]["SUN_ELEVATION"])
    # The correction Sentinel-2 already carries and Landsat Level 1 does not.
    cos_sza = math.sin(math.radians(sun))
    if cos_sza <= 0:
        raise ValueError("sun below the horizon")

    out: dict[str, np.ndarray] = {}
    land = None
    for name in ("green", "nir08", "swir16", "qa_pixel"):
        with rasterio.open(s3href(name)) as src:
            window = from_bounds(*BOUNDS, src.transform)
            arr = src.read(1, window=window)
            if name == "qa_pixel":
                out[name] = arr.astype("uint16")
            else:
                n = BAND_NUMBER[name]
                mult = float(rescale[f"REFLECTANCE_MULT_BAND_{n}"])
                add = float(rescale[f"REFLECTANCE_ADD_BAND_{n}"])
                out[name] = (mult * arr.astype("float64") + add) / cos_sza
                out[name][arr == 0] = np.nan
            if land is None:
                land = np.zeros(arr.shape, dtype="uint8")
                reproject(
                    source=land_source["array"],
                    destination=land,
                    src_transform=land_source["transform"],
                    src_crs=land_source["crs"],
                    dst_transform=src.window_transform(window),
                    dst_crs=src.crs,
                    resampling=Resampling.nearest,
                )
    return out, land > 127, sun


def classify(bands, land):
    """The pipeline's decision rule, on Landsat reflectance."""
    green, nir, swir = bands["green"], bands["nir08"], bands["swir16"]
    qa = bands["qa_pixel"]
    # QA_PIXEL bits: 0 fill, 1 dilated cloud, 3 cloud, 4 cloud shadow.
    obscured = (qa & (1 << 1) | qa & (1 << 3) | qa & (1 << 4)) > 0
    fill = (qa & 1) > 0
    valid = ~fill & ~land & ~obscured & np.isfinite(green) & np.isfinite(nir)

    g, n, s = (np.maximum(np.nan_to_num(x), 0.0) for x in (green, nir, swir))
    ndsi = (g - s) / (g + s + 1e-6)
    ndwi = (g - n) / (g + n + 1e-6)
    stable_s = (g + s) > INDEX_FLOOR
    stable_w = (g + n) > INDEX_FLOOR
    bright = (green > VIS_BRIGHT_MIN) & (nir > NIR_BRIGHT_MIN)

    solid = (ndsi > NDSI_SOLID) & stable_s & bright & valid
    light = (ndsi > NDSI_LIGHT) & (ndsi < NDSI_SOLID) & stable_s & bright & valid
    water = (ndwi > NDWI_MIN) & stable_w & ~solid & ~light & valid
    ice = solid | light
    classified = int(ice.sum() + water.sum())
    grid = int((~land).sum())
    return {
        "landsat_ice": float(ice.sum() / classified) if classified else float("nan"),
        "landsat_share": classified / grid if grid else 0.0,
    }


def sentinel_series(archive: Path) -> pd.DataFrame:
    frame = pd.read_csv(archive)
    for col in ("solid_px", "light_px", "water_px", "cloud_px", "land_px", "nodata_px"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
    stamp = pd.to_datetime(frame.timestamp.astype(str), format="%Y%m%dT%H%M%S")
    frame["day"] = stamp.dt.date.astype(str)
    frame["doy"] = stamp.dt.dayofyear
    classified = frame.solid_px + frame.light_px + frame.water_px
    grid = classified + frame.cloud_px + frame.land_px + frame.nodata_px
    frame["s2_ice"] = (frame.solid_px + frame.light_px).divide(
        classified.where(classified > 0)
    )
    frame["s2_share"] = classified.divide(grid.where(grid > 0))
    return frame[["day", "doy", "s2_ice", "s2_share"]]


def main(argv: list[str] | None = None) -> int:
    import time

    import rasterio
    from pystac_client import Client

    from uummannaq_ice.assets import default_landmask_path

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    parser.add_argument(
        "--regime",
        choices=("winter", "lowsun", "all"),
        default="winter",
        help="winter = February and March below the Level 2 floor",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("rasterio").setLevel(logging.ERROR)
    logging.getLogger("botocore").setLevel(logging.WARNING)

    s2 = sentinel_series(args.archive)
    s2_days = dict(zip(s2.day, s2.s2_ice, strict=True))

    client = Client.open(USGS_STAC)
    candidates = []
    for year in range(2017, 2027):
        for attempt in range(4):
            try:
                for item in client.search(
                    collections=["landsat-c2l1"],
                    bbox=AOI,
                    datetime=f"{year}-01-01/{year}-12-31",
                    limit=100,
                ).items():
                    p = item.properties
                    sun = p.get("view:sun_elevation")
                    if sun is None or sun <= 0:
                        continue
                    if p.get("platform") not in ("LANDSAT_8", "LANDSAT_9"):
                        continue
                    day = item.datetime.date().isoformat()
                    doy = item.datetime.timetuple().tm_yday
                    if not (SEASON_WINDOW[0] <= doy <= SEASON_WINDOW[1]):
                        continue
                    if day not in s2_days:
                        continue
                    month, hour = item.datetime.month, item.datetime.hour
                    candidates.append(
                        {
                            "item": item,
                            "day": day,
                            "sun": sun,
                            "month": month,
                            "hour": hour,
                            "doy": doy,
                        }
                    )
                break
            except Exception:  # pragma: no cover - network-driven
                time.sleep(3 * (attempt + 1))

    if args.regime == "winter":
        chosen = [
            c for c in candidates if c["month"] in (2, 3) and c["sun"] < LEVEL2_FLOOR
        ]
    elif args.regime == "lowsun":
        chosen = [c for c in candidates if c["sun"] < LEVEL2_FLOOR]
    else:
        chosen = candidates
    # One scene per day, the least cloudy.
    by_day: dict[str, dict] = {}
    for c in chosen:
        cloud = c["item"].properties.get("eo:cloud_cover", 100) or 100
        if c["day"] not in by_day or cloud < by_day[c["day"]]["cloud"]:
            by_day[c["day"]] = {**c, "cloud": cloud}
    chosen = sorted(by_day.values(), key=lambda c: c["day"])
    if args.limit:
        chosen = chosen[: args.limit]
    LOGGER.info("%s regime: %d days with a same-day pair", args.regime, len(chosen))

    with rasterio.open(default_landmask_path()) as lm:
        land_source = {"array": lm.read(1), "transform": lm.transform, "crs": lm.crs}

    rows: list[dict] = []
    for index, c in enumerate(chosen, start=1):
        try:
            bands, land, sun = read_scene(c["item"], land_source)
            got = classify(bands, land)
        except Exception as exc:  # pragma: no cover - network-driven
            LOGGER.warning("%s: %s", c["day"], type(exc).__name__)
            continue
        rows.append(
            {
                "day": c["day"],
                "scene": c["item"].id,
                "doy": c["doy"],
                "month": c["month"],
                "hour": c["hour"],
                "sun_elevation": sun,
                "scene_cloud": c["cloud"],
                "s2_ice": s2_days[c["day"]],
                **got,
            }
        )
        LOGGER.info(
            "[%d/%d] %s  sun %5.2f  S2 %.3f  L1 %.3f  share %.2f",
            index,
            len(chosen),
            c["day"],
            sun,
            rows[-1]["s2_ice"],
            rows[-1]["landsat_ice"],
            rows[-1]["landsat_share"],
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        print("nothing measured")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"landsat_l1_{args.regime}.csv"
    frame.to_csv(path, index=False)
    LOGGER.info("written to %s", path)

    kept = frame[frame.landsat_share >= MIN_CLASSIFIED_SHARE].copy()
    kept["diff"] = kept.landsat_ice - kept.s2_ice
    print()
    print(
        f"{len(kept)} of {len(frame)} pairs clear the {MIN_CLASSIFIED_SHARE} share gate"
    )
    if kept.empty:
        return 0
    print()
    print(f"{'day':12s}{'sun':>7s}{'S2':>8s}{'Landsat':>9s}{'diff':>8s}")
    for _, r in kept.sort_values("day").iterrows():
        print(
            f"{r.day:12s}{r.sun_elevation:7.2f}{r.s2_ice:8.3f}{r.landsat_ice:9.3f}{r['diff']:+8.3f}"
        )
    print()
    print(
        f"bias {kept['diff'].mean():+.4f}   RMSE {np.sqrt((kept['diff'] ** 2).mean()):.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
