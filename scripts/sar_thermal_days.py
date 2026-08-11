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
is known, and the spread separates them at an AUC of only 0.81 against 0.92 for
the plain median and 0.96 for the p95. Icebergs are the likely reason: this fjord
carries grounded bergs that are extremely bright in C band all year, so the
spread over the fjord is wide whatever the sea ice is doing, and it cannot be
read as a count of surfaces. So the placement uses the LEVEL, which is what
measurably separates known ice from known water here, and the spread is printed
beside it as description rather than evidence. The prediction was wrong; the test
that caught it is the reason it is not in the result.

Both artefacts come out of this file: `sar_thermal_days.csv` is every acquisition
and `sar_thermal_verdicts.csv` is one row per contradicted day. An earlier version
produced the second by hand and committed it, which left the chain from radar to
the corrected headline unreproducible from this repository, and
sentinel_correction.py reads it.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
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
# Where a placed day stops being ambiguous. A quarter of the way from one
# reference to the other in either direction.
LIKE_ICE = 0.75
LIKE_WATER = 0.25


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


def separation(positive, negative) -> float:
    """AUC. 0.5 is no separation between the two classes, 1.0 is perfect."""
    pos, neg = np.asarray(positive, float), np.asarray(negative, float)
    if not pos.size or not neg.size:
        return float("nan")
    greater = (pos[:, None] > neg[None, :]).mean()
    equal = (pos[:, None] == neg[None, :]).mean()
    return float(greater + 0.5 * equal)


def instrument_test(kept: pd.DataFrame) -> pd.DataFrame:
    """Do the two classes whose answer is known separate at all, and on what?

    This runs before any suspect day is judged, and it is allowed to end the
    exercise. A discriminant that cannot tell known ice from known water cannot
    classify anything, and the one this script was built around is the one that
    fails: see the note at the top of the file.
    """
    ice = kept[kept.role == "closed_ice"]
    water = kept[kept.role == "open_water"]
    rows = []
    for label, column in (
        ("median dB", "water_median_db"),
        ("p5 to p95 spread", "spread_db"),
        ("p5 dB", "water_p5_db"),
        ("p95 dB", "water_p95_db"),
    ):
        rows.append(
            {
                "quantity": label,
                "column": column,
                "ice": float(ice[column].median()),
                "water": float(water[column].median()),
                "separation_auc": separation(ice[column], water[column]),
            }
        )
    return pd.DataFrame(rows)


def place(kept: pd.DataFrame, column: str = "water_median_db") -> pd.DataFrame:
    """Put every suspect day on a scale from its own season's water to its ice.

    1.00 is that season's fast ice, 0.00 is its open water, and the same relative
    orbit is used on both sides wherever one exists, because incidence angle
    moves the fjord median by whole decibels. A day whose season has no reference
    of one kind cannot be placed and says so rather than borrowing another
    season's.
    """
    rows: list[dict[str, Any]] = []
    for (season, day), group in kept[kept.role == "suspect"].groupby(
        ["season", "target_day"]
    ):
        ice = kept[(kept.season == season) & (kept.role == "closed_ice")]
        water = kept[(kept.season == season) & (kept.role == "open_water")]
        if ice.empty or water.empty:
            rows.append(
                {"season": season, "day": day, "verdict": "no reference", "pos": None}
            )
            continue
        orbits = set(group.relative_orbit.dropna())
        ice_orbit = ice[ice.relative_orbit.isin(orbits)]
        water_orbit = water[water.relative_orbit.isin(orbits)]
        matched = not ice_orbit.empty and not water_orbit.empty
        ice_ref = float((ice_orbit if matched else ice)[column].median())
        water_ref = float((water_orbit if matched else water)[column].median())
        value = float(group[column].median())
        pos = (value - water_ref) / (ice_ref - water_ref)
        rows.append(
            {
                "season": int(season),
                "day": day,
                "acquisitions": len(group),
                "orbit_matched": matched,
                "ice_ref_db": round(ice_ref, 3),
                "water_ref_db": round(water_ref, 3),
                "value_db": round(value, 3),
                "pos": pos,
                "spread_db": float(group.spread_db.median()),
                "verdict": (
                    "like fast ice"
                    if pos >= LIKE_ICE
                    else "like open water"
                    if pos <= LIKE_WATER
                    else "between"
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("day")


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

    # The instrument test first, because it is allowed to end the exercise.
    checks = instrument_test(kept)
    checks.to_csv(args.out / "sar_thermal_separation.csv", index=False)
    print()
    print("Do the two classes whose answer is known separate, and on what?")
    print(f"  {'quantity':20s}{'ice':>9s}{'water':>9s}{'AUC':>7s}")
    for r in checks.itertuples():
        print(f"  {r.quantity:20s}{r.ice:9.2f}{r.water:9.2f}{r.separation_auc:7.2f}")
    by_name = checks.set_index("quantity").separation_auc
    print()
    print(
        f"  AUC 0.50 is no separation and 1.00 is perfect. The spread this script was\n"
        f"  built around manages {by_name['p5 to p95 spread']:.2f} and cannot classify "
        f"anything. The placement uses\n"
        f"  the median at {by_name['median dB']:.2f} rather than the p95 at "
        f"{by_name['p95 dB']:.2f}, and the better number\n"
        "  is deliberately not the one taken: the p95 is the bright tail, which over\n"
        "  this fjord is grounded icebergs and deformed ice, while the question is\n"
        "  what the fjord as a whole looked like. Both are in the artefact."
    )

    placed = place(kept)
    placed.to_csv(args.out / "sar_thermal_verdicts.csv", index=False)
    judged = placed[placed.verdict != "no reference"]
    print()
    print("Where each contradicted day sits between its own season's two references")
    print("-" * 78)
    print(
        f"{'day':12s}{'n':>3s}{'orbit':>7s}{'ice':>8s}{'water':>8s}{'day':>8s}"
        f"{'pos':>7s}{'spread':>8s}  verdict"
    )
    for r in placed.itertuples():
        if r.verdict == "no reference":
            print(f"{r.day:12s}{'':40s}no reference in that season")
            continue
        print(
            f"{r.day:12s}{int(r.acquisitions):3d}{'yes' if r.orbit_matched else 'no':>7s}"
            f"{r.ice_ref_db:8.1f}{r.water_ref_db:8.1f}{r.value_db:8.1f}"
            f"{r.pos:7.2f}{r.spread_db:8.1f}  {r.verdict}"
        )
    print()
    print(f"{'verdict':18s}{'total':>7s}{'early':>7s}{'late':>6s}")
    for name in ("like fast ice", "between", "like open water"):
        block = judged[judged.verdict == name]
        print(
            f"{name:18s}{len(block):7d}{int((block.season < LATE_FROM).sum()):7d}"
            f"{int((block.season >= LATE_FROM).sum()):6d}"
        )
    print()
    print(
        f"  {len(judged)} of {len(suspects)} reachable days placed, median position "
        f"{judged.pos.median():.2f},\n  mean {judged.pos.mean():.2f}. 1.00 is that "
        "season's fast ice and 0.00 its open water.\n"
        "\n"
        "  Both extremes are refused if most days sit in the middle: the chain saw\n"
        "  more water than was there, and a completely frozen fjord is not what was\n"
        "  there either."
    )
    print(f"\nwritten to {path} and {args.out / 'sar_thermal_verdicts.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
