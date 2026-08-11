#!/usr/bin/env python3
"""What Landsat Level 1 could answer here, and what it takes to reach it.

landsat-crosscheck.md compares against Collection 2 Level **2**, and that
comparison has a structural hole it does not state loudly enough. Level 2
surface reflectance is not produced above a solar zenith of 76 degrees, so the
82 pairs behind that page span sun elevations of 14.3 to 42.5 degrees. The 28
February and March scenes that report almost no ice under a sky the pipeline
itself calls clear all sit BELOW that floor. The second instrument was never
asked about the one regime where the first one is unexplained.

Level 1 has no such floor, and it is also the methodologically closer product:
the pipeline reads Sentinel-2 L1C, which is top of atmosphere, so a Level 1
comparison changes the sensor and nothing else, where Level 2 changes the sensor
and the atmospheric correction together.

    python3 scripts/landsat_l1_inventory.py

This counts what is there and then stops at the wall, because the wall is real
and is not something a script can climb.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / "archive/reprocessed_2026/summary.csv"

USGS_STAC = "https://landsatlook.usgs.gov/stac-server"
AOI = [-52.374, 70.629, -51.905, 70.799]
SEASON_WINDOW = (45, 180)

# The floor above which Level 2 surface reflectance is produced at all, in sun
# elevation. Everything below it is invisible to the existing cross-check.
LEVEL2_FLOOR = 14.06
SEASONS = range(2017, 2027)


def inventory() -> pd.DataFrame:
    from pystac_client import Client

    client = Client.open(USGS_STAC)
    rows: list[dict] = []
    for year in SEASONS:
        for attempt in range(4):
            try:
                for item in client.search(
                    collections=["landsat-c2l1"],
                    bbox=AOI,
                    datetime=f"{year}-01-01/{year}-12-31",
                    limit=100,
                ).items():
                    p = item.properties
                    rows.append(
                        {
                            "id": item.id,
                            "datetime": item.datetime,
                            "platform": p.get("platform"),
                            "sun_elevation": p.get("view:sun_elevation"),
                            "cloud": p.get("eo:cloud_cover"),
                        }
                    )
                break
            except Exception:  # pragma: no cover - network-driven
                time.sleep(3 * (attempt + 1))
    frame = pd.DataFrame(rows)
    stamp = pd.to_datetime(frame.datetime, utc=True)
    frame["day"] = stamp.dt.date.astype(str)
    frame["doy"] = stamp.dt.dayofyear
    frame["hour"] = stamp.dt.hour
    frame["month"] = stamp.dt.month
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    args = parser.parse_args(argv)

    frame = inventory()
    lo, hi = SEASON_WINDOW
    window = frame[
        (frame.doy >= lo)
        & (frame.doy <= hi)
        & (frame.sun_elevation > 0)
        & (frame.platform.isin(["LANDSAT_8", "LANDSAT_9"]))
    ]

    archive = pd.read_csv(args.archive)
    s2_days = set(
        pd.to_datetime(
            archive.timestamp.astype(str), format="%Y%m%dT%H%M%S"
        ).dt.date.astype(str)
    )
    pairs = window[window.day.isin(s2_days)]
    low = pairs[pairs.sun_elevation < LEVEL2_FLOOR]
    winter = low[low.month.isin([2, 3])]

    print("What Landsat Collection 2 Level 1 holds over this fjord")
    print("=" * 74)
    print(f"{len(frame):5d} scenes in the catalogue, all platforms, all year")
    print(f"{len(window):5d} Landsat 8 or 9, daylight, inside day {lo} to {hi}")
    print(
        f"      sun elevation {window.sun_elevation.min():.2f} to "
        f"{window.sun_elevation.max():.2f}, against 14.3 to 42.5 for the Level 2 pairs"
    )
    print(
        f"{int((window.sun_elevation < LEVEL2_FLOOR).sum()):5d} below the Level 2 floor of {LEVEL2_FLOOR}"
    )
    print()
    print("Those low-sun scenes are two different regimes, not one:")
    table = (
        window[window.sun_elevation < LEVEL2_FLOOR]
        .groupby(["hour", "month"])
        .size()
        .unstack(fill_value=0)
    )
    print(table.to_string())
    print()
    print(
        "Hour 15 in February and March is genuine low winter sun over fast ice.\n"
        "Hours 23 and 0 in May and June are midnight sun over ice about to break\n"
        "up. Same sun elevation, different surface, and they must not be pooled."
    )
    print()
    print("Same-day pairs with a Sentinel-2 scene in the archive")
    print("-" * 74)
    print(f"{pairs.day.nunique():5d} days")
    print(f"{low.day.nunique():5d} of them below the Level 2 floor")
    print(
        f"{winter.day.nunique():5d} of those in February or March, which is the open regime"
    )

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "landsat_l1_inventory.csv"
    window.to_csv(path, index=False)
    print(f"\nwritten to {path}")

    print()
    print("And the wall")
    print("=" * 74)
    print(
        "Neither route to the pixels is open without a credential this repository\n"
        "does not have, and both were tested rather than assumed.\n"
        "\n"
        "  https://landsatlook.usgs.gov/data/...  redirects to ers.cr.usgs.gov/login.\n"
        "  A USGS EROS account is free, but the asset is not anonymous.\n"
        "\n"
        "  s3://usgs-landsat/...  is requester pays. A windowed read of three bands\n"
        "  and the QA layer over this AOI is a few hundred kilobytes per scene, so\n"
        "  the bill for the whole comparison is cents, but it needs an AWS account.\n"
        "\n"
        "There is no third route. The Planetary Computer carries landsat-c2-l1 as\n"
        "MSS only, 1972 to 2013, which has no SWIR band and ends twelve years\n"
        "before Sentinel-2 launches. The Albers top-of-atmosphere collections\n"
        "return zero scenes here, because that ARD grid does not cover Greenland."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
