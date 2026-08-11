#!/usr/bin/env python3
"""Ask radar the one question the optics cannot answer.

Two optical instruments now agree that on four April days this fjord read as
half open water, weeks before that season had ever broken up. Landsat sees the
same surface as Sentinel-2 and slightly wetter, so the reading is not a
Sentinel-2 defect. What neither can say is whether the fjord was OPEN or whether
it was still frozen under a wet surface, because liquid water absorbs in the near
infrared for every optical sensor alike.

Sentinel-1 can, in principle. This asks it.

    python3 scripts/sar_wet_days.py
    python3 scripts/sar_wet_days.py --window 3 --out out/archive

The design, and why it is not the design of validate_sar.py:

  Anchors from the SAME season, not from the record. sar-validation.md compares
  suspect days against ice anchors pooled over nine winters and water anchors
  from June and July, which leaves a seasonal confounder it says so itself. Here
  each April day is compared against February and March days of ITS OWN season,
  chosen where the optical chain reported a solidly frozen fjord. The question
  is not "does this look like ice somewhere in the record" but "does this look
  like the ice that was here six weeks ago".

  Same relative orbit where one exists. Incidence angle alone moves the fjord
  median by whole decibels, and the published orbit stratification shows water
  anchors 3.6 dB apart between orbits 25 and 90. A within-orbit comparison holds
  the geometry fixed. Where no same-orbit reference exists the comparison is
  still printed, and marked.

What a result would mean, and the honest caveat first: wet snow depresses C band
backscatter too. So a day that reads LOW on radar is ambiguous between open water
and a wet surface, and only a day that reads like its own winter ice is decisive.
This test can therefore confirm "the ice was still there" but cannot confirm
"the fjord was open". An inconclusive answer is the likely one and it is still
worth having, because the current pages assert nothing at all about these days.
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

from uummannaq_ice.sar import (  # noqa: E402
    SasToken,
    load_landmask,
    measure_scene,
    search_scenes,
)

LOGGER = logging.getLogger("sar_wet_days")

DEFAULT_ARCHIVE = Path("archive/reprocessed_2026/summary.csv")

# The days two optical instruments call half open, from
# docs/landsat-crosscheck.md. Sentinel-2 first, Landsat second.
WET_DAYS: dict[str, tuple[float, float]] = {
    "2023-04-11": (0.5952, 0.4158),
    "2023-04-12": (0.5207, 0.3756),
    "2025-04-17": (0.7128, 0.5876),
    "2025-04-18": (0.8305, 0.6498),
}

# The one winter anomaly where the two cross-checks contradict each other:
# both optical sensors call it open, sar-validation.md calls the group fast ice.
CONTESTED = {"2025-03-15": (0.0032, 0.0029)}

# A reference day is a February or March day of the same season where the
# optical chain saw a solidly frozen fjord. Ice that reads this on radar is the
# ice this comparison is asking about.
REFERENCE_MONTHS = (2, 3)
REFERENCE_MIN_ICE = 0.95
MIN_CLASSIFIED_SHARE = 0.30
MAX_REFERENCES = 6


def load_optical(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    for col in ("solid_px", "light_px", "water_px", "cloud_px", "land_px", "nodata_px"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
    day = pd.to_datetime(frame["timestamp"].astype(str).str[:8], format="%Y%m%d")
    frame["day"] = day.dt.date
    frame["season"] = day.dt.year
    frame["month"] = day.dt.month
    classified = frame.solid_px + frame.light_px + frame.water_px
    grid = classified + frame.cloud_px + frame.land_px + frame.nodata_px
    frame["ice"] = (frame.solid_px + frame.light_px).divide(
        classified.where(classified > 0)
    )
    frame["share"] = classified.divide(grid.where(grid > 0))
    return frame[frame.share >= MIN_CLASSIFIED_SHARE]


def measure_days(
    days: list[date], window: int, land, bounds, crs, transform, token: SasToken
) -> pd.DataFrame:
    """Every RTC acquisition within +- window days of each target day."""
    rows: list[dict[str, Any]] = []
    for target in days:
        found = search_scenes(
            target - timedelta(days=window), target + timedelta(days=window)
        )
        for feature in found:
            stats = measure_scene(feature, land, bounds, crs, transform, token)
            row = stats.as_row()
            row["target_day"] = target.isoformat()
            row["offset_days"] = (stats.date - target).days
            rows.append(row)
        LOGGER.info("%s: %d acquisitions in the window", target, len(found))
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    parser.add_argument("--window", type=int, default=2, help="days either side")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    optical = load_optical(args.archive)
    targets = {**WET_DAYS, **CONTESTED}

    # Reference days: same season, deep winter, optically frozen.
    references: dict[str, list[date]] = {}
    for iso in targets:
        target = date.fromisoformat(iso)
        same = optical[
            (optical.season == target.year)
            & (optical.month.isin(REFERENCE_MONTHS))
            & (optical.ice >= REFERENCE_MIN_ICE)
        ]
        references[iso] = sorted(same.day)[-MAX_REFERENCES:]
        LOGGER.info(
            "%s: %d optical reference days in its own winter", iso, len(references[iso])
        )

    land, bounds, crs, transform = load_landmask()
    token = SasToken()

    every_day = sorted(
        {date.fromisoformat(d) for d in targets}
        | {d for days in references.values() for d in days}
    )
    LOGGER.info("measuring %d days of RTC", len(every_day))
    measured = measure_days(every_day, args.window, land, bounds, crs, transform, token)

    args.out.mkdir(parents=True, exist_ok=True)
    measured.to_csv(args.out / "sar_wet_days.csv", index=False)

    usable = measured[measured.passes_gates.astype(str).isin({"True", "1", "true"})]
    print()
    print(
        f"{len(measured)} acquisitions measured, {len(usable)} pass the geometry gates"
    )
    print(f"written to {args.out / 'sar_wet_days.csv'}")
    print()

    if usable.empty:
        print("nothing passed, cannot compare")
        return 1

    usable = usable.copy()
    usable["water_median_db"] = pd.to_numeric(usable.water_median_db, errors="coerce")
    usable["relative_orbit"] = pd.to_numeric(usable.relative_orbit, errors="coerce")

    def nearest(target: str) -> pd.DataFrame:
        block = usable[usable.target_day == target].copy()
        block["abs_offset"] = block.offset_days.abs()
        return block.sort_values("abs_offset")

    print(
        f"{'day':12s} {'S2':>7s} {'LS':>7s} {'radar dB':>9s} {'orbit':>6s} {'off':>4s}  own winter ice"
    )
    for iso, (s2, ls) in targets.items():
        block = nearest(iso)
        if block.empty:
            print(f"{iso:12s} {s2:7.3f} {ls:7.3f} {'no scene':>9s}")
            continue
        row = block.iloc[0]
        refs = pd.concat(
            [nearest(r.isoformat()) for r in references[iso]] or [pd.DataFrame()]
        )
        same_orbit = (
            refs[refs.relative_orbit == row.relative_orbit] if not refs.empty else refs
        )
        pool = same_orbit if len(same_orbit) >= 2 else refs
        tag = "same orbit" if len(same_orbit) >= 2 else "mixed orbits"
        if pool.empty:
            print(
                f"{iso:12s} {s2:7.3f} {ls:7.3f} {row.water_median_db:9.2f} "
                f"{int(row.relative_orbit):6d} {int(row.offset_days):4d}  no reference"
            )
            continue
        ref_med = float(pool.water_median_db.median())
        delta = float(row.water_median_db) - ref_med
        print(
            f"{iso:12s} {s2:7.3f} {ls:7.3f} {row.water_median_db:9.2f} "
            f"{int(row.relative_orbit):6d} {int(row.offset_days):4d}  "
            f"{ref_med:6.2f} dB from n={len(pool)} ({tag}), delta {delta:+.2f} dB"
        )
    print()
    print(
        "A day sitting at its own winter's ice level is ice under a wet surface.\n"
        "A day far below it is ambiguous: open water and wet snow both depress\n"
        "C band, and this comparison cannot separate them. Read the deltas, not\n"
        "the absolute decibels, because incidence angle moves those on its own."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
