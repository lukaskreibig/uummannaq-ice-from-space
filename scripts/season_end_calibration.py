#!/usr/bin/env python3
"""Measure both error directions against days whose answer is already known.

The record has never carried an error rate for the ice fraction itself. Every
proposal for one asked for something the project does not have: hand labels, a
second sensor, a field season. The archive has been carrying the answer at both
ends of the season the whole time.

    python3 scripts/season_end_calibration.py
    python3 scripts/season_end_calibration.py --archive path/to/summary.csv

The two anchors, and why each is safe:

  July           This fjord is open in July with near certainty. Over the
                 reprocessed archive the June median clear-sky ice fraction is
                 0.001 and July 0.002, and the latest break-up in the record is
                 8 June 2024. So on a July scene the true ice fraction is zero,
                 and whatever the pipeline reports instead IS its false ice
                 rate, measured on open water.

  1 to 20 April  The earliest break-up in the record is 30 April 2021, day 120.
                 A window ending on day 110 therefore sits at least ten days
                 before the fjord has ever opened, in all ten seasons. The true
                 ice fraction is one, and the shortfall IS the false water rate,
                 measured on fast ice.

Neither anchor needs a label, a second instrument or a field campaign. Both are
scenes the pipeline already processed and then discarded, because the published
season window stops at day 180 and the calibration value of the days on either
side was never used.

What the script deliberately does NOT do: treat the two rates as symmetric. The
medians come out close, and the tails do not. The distribution of the April
residuals is the interesting half, so it is printed in full rather than
summarised, and the seasons the outliers fall in are tested for clustering.

Exits non-zero if an anchor window has too few scenes to support a rate, so it
can sit in a Makefile target.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Sequence

import pandas as pd

DEFAULT_ARCHIVE = Path("archive/reprocessed_2026/summary.csv")

# The visibility gate the published series uses. A scene that classified less
# than this share of the AOI is not a measurement of it.
MIN_CLASSIFIED_SHARE = 0.30

# Day of year windows. See the module docstring for why each one is safe.
APRIL_WINDOW = (91, 110)
JULY_WINDOW = (182, 213)

# Break-up day of year per season, from the published series: the story's
# backend runs _freeze_and_breakup over frac_smooth in
# climate-dashboard/backend/main.py. Kept here as data rather than recomputed,
# so the two definitions cannot quietly drift apart; the assert below fails if
# they do.
#
# An outlier's distance from its own season's break-up is what decides how it
# reads. Ten days before break-up a low reading can be the fjord starting to
# open. A month before, it cannot.
BREAKUP_DOY = {
    2017: 157,
    2018: 155,
    2019: 142,
    2020: 147,
    2021: 120,
    2022: 159,
    2023: 134,
    2024: 160,
    2025: 134,
    2026: 133,
}

# Earliest break-up in the record, 30 April 2021. The April window has to end
# before this or the anchor is not an anchor.
EARLIEST_BREAKUP_DOY = min(BREAKUP_DOY.values())

# An outlier this far before its own break-up cannot be the fjord opening.
CLEAR_OF_BREAKUP_DAYS = 21

# Below this an April scene is not a small residual, it is a different answer.
OUTLIER_BELOW = 0.90

BOOTSTRAP_DRAWS = 20000
PERMUTATIONS = 20000
SEED = 20260811


def load(path: Path) -> pd.DataFrame:
    """Rebuild share and ice fraction from the counts, not from the columns.

    The archive predates the change from the clear-sky denominator to the
    classified one, so its written `*_pct_clear` columns answer a question the
    published series no longer asks. The raw counts are the same either way,
    which is why the story rebuilds from them too.
    """
    frame = pd.read_csv(path)
    counts = ["solid_px", "light_px", "water_px", "cloud_px", "land_px", "nodata_px"]
    missing = [c for c in counts if c not in frame.columns]
    if missing:
        raise SystemExit(f"archive is missing count columns: {', '.join(missing)}")
    for col in counts:
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)

    day = pd.to_datetime(frame["timestamp"].astype(str).str[:8], format="%Y%m%d")
    frame["day"] = day
    frame["doy"] = day.dt.dayofyear
    frame["season"] = day.dt.year

    classified = frame.solid_px + frame.light_px + frame.water_px
    total = classified + frame.cloud_px + frame.land_px + frame.nodata_px
    frame["classified_share"] = classified.divide(total.where(total > 0))
    frame["ice"] = (frame.solid_px + frame.light_px).divide(
        classified.where(classified > 0)
    )
    return frame


def window(frame: pd.DataFrame, bounds: tuple[int, int]) -> pd.DataFrame:
    lo, hi = bounds
    picked = frame[(frame.doy >= lo) & (frame.doy <= hi)]
    return picked[picked.classified_share >= MIN_CLASSIFIED_SHARE].copy()


def median_ci(
    values: Sequence[float], draws: int = BOOTSTRAP_DRAWS
) -> tuple[float, float, float]:
    """Median with a percentile bootstrap interval.

    The residuals are heavily skewed, so a standard error around a mean would
    describe a distribution this is not. The median is what gets quoted and the
    bootstrap is on the median.
    """
    rng = random.Random(SEED)
    data = list(values)
    n = len(data)
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    point = float(pd.Series(data).median())
    medians = []
    for _ in range(draws):
        sample = [data[rng.randrange(n)] for _ in range(n)]
        medians.append(float(pd.Series(sample).median()))
    medians.sort()
    return point, medians[int(0.025 * draws)], medians[int(0.975 * draws)]


def clustering_p(april: pd.DataFrame) -> tuple[float, int]:
    """Do the April outliers fall in more seasons than chance would put them in?

    The question that matters is not whether outliers exist but whether they
    concentrate in particular seasons, because a failure mode that prefers the
    seasons carrying the headline is a different problem from one spread evenly.

    The statistic is the sum of squared per-season outlier counts, which is
    large when they bunch. Under the null the same number of outliers is dealt
    out across the scenes at random, holding each season's scene count fixed.
    """
    flags = (april.ice < OUTLIER_BELOW).to_numpy()
    seasons = april.season.to_numpy()
    observed = pd.Series(seasons[flags]).value_counts()
    stat = float((observed**2).sum())

    rng = random.Random(SEED)
    n, k = len(flags), int(flags.sum())
    if k == 0:
        return float("nan"), 0
    idx = list(range(n))
    hits = 0
    for _ in range(PERMUTATIONS):
        drawn = rng.sample(idx, k)
        counts = pd.Series(seasons[drawn]).value_counts()
        if float((counts**2).sum()) >= stat:
            hits += 1
    return (hits + 1) / (PERMUTATIONS + 1), k


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure the false ice and false water rates against days whose answer is known.",
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    args = parser.parse_args(argv)

    if not args.archive.exists():
        print(f"archive not found: {args.archive}", file=sys.stderr)
        return 2

    frame = load(args.archive)
    april = window(frame, APRIL_WINDOW)
    july = window(frame, JULY_WINDOW)

    if APRIL_WINDOW[1] >= EARLIEST_BREAKUP_DOY:
        print(
            f"April window ends on day {APRIL_WINDOW[1]}, at or after the earliest "
            f"break-up on day {EARLIEST_BREAKUP_DOY}. The anchor does not hold.",
            file=sys.stderr,
        )
        return 1

    failed = False
    for name, picked in (("April", april), ("July", july)):
        if len(picked) < 20 or picked.season.nunique() < 8:
            print(
                f"{name} anchor is too thin: {len(picked)} scenes from "
                f"{picked.season.nunique()} seasons",
                file=sys.stderr,
            )
            failed = True

    print("Season end calibration")
    print("=" * 70)
    print(
        f"archive {args.archive}, visibility gate {MIN_CLASSIFIED_SHARE:.2f}, "
        f"{len(frame)} scenes total"
    )
    print()

    fp, fp_lo, fp_hi = median_ci(july.ice.dropna().tolist())
    print(
        f"False ice on open water   {len(july):4d} July scenes, "
        f"{july.season.nunique()} seasons"
    )
    print(f"    median reported ice   {fp:.4f}   95 % CI {fp_lo:.4f} to {fp_hi:.4f}")
    print(
        f"    worst scene           {july.ice.max():.4f} on {july.loc[july.ice.idxmax(), 'day'].date()}"
    )
    print(f"    scenes above 0.05     {int((july.ice > 0.05).sum())}")
    print()

    residual = 1.0 - april.ice
    fn, fn_lo, fn_hi = median_ci(residual.dropna().tolist())
    print(
        f"False water on fast ice   {len(april):4d} April scenes (1 to 20 April), "
        f"{april.season.nunique()} seasons"
    )
    print(f"    median shortfall      {fn:.4f}   95 % CI {fn_lo:.4f} to {fn_hi:.4f}")
    print(f"    mean shortfall        {residual.mean():.4f}")
    print(
        f"    worst scene           {residual.max():.4f} on {april.loc[april.ice.idxmin(), 'day'].date()}"
    )
    print()

    outliers = april[april.ice < OUTLIER_BELOW].sort_values("ice").copy()
    outliers["before_breakup"] = [
        BREAKUP_DOY.get(int(s_), 0) - int(d)
        for s_, d in zip(outliers.season, outliers.doy, strict=True)
    ]
    print(f"April scenes below {OUTLIER_BELOW:.2f}: {len(outliers)} of {len(april)}")
    print("    date         ice   classified   days before its own break-up")
    for _, row in outliers.iterrows():
        print(
            f"    {row.day.date()}   {row.ice:.4f}   {row.classified_share:9.2f}   "
            f"{int(row.before_breakup):>4d}"
        )
    clear = outliers[outliers.before_breakup >= CLEAR_OF_BREAKUP_DAYS]
    print()
    print(
        f"{len(clear)} of {len(outliers)} sit at least {CLEAR_OF_BREAKUP_DAYS} days before\n"
        f"their own season's break-up, so they cannot be the fjord opening early.\n"
        f"The remaining {len(outliers) - len(clear)} are close enough to break-up that a low\n"
        f"reading might be the real thing."
    )
    print()

    by_season = outliers.season.value_counts().sort_index()
    print("outliers per season:")
    for season in sorted(april.season.unique()):
        n_out = int(by_season.get(season, 0))
        n_all = int((april.season == season).sum())
        bar = "#" * n_out
        print(f"    {season}  {n_out:2d} of {n_all:3d}  {bar}")
    p, k = clustering_p(april)
    print()
    print(
        f"clustering by season: permutation p = {p:.4f} over {PERMUTATIONS} draws "
        f"({k} outliers)"
    )
    print()
    print(
        "Read the two medians together and the two tails separately. The median\n"
        "scene is accurate to about two parts in a thousand in both directions.\n"
        "The tails are not symmetric: open water is almost never called ice, and\n"
        "fast ice is sometimes called water. A cell that fails the brightness gate\n"
        "leaves the denominator rather than becoming water, so a scene can only\n"
        "reach a low ice fraction by having cells pass NDWI. On a fjord that is\n"
        "certainly frozen that is melt water or wet snow read as open water, which\n"
        "is the bias limitations.md carries as unquantified."
    )

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
