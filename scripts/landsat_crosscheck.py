#!/usr/bin/env python3
"""Run the same classification on Landsat, on the same day, and compare.

The optical series has never been checked against a second optical instrument.
The Sentinel-1 cross-check bounds one error and cannot calibrate the record,
and the season-end anchors measure the pipeline against itself. This measures it
against Landsat 8 and 9 on days both satellites saw the fjord.

    python3 scripts/landsat_crosscheck.py
    python3 scripts/landsat_crosscheck.py --max-cloud 10 --out out/archive

What it does, per pair: reads Landsat green, NIR and SWIR1 through a window over
the same land mask the optical pipeline uses, in the same CRS (EPSG:32622, so no
warping of the imagery), applies the SAME indices, the SAME thresholds and the
SAME brightness gate, and reports the ice fraction over the classified cells.

Three things make this a real check rather than a restatement:

  different optics      OLI is not MSI. Different band passes, different
                        detectors, a different orbit and a different overpass
                        time, usually within two hours here.
  different atmosphere  Landsat Collection 2 Level 2 is surface reflectance from
                        LaSRC. The pipeline reads Sentinel-2 L1C, which is top of
                        atmosphere. Nothing is shared between the two corrections.
  different cloud mask  CFMask in the QA_PIXEL band against a UNetMobV2 trained
                        on CloudSEN12. An agreement is not two runs of one idea.

And one thing that keeps it honest: the thresholds were derived on Sentinel-2 TOA
and are applied here to Landsat surface reflectance unchanged. That is only
defensible because the controls say so. Days where the answer is not in doubt,
April with a closed fjord and July with an open one, have to reproduce, or
nothing else printed here means anything. They are measured first and printed
first for that reason.

What the comparison cannot do: both instruments are optical, and liquid water on
ice absorbs in the near infrared whichever satellite looks at it. Two optical
sensors agreeing that a surface reads as water establishes that it read as water,
not that the fjord was open. Only radar can separate those, and it has its own
wet-surface problem.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject
from rasterio.windows import from_bounds

from uummannaq_ice.assets import default_landmask_path

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

DEFAULT_ARCHIVE = Path("archive/reprocessed_2026/summary.csv")
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
TOKEN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/landsat-c2-l2"

AOI = {
    "type": "Polygon",
    "coordinates": [
        [
            [-52.374, 70.629],
            [-51.905, 70.629],
            [-51.905, 70.799],
            [-52.374, 70.799],
            [-52.374, 70.629],
        ]
    ],
}

# The pipeline's own thresholds, unchanged. See methods.md section 5.
NDSI_ICE = 0.40
NDWI_WATER = 0.20
VIS_BRIGHT_MIN = 0.10
NIR_BRIGHT_MIN = 0.17

# The pipeline's visibility gate, applied to both sides.
MIN_CLASSIFIED_SHARE = 0.30

# Collection 2 Level 2 surface reflectance scaling, from the USGS product guide.
SR_SCALE, SR_OFFSET = 0.0000275, -0.2

# Groups, by what the answer is already known to be. See
# scripts/season_end_calibration.py for why April and July are safe anchors.
APRIL_ANCHOR = (91, 110)
JULY_ANCHOR = (182, 213)
WINTER = (45, 90)

# A visibility gate on the LANDSAT side, and the number was measured rather than
# chosen. The scene-level cloud percentage is over a 185 km tile and says little
# about a 15 km fjord inside it: the two controls that disagree worst, 2025-04-19
# at -0.37 and 2025-04-09 at -0.12, both pass a 20 percent scene-cloud filter.
# Sorting the controls by the share of the fjord Landsat actually classified
# separates them cleanly. Below 0.60 the control RMSE is 0.18; above 0.95 it is
# 0.004. At 0.90 the controls sit at RMSE 0.026, which is the noise floor every
# disagreement below is measured against.
MIN_LANDSAT_SHARE = 0.90


# One SAS token for the whole collection, fetched once and reused, rather than
# one signing request per asset. Signing every asset separately is four requests
# per scene and the endpoint answers 429 long before the run finishes: the first
# version of this script lost 139 of 617 days that way and reported a tighter
# agreement than it had earned.
_TOKEN: dict[str, Any] = {"value": None, "expiry": ""}
_TOKEN_LOCK = Lock()


def _token() -> str:
    with _TOKEN_LOCK:
        if (
            _TOKEN["value"]
            and _TOKEN["expiry"] > datetime.now(timezone.utc).isoformat()
        ):
            return str(_TOKEN["value"])
        for attempt in range(6):
            try:
                with urllib.request.urlopen(TOKEN_URL, timeout=60) as r:
                    doc = json.load(r)
                _TOKEN["value"] = doc["token"]
                _TOKEN["expiry"] = doc.get("msft:expiry", "")
                return str(_TOKEN["value"])
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == 5:
                    raise
                time.sleep(2**attempt)
        raise RuntimeError("could not obtain a SAS token")


def sign(href: str) -> str:
    return f"{href}?{_token()}"


def search(day: str) -> list[dict[str, Any]]:
    body = {
        "collections": ["landsat-c2-l2"],
        "intersects": AOI,
        "datetime": f"{day}T00:00:00Z/{day}T23:59:59Z",
        "limit": 10,
    }
    req = urllib.request.Request(
        STAC,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r).get("features", [])


def landsat_scene(day: str, bounds, land_src) -> dict[str, Any] | None:
    """Classify one Landsat scene over the AOI with the pipeline's own rules."""
    feats = search(day)
    if not feats:
        return None
    item = min(feats, key=lambda f: f["properties"].get("eo:cloud_cover", 100))

    arrays: dict[str, np.ndarray] = {}
    land: np.ndarray | None = None
    for name in ("green", "nir08", "swir16", "qa_pixel"):
        with rasterio.open(sign(item["assets"][name]["href"])) as src:
            window = from_bounds(*bounds, transform=src.transform)
            arrays[name] = src.read(1, window=window).astype("float64")
            if land is None:
                land = np.zeros(arrays[name].shape, dtype="uint8")
                reproject(
                    land_src["array"],
                    land,
                    src_transform=land_src["transform"],
                    src_crs=land_src["crs"],
                    dst_transform=src.window_transform(window),
                    dst_crs=src.crs,
                    resampling=Resampling.nearest,
                )

    if land is None:  # the loop above always fills it on its first pass
        raise RuntimeError(f"no bands read for {day}")

    sr = {k: arrays[k] * SR_SCALE + SR_OFFSET for k in ("green", "nir08", "swir16")}
    qa = arrays["qa_pixel"].astype("uint16")
    # QA_PIXEL bits: 0 fill, 1 dilated cloud, 3 cloud, 4 cloud shadow.
    unusable = (
        ((qa >> 3) & 1) | ((qa >> 4) & 1) | ((qa >> 1) & 1) | ((qa >> 0) & 1)
    ).astype(bool)
    visible = (~unusable) & (land == 0)

    with np.errstate(divide="ignore", invalid="ignore"):
        ndsi = (sr["green"] - sr["swir16"]) / (sr["green"] + sr["swir16"])
        ndwi = (sr["green"] - sr["nir08"]) / (sr["green"] + sr["nir08"])
    bright = (sr["green"] > VIS_BRIGHT_MIN) & (sr["nir08"] > NIR_BRIGHT_MIN)
    ice = ((ndsi > NDSI_ICE) & bright) & visible
    water = (ndwi > NDWI_WATER) & (~ice) & visible

    classified = int(ice.sum()) + int(water.sum())
    total = int((land == 0).sum())
    return {
        "landsat_id": item["id"],
        "landsat_cloud": item["properties"].get("eo:cloud_cover"),
        "landsat_sun": item["properties"].get("view:sun_elevation"),
        "landsat_ice": (int(ice.sum()) / classified) if classified else float("nan"),
        "landsat_share": (classified / total) if total else 0.0,
    }


def load_archive(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    for col in ("solid_px", "light_px", "water_px", "cloud_px", "land_px", "nodata_px"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
    day = pd.to_datetime(frame["timestamp"].astype(str).str[:8], format="%Y%m%d")
    frame["date"] = day.dt.date
    frame["doy"] = day.dt.dayofyear
    frame["season"] = day.dt.year
    classified = frame.solid_px + frame.light_px + frame.water_px
    grid = classified + frame.cloud_px + frame.land_px + frame.nodata_px
    frame["s2_ice"] = (frame.solid_px + frame.light_px).divide(
        classified.where(classified > 0)
    )
    frame["s2_share"] = classified.divide(grid.where(grid > 0))
    return frame[frame.s2_share >= MIN_CLASSIFIED_SHARE].copy()


def group_of(row) -> str:
    doy, ice = row.doy, row.s2_ice
    if APRIL_ANCHOR[0] <= doy <= APRIL_ANCHOR[1]:
        return "april anchor, outlier" if ice < 0.90 else "april anchor, control"
    if JULY_ANCHOR[0] <= doy <= JULY_ANCHOR[1]:
        return "july anchor, control"
    if WINTER[0] <= doy <= WINTER[1]:
        return "winter, anomaly" if ice < 0.15 else "winter, ordinary"
    return "season, ordinary"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    parser.add_argument("--max-cloud", type=float, default=20.0)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0, help="0 means all pairs")
    args = parser.parse_args(argv)

    if not args.archive.exists():
        print(f"archive not found: {args.archive}")
        return 2

    s2 = load_archive(args.archive)
    s2["group"] = s2.apply(group_of, axis=1)

    with rasterio.open(default_landmask_path()) as lm:
        bounds = lm.bounds
        land_src = {"array": lm.read(1), "transform": lm.transform, "crs": lm.crs}

    days = sorted({str(d) for d in s2.date})
    if args.limit:
        days = days[: args.limit]
    print(
        f"{len(s2)} Sentinel-2 scenes clear the gate, checking {len(days)} days against Landsat"
    )

    def one(day: str):
        try:
            return day, landsat_scene(day, bounds, land_src)
        except Exception as exc:  # a single unreadable scene must not kill the run
            return day, {"error": f"{type(exc).__name__}: {exc}"}

    results, errors, empty = {}, {}, 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, (day, res) in enumerate(pool.map(one, days), 1):
            if res is None:
                empty += 1
            elif "error" in res:
                errors[day] = res["error"]
            else:
                results[day] = res
            if i % 25 == 0:
                print(f"  {i} of {len(days)} days")

    # Never drop a scene quietly. A cross-check that silently loses half its
    # sample reports a tighter agreement than it earned.
    print()
    print(
        f"{len(results)} days measured, {empty} without a Landsat scene, {len(errors)} failed"
    )
    if errors:
        from collections import Counter

        for kind, n in Counter(e.split(":")[0] for e in errors.values()).most_common():
            print(f"    {n:4d} x {kind}")
        for day, err in list(errors.items())[:3]:
            print(f"    example {day}: {err[:110]}")

    rows = []
    for _, r in s2.iterrows():
        res = results.get(str(r.date))
        if not res or "error" in res or res.get("landsat_cloud") is None:
            continue
        if res["landsat_cloud"] > args.max_cloud:
            continue
        rows.append(
            {
                "date": r.date,
                "season": r.season,
                "doy": r.doy,
                "group": r.group,
                "s2_ice": r.s2_ice,
                "s2_share": r.s2_share,
                **res,
            }
        )
    paired = pd.DataFrame(rows).dropna(subset=["landsat_ice"])
    paired = paired[paired.landsat_share >= MIN_LANDSAT_SHARE]

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "landsat_crosscheck.csv"
    paired.to_csv(target, index=False)

    print()
    print(
        f"{len(paired)} usable pairs under {args.max_cloud:.0f} percent Landsat cloud"
    )
    print(f"written to {target}")
    print()

    order = [
        "april anchor, control",
        "july anchor, control",
        "april anchor, outlier",
        "winter, anomaly",
        "winter, ordinary",
        "season, ordinary",
    ]
    print(
        f"{'group':24s} {'n':>4s} {'S2':>8s} {'Landsat':>8s} {'bias':>8s} {'RMSE':>8s}"
    )
    for name in order:
        block = paired[paired.group == name]
        if block.empty:
            continue
        diff = block.landsat_ice - block.s2_ice
        print(
            f"{name:24s} {len(block):4d} {block.s2_ice.mean():8.4f} "
            f"{block.landsat_ice.mean():8.4f} {diff.mean():+8.4f} "
            f"{float(np.sqrt((diff**2).mean())):8.4f}"
        )
    print()
    controls = paired[paired.group.str.endswith("control")]
    noise = float("nan")
    if len(controls) > 2:
        d = controls.landsat_ice - controls.s2_ice
        noise = float(np.sqrt((d**2).mean()))
        print(
            f"Controls alone: n = {len(controls)}, bias {d.mean():+.4f}, "
            f"RMSE {noise:.4f}, worst {float(d.abs().max()):.4f}"
        )
        print(
            "These are the days whose answer was not in doubt, and this RMSE is the\n"
            "noise floor. Two instruments, two atmospheric corrections and two cloud\n"
            "masks agreeing this closely is what makes the rest of the table readable."
        )
    print()
    outliers = paired[paired.group == "april anchor, outlier"]
    if len(outliers):
        d = outliers.landsat_ice - outliers.s2_ice
        print(f"April outliers: n = {len(outliers)}, bias {d.mean():+.4f}")
        for _, r in outliers.sort_values("s2_ice").iterrows():
            gap = r.landsat_ice - r.s2_ice
            times = (
                f"{abs(gap) / noise:.0f}x the control noise" if noise == noise else ""
            )
            print(
                f"    {r.date}  S2 {r.s2_ice:.4f}  Landsat {r.landsat_ice:.4f}  "
                f"{gap:+.4f}   {times}"
            )
        print(
            "\nA second instrument, a second atmospheric correction and a second cloud\n"
            "mask reading the same surface the same way is evidence about the surface,\n"
            "not about the chain. It does not establish that the fjord was open: both\n"
            "instruments are optical, and meltwater on ice absorbs in the near infrared\n"
            "whichever one is looking."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
