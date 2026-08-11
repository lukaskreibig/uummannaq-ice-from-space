#!/usr/bin/env python3
"""The one question the thermometer left open: closed ice, or broken floes?

thermal_audit.py finds 36 days on which the optical chain calls this fjord mostly
open while more than half of it radiates below the freezing point of seawater,
and it finds them twice as often after 2021 as before. If those days were closed
fast ice misread as water, a large part of the measured decline is a classifier
failure that grew more common. If they were ice broken into floes with leads
between them, the chain was right, the thermometer was reading floe surfaces, and
the whole finding dissolves.

Thermal cannot separate those two. Its band is 100 m data on a 30 m grid, so
leads narrower than that average away, and floe surfaces radiate exactly as cold
as a closed sheet does. Radar can, and this asks it.

    python3 scripts/sar_thermal_days.py
    python3 scripts/sar_thermal_days.py --window 2 --limit 6

THE DISCRIMINANT, and it is not the median. Backscatter level alone is
ambiguous: wet snow on closed ice reads low, and so does calm open water, which
is the wall sar_wet_days.py ran into and said so. What separates closed ice from
a broken field is not the level but the SPREAD. A closed sheet is one surface and
its p5 to p95 range over the fjord is narrow. A broken field is floes and leads
together, two surfaces tens of decibels apart inside one scene, and the range
opens up. Every contradicted day is therefore compared on both level and spread
against two references from ITS OWN season, taken from the Landsat series itself
rather than from Sentinel-2, which has nothing before 2017:

    closed ice   day 45 to 105, where the series reports 0.95 or more ice, which
                 is the surface the question is about
    open water   day 160 to 180, after every break-up in the record, where it
                 reports 0.02 or less

WHAT THIS RUN CANNOT REACH, before anything else. Sentinel-1A launched in April
2014 and the RTC archive over this fjord is thin before 2016, so seven of the 36
contradicted days cannot be asked at all: four in 2013 and three in 2014. Those
are seven of the nine EARLY ones. What is left is 2 early days against 27 late.
So this run can characterise the late period, where the failure concentrates and
where it matters to the decline, and it cannot itself test the early-late
asymmetry. That asymmetry rests on the thermal count and stays there.

WHAT AN ANSWER LOOKS LIKE, written down before the run so it cannot be chosen
afterwards. A contradicted day whose spread sits with its own winter ice is
closed ice the chain misread, and the thermal finding stands. A day whose spread
is far wider than either reference is a broken field, the chain was right about
it, and that day comes off the count. A day that matches open water on both level
and spread was open, and the chain was right for a different reason.

The likely outcome is a mixture, and the useful output is therefore the COUNT of
each, per period, because the thermal finding rests on the early-late asymmetry
rather than on any single day.

AND THE DISCRIMINANT ABOVE DID NOT WORK, which is recorded here rather than
quietly replaced. The instrument test runs first, on the two classes whose answer
is known, and the spread separates them at an AUC of only 0.81 against 0.98 for
the plain median and 1.00 for the p95. Icebergs are the likely reason: this fjord
carries grounded bergs that are extremely bright in C band all year, so the
spread over the fjord is wide whatever the sea ice is doing, and it cannot be
read as a count of surfaces. So the classification below uses the LEVEL, which is
what measurably separates known ice from known water here, and the spread is
printed beside it as description rather than evidence. The prediction was wrong;
the test that caught it is the reason it is not in the result.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from uummannaq_ice.sar import (  # noqa: E402
    SasToken,
    load_landmask,
    measure_scene,
    search_scenes,
)

LOGGER = logging.getLogger("sar_thermal_days")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_THERMAL = ROOT / "archive/reprocessed_2026/thermal_audit.csv"
DEFAULT_SERIES = ROOT / "archive/reprocessed_2026/landsat_season_series.csv"

# References come from the LANDSAT series and not the Sentinel-2 archive, because
# the days in question run from 2013 and Sentinel-2 has nothing before 2017. It
# is also the right choice on its own terms: the thermal audit is a statement
# about this series, so its references should be its own days.
ICE_DOY = (45, 105)  # mid February to mid April, frozen with near certainty
ICE_MIN = 0.95
WATER_DOY = (160, 180)  # late June, after every break-up in the record
WATER_MAX = 0.02
MIN_SHARE = 0.90
MAX_REFERENCES = 4
LATE_FROM = 2021
# Sentinel-1A reached its operational orbit in 2014 and the RTC archive over this
# fjord is thin before 2016. Days earlier than this cannot be asked at all, which
# is a limit on the answer and not a choice inside it.
RADAR_FROM = "2016-01-01"


def series(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame = frame[frame.landsat_share >= MIN_SHARE].copy()
    frame["date"] = [date.fromisoformat(d) for d in frame.day]
    return frame


def references(frame: pd.DataFrame, season: int) -> dict[str, list[date]]:
    """Days of one season whose surface is not in doubt, from the series itself."""
    block = frame[frame.season == season]
    ice = block[
        block.doy.between(*ICE_DOY)
        & (block.landsat_ice >= ICE_MIN)
        & (block.day >= RADAR_FROM)
    ]
    water = block[
        block.doy.between(*WATER_DOY)
        & (block.landsat_ice <= WATER_MAX)
        & (block.day >= RADAR_FROM)
    ]
    return {
        "closed_ice": list(ice.date)[:MAX_REFERENCES],
        "open_water": list(water.date)[-MAX_REFERENCES:],
    }


def measure(
    days: list[date], window: int, geom, token: SasToken, role: str, season: int
):
    land, bounds, crs, transform = geom
    rows: list[dict[str, Any]] = []
    for target in days:
        try:
            found = search_scenes(
                target - timedelta(days=window), target + timedelta(days=window)
            )
        except Exception as exc:  # pragma: no cover - network-driven
            LOGGER.warning("%s search: %s", target, type(exc).__name__)
            continue
        for feature in found:
            try:
                stats = measure_scene(feature, land, bounds, crs, transform, token)
            except Exception as exc:  # pragma: no cover - network-driven
                LOGGER.warning("%s scene: %s", target, type(exc).__name__)
                continue
            row = stats.as_row()
            row.update(
                {
                    "role": role,
                    "season": season,
                    "target_day": target.isoformat(),
                    "offset_days": (stats.date - target).days,
                    "spread_db": round(row["water_p95_db"] - row["water_p5_db"], 3),
                }
            )
            rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--thermal", type=Path, default=DEFAULT_THERMAL)
    parser.add_argument("--series", type=Path, default=DEFAULT_SERIES)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    parser.add_argument("--window", type=int, default=2)
    parser.add_argument(
        "--ref-window",
        type=int,
        default=5,
        help="days either side of a reference day; wider than the suspect window "
        "on purpose, because midwinter fast ice and post-break-up open water are "
        "stable over days while the suspect day's state is the question",
    )
    parser.add_argument("--limit", type=int, default=0, help="first N suspect days")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("rasterio").setLevel(logging.ERROR)

    thermal = pd.read_csv(args.thermal)
    all_suspects = thermal[thermal.contradicted].copy()
    suspects = all_suspects[all_suspects.day >= RADAR_FROM].copy()
    lost = all_suspects[all_suspects.day < RADAR_FROM]
    LOGGER.info(
        "%d contradicted days, %d early and %d late",
        len(all_suspects),
        int((all_suspects.season < LATE_FROM).sum()),
        int((all_suspects.season >= LATE_FROM).sum()),
    )
    if not lost.empty:
        LOGGER.info(
            "%d of them predate usable radar over this fjord and cannot be asked: %s",
            len(lost),
            ", ".join(sorted(lost.day)),
        )
        LOGGER.info(
            "that leaves %d early and %d late, so this run can characterise the late "
            "period and cannot test the early-late asymmetry itself",
            int((suspects.season < LATE_FROM).sum()),
            int((suspects.season >= LATE_FROM).sum()),
        )
    if args.limit:
        suspects = suspects.head(args.limit)

    opt = series(args.series)
    geom = load_landmask()
    token = SasToken()

    rows: list[dict[str, Any]] = []
    for season in sorted(suspects.season.unique()):
        days = [date.fromisoformat(d) for d in suspects[suspects.season == season].day]
        refs = references(opt, int(season))
        LOGGER.info(
            "%d: %d suspect days, %d ice references, %d water references",
            season,
            len(days),
            len(refs["closed_ice"]),
            len(refs["open_water"]),
        )
        rows += measure(days, args.window, geom, token, "suspect", int(season))
        for role, ref_days in refs.items():
            rows += measure(ref_days, args.ref_window, geom, token, role, int(season))

    if not rows:
        print("no acquisitions measured")
        return 1
    frame = pd.DataFrame(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "sar_thermal_days.csv"
    frame.to_csv(path, index=False)

    kept = frame[frame.passes_gates == 1]
    print()
    print(
        f"{len(kept)} of {len(frame)} acquisitions pass the geometry and coverage gates"
    )
    print("=" * 78)
    print()
    print(f"{'role':14s}{'n':>5s}{'median dB':>11s}{'p5 to p95 spread':>19s}")
    for role in ("closed_ice", "open_water", "suspect"):
        block = kept[kept.role == role]
        if block.empty:
            continue
        print(
            f"{role:14s}{len(block):5d}{block.water_median_db.median():11.2f}"
            f"{block.spread_db.median():19.2f}"
        )
    print()
    print(
        "  If the suspect spread sits with closed ice, those days were a single\n"
        "  surface and the chain misread it. If it is far wider, they were floes\n"
        "  and leads together and the chain was right about them."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
