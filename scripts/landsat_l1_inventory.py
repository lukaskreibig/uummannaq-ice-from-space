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
    python3 scripts/landsat_l1_inventory.py --reach

The default mode counts what is there for the cross-check and then stops at the
access wall. That wall has since been climbed with a requester-pays AWS profile,
so the section about it below records what it cost to get in rather than a dead
end, and landsat_l1_crosscheck.py runs through it.

`--reach` asks the separate question of how far back the archive itself goes and
whether a longer series could be built from it. It is catalogue metadata only,
no pixels, so it is cheap and free. It exists because the answer decides what
landsat_season_series.py is allowed to do, and the answer is not the obvious one:
there is plenty of data and almost no way to join it.
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


# The instrument behind each Landsat id prefix. MSS has no shortwave infrared at
# all, so NDSI cannot even be formed on it, which rules out four of the sensors
# before any calibration argument starts.
INSTRUMENTS = {
    "LM": ("MSS", False),
    "LT": ("TM", True),
    "LE": ("ETM+", True),
    "LC": ("OLI", True),
}
ARCHIVE_FROM = 1972
# Degrees of sun elevation within which two scenes count as the same overpass.
SAME_PASS_SUN = 5.0


def reach(out: Path) -> int:
    """How far back does the catalogue go, and can the sensors be joined?"""
    from pystac_client import Client

    client = Client.open(USGS_STAC)
    rows: list[dict] = []
    for year in range(ARCHIVE_FROM, 2027):
        for attempt in range(4):
            try:
                for item in client.search(
                    collections=["landsat-c2l1"],
                    bbox=AOI,
                    datetime=f"{year}-01-01/{year}-12-31",
                    limit=100,
                ).items():
                    p = item.properties
                    when = item.datetime
                    sun = p.get("view:sun_elevation")
                    if when is None or sun is None or sun <= 0:
                        continue
                    doy = when.timetuple().tm_yday
                    if not (SEASON_WINDOW[0] <= doy <= SEASON_WINDOW[1]):
                        continue
                    name, swir = INSTRUMENTS.get(item.id[:2], ("?", False))
                    rows.append(
                        {
                            "id": item.id,
                            "day": when.date().isoformat(),
                            "season": year,
                            "doy": doy,
                            "hour": when.hour,
                            "instrument": name,
                            "has_swir": swir,
                            "sun_elevation": sun,
                            "cloud": p.get("eo:cloud_cover"),
                            "tier": item.id[-2:],
                        }
                    )
                break
            except Exception:  # pragma: no cover - network-driven
                time.sleep(3 * (attempt + 1))

    frame = pd.DataFrame(rows)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "landsat_reach.csv"
    frame.to_csv(path, index=False)

    print("How far back the archive reaches over this fjord, day 45 to 180")
    print("=" * 74)
    print(
        f"{'instrument':12s}{'SWIR':>6s}{'seasons':>9s}{'first':>7s}{'last':>6s}{'scenes':>8s}{'median/season':>15s}"
    )
    for name in ("MSS", "TM", "ETM+", "OLI"):
        block = frame[frame.instrument == name]
        if block.empty:
            continue
        per = block.groupby("season").size()
        print(
            f"{name:12s}{'yes' if block.has_swir.iloc[0] else 'NO':>6s}"
            f"{block.season.nunique():9d}{block.season.min():7d}{block.season.max():6d}"
            f"{len(block):8d}{per.median():15.0f}"
        )
    print()
    modern = frame[frame.season >= 1990]
    per_season = modern.groupby("season").size()
    print(
        f"So the data is there. From 1990 the archive holds "
        f"{modern.season.nunique()} seasons over this AOI, at a median of "
        f"{per_season.median():.0f} scenes\ninside the window and a range of "
        f"{per_season.min()} to {per_season.max()}. What is missing is any way to "
        "join one\nsensor to the next."
    )
    print()
    print("Same-day scenes from two different instruments, which is what a fixed")
    print("threshold would need in order to survive a sensor change:")
    print()
    by_day = frame.groupby("day").instrument.apply(set)
    order = ["MSS", "TM", "ETM+", "OLI"]
    for i, a in enumerate(order):
        for b in order[i + 1 :]:
            days = [d for d, s in by_day.items() if a in s and b in s]
            same_pass, clear = 0, 0
            for d in days:
                block = frame[frame.day == d]
                left = block[block.instrument == a]
                right = block[block.instrument == b]
                # A bbox search returns scenes whose footprint merely clips this
                # AOI, including neighbouring WRS-2 paths acquired at a wholly
                # different local time. Over a fixed point the sun elevation is
                # fixed by the date and the hour, so a pair that disagrees about
                # it by more than a few degrees did not see this fjord together.
                pairs = [
                    (x, y)
                    for x in left.itertuples()
                    for y in right.itertuples()
                    if abs(x.sun_elevation - y.sun_elevation) <= SAME_PASS_SUN
                ]
                if not pairs:
                    continue
                same_pass += 1
                if any(x.cloud < 20 and y.cloud < 20 for x, y in pairs):
                    clear += 1
            print(
                f"  {a:5s} against {b:5s}{len(days):5d} days share a date, "
                f"{same_pass} are the same overpass, {clear} of those under 20 percent cloud"
            )
    print()
    print("And the two ETM+ against OLI overpasses, in full, because they are the")
    print("only bridge the whole archive offers between two SWIR sensors here:")
    print()
    for day in ("2013-03-30", "2019-06-06"):
        for row in frame[frame.day == day].sort_values("sun_elevation").itertuples():
            if row.instrument in ("ETM+", "OLI"):
                print(
                    f"  {day}  {row.instrument:5s} {row.hour:02d}h UTC  "
                    f"sun {row.sun_elevation:5.1f}  cloud {row.cloud:5.1f}"
                )
        print()
    print(
        "Neither is enough to carry a threshold across the boundary, and the reason\n"
        "is not the one this script first claimed.\n"
        "\n"
        "  2013-03-30 is as clean a pair as could be asked for, same hour, same sun,\n"
        "  both under one percent cloud, and commissioning_check.py ran both scenes\n"
        "  through this pipeline. They AGREE: green 0.223 against 0.226, near\n"
        "  infrared 0.120 against 0.115, ice 0.112 against 0.098. So ETM+ and OLI do\n"
        "  not disagree over this fjord, which is the opposite of what an earlier\n"
        "  version of this text asserted.\n"
        "\n"
        "  What one pair cannot do is calibrate. It fixes the relationship at ONE\n"
        "  surface state, and that state turns out to be dark ice near the bottom of\n"
        "  the range. Agreement there says nothing about whether the two sensors\n"
        "  agree over bright snow covered fast ice, which is where the thresholds\n"
        "  actually decide, or over open water. A gain and an offset across the\n"
        "  dynamic range cannot be fitted from a single point.\n"
        "\n"
        "  2019-06-06 is the only other candidate and is worse: 6 June, midnight sun\n"
        "  at 10 degrees elevation, an hour apart, over ice already breaking up. A\n"
        "  threshold anchored there says nothing about February fast ice.\n"
        "\n"
        "The sensor boundaries fall in 1999 and 2013, which is exactly where an\n"
        "early-late split of a long record would sit, so an uncalibrated join would\n"
        "be indistinguishable from the trend it is meant to measure. Steiro et al.\n"
        "(2021) reached back to 1985 on this fjord by setting thresholds per image\n"
        "from histogram analysis, which sidesteps calibration by putting an analyst\n"
        "inside every measurement. That is a study. This is a pipeline, and it takes\n"
        "the one extension that crosses no boundary at all: OLI alone, 2014 to 2026,\n"
        "in landsat_season_series.py."
    )
    print(f"\nwritten to {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    parser.add_argument(
        "--reach", action="store_true", help="how far back the catalogue goes"
    )
    args = parser.parse_args(argv)
    if args.reach:
        return reach(args.out)

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
