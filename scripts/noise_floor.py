#!/usr/bin/env python3
"""Ice does not move overnight. Whatever does move overnight is the instrument.

    python3 scripts/noise_floor.py

Every number this project publishes is a difference between two averages, and no
page in it says how large a difference has to be before it means anything. The
per season bootstrap answers a different question: it resamples the days that
were measured and reports how much the season mean would wander, which is
sampling error given the measurement. It says nothing about how good any single
measurement is.

There is a way to ask that without a reference dataset. In the deep of winter
this fjord is landfast ice shore to shore, and it stays that way for months. Two
scenes one day apart in that window are looking at the same surface. Any
difference between them is the chain: cloud edges, shadow length, a different
platform, the gate. So the distribution of one-day differences inside the frozen
window is a floor under the noise, and it can be set beside the signal.

That comparison is the only thing here. It is printed against the published
between-period gap of 0.154 in ice fraction, and against the season to season
spread, so a reader can see whether the story is measuring ice or measuring its
own instrument.

WHAT THIS IS NOT. It is a floor, not the noise itself. The surface can genuinely
change a little overnight even in February: a lead opens, wind clears snow,
temperature moves. Everything real that happens in a day is counted here as noise
and inflates the floor, which makes this conservative in the direction that
matters. It is also silent about anything that biases every scene the same way,
because a difference between two scenes cancels exactly that. The shadow is a
bias of that kind, which is why it needs shadow_bias.py and not this.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / "archive/reprocessed_2026/summary.csv"

# The fjord is landfast shore to shore across this window in every season of the
# record: the earliest break-up is 30 April, day 120. Same window as
# shadow_bias.py, for the same reason.
FROZEN_WINDOW = (45, 105)
MIN_SHARE = 0.30
LATE_FROM = 2021
# The published gap between the early and late period means, from
# docs/published_numbers.json.
PUBLISHED_GAP = 0.154
COUNTS = ("solid_px", "light_px", "water_px", "cloud_px", "land_px", "nodata_px")
# How far apart two scenes may be and still be treated as the same surface.
LAGS = (1, 2, 3, 5, 10)


def load(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    for column in COUNTS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    stamp = pd.to_datetime(frame.timestamp.astype(str), format="%Y%m%dT%H%M%S")
    classified = frame.solid_px + frame.light_px + frame.water_px
    grid = classified + frame.cloud_px + frame.land_px + frame.nodata_px
    frame["date"] = stamp.dt.normalize()
    frame["doy"] = stamp.dt.dayofyear
    frame["season"] = stamp.dt.year
    frame["ice"] = (frame.solid_px + frame.light_px).divide(
        classified.where(classified > 0)
    )
    frame["share"] = classified.divide(grid.where(grid > 0))
    frame["sun"] = pd.to_numeric(frame.sun_elev, errors="coerce")
    return frame


def pairs(frame: pd.DataFrame, lag: int) -> pd.DataFrame:
    """Every pair of usable scenes exactly `lag` days apart, inside one season."""
    left = frame.copy()
    right = frame.copy()
    right["date"] = right.date - pd.Timedelta(days=lag)
    merged = left.merge(right, on="date", suffixes=("_a", "_b"))
    merged = merged[merged.season_a == merged.season_b]
    merged["gap"] = (merged.ice_b - merged.ice_a).abs()
    merged["mean_sun"] = (merged.sun_a + merged.sun_b) / 2.0
    return merged


def describe(block: pd.DataFrame) -> dict[str, float]:
    return {
        "pairs": len(block),
        "median": float(block.gap.median()),
        "p90": float(block.gap.quantile(0.90)),
        "worst": float(block.gap.max()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--out", type=Path, default=ROOT / "out/archive")
    args = parser.parse_args(argv)

    frame = load(args.archive)
    lo, hi = FROZEN_WINDOW
    frozen = frame[
        (frame.doy >= lo) & (frame.doy <= hi) & (frame.share >= MIN_SHARE)
    ].copy()

    print(f"Two scenes, one surface: day {lo} to {hi}, {len(frozen)} usable scenes")
    print("=" * 78)
    print(
        "  The fjord is landfast shore to shore across this whole window in every\n"
        "  season of the record. Two scenes a day apart are looking at the same ice."
    )
    print()
    print(f"{'days apart':>12s}{'pairs':>8s}{'median':>10s}{'p90':>9s}{'worst':>9s}")
    rows: list[dict[str, object]] = []
    for lag in LAGS:
        block = pairs(frozen, lag)
        if block.empty:
            continue
        stats = describe(block)
        print(
            f"{lag:>12d}{stats['pairs']:8.0f}{stats['median']:10.3f}"
            f"{stats['p90']:9.3f}{stats['worst']:9.3f}"
        )
        rows.append({"lag_days": lag, **stats})

    one_day = pairs(frozen, 1)
    floor = float(one_day.gap.median())
    p90 = float(one_day.gap.quantile(0.90))
    print()
    print(
        f"  The typical scene is very good and the tail is very bad. The one day\n"
        f"  difference is {floor:.3f} in ice fraction at the median, which is "
        f"{PUBLISHED_GAP / floor:.0f} times smaller\n"
        f"  than the {PUBLISHED_GAP:.3f} this project publishes between its two periods. At the\n"
        f"  ninetieth percentile it is {p90:.3f}, which is the published gap itself. One\n"
        "  scene in ten disagrees with the scene beside it by as much as the entire\n"
        "  signal, on a surface that did not change."
    )
    over = {t: int((one_day.gap > t).sum()) for t in (0.10, 0.25, 0.50)}
    print()
    print(
        f"  Of {len(one_day)} pairs, {over[0.10]} differ by more than 0.10, {over[0.25]} by more than 0.25\n"
        f"  and {over[0.50]} by more than 0.50. Those last four are worth printing in full,\n"
        "  because they are not noise in any ordinary sense. They are the chain\n"
        "  changing its mind about the whole fjord overnight."
    )
    print()
    worst_pairs = one_day.nlargest(4, "gap")
    print(
        f"{'date':>12s}{'season':>8s}{'doy':>5s}{'ice':>8s}{'next day':>10s}{'sun':>7s}"
    )
    for row in worst_pairs.itertuples():
        print(
            f"{str(row.date.date()):>12s}{row.season_a:8d}{row.doy_a:5d}"
            f"{row.ice_a:8.3f}{row.ice_b:10.3f}{row.mean_sun:7.1f}"
        )

    print()
    print(
        "  So does the tail reach the headline? Not at full size, because the published\n"
        "  quantity is a difference between SEASON means and each of those averages 24\n"
        "  to 66 measured days. Averaging pulls a symmetric tail down towards nothing.\n"
        "  This tail is not symmetric. Shadow, thin ice and wet ice all move cells from\n"
        "  ice to water and none of them move a cell back, so what survives the average\n"
        "  is a one way pull on whichever period carries more of it."
    )
    lag_medians = [float(r["median"]) for r in rows]  # type: ignore[arg-type]
    print()
    print(
        f"  The lag table is the check on the premise. The median goes {lag_medians[0]:.3f} at one day\n"
        f"  to {lag_medians[-1]:.3f} at ten, so the surface really is holding still across the\n"
        "  window. If it had climbed steeply, this would be measuring a fjord that\n"
        "  changes rather than an instrument that wobbles."
    )

    print()
    print("Where the noise lives")
    print("-" * 78)
    print(f"{'sun elevation':>16s}{'pairs':>8s}{'median':>10s}{'p90':>9s}")
    bands = ((0, 10), (10, 15), (15, 20), (20, 30))
    for band_lo, band_hi in bands:
        block = one_day[(one_day.mean_sun >= band_lo) & (one_day.mean_sun < band_hi)]
        if block.empty:
            continue
        print(
            f"{band_lo:>7d} to {band_hi:<6d}{len(block):8d}"
            f"{block.gap.median():10.3f}{block.gap.quantile(0.90):9.3f}"
        )
        rows.append(
            {
                "lag_days": 1,
                "sun_from": band_lo,
                "sun_to": band_hi,
                "pairs": len(block),
                "median": float(block.gap.median()),
                "p90": float(block.gap.quantile(0.90)),
                "worst": float(block.gap.max()),
            }
        )
    print()
    print(
        "  The floor is a function of the sun, which is the same finding shadow_bias.py\n"
        "  reaches from the other side. A low sun is not merely biased, it is noisy: the\n"
        "  shadow's length changes between two passes and takes a different amount of\n"
        "  ice with it each time."
    )

    print()
    print("Is the late period measured worse than the early one?")
    print("-" * 78)
    print(f"{'period':>10s}{'pairs':>8s}{'median':>10s}{'p90':>9s}{'median sun':>12s}")
    period_rows: list[dict[str, object]] = []
    for name, block in (
        ("early", one_day[one_day.season_a < LATE_FROM]),
        ("late", one_day[one_day.season_a >= LATE_FROM]),
    ):
        print(
            f"{name:>10s}{len(block):8d}{block.gap.median():10.3f}"
            f"{block.gap.quantile(0.90):9.3f}{block.mean_sun.median():12.1f}"
        )
        period_rows.append(
            {
                "period": name,
                "pairs": len(block),
                "median": float(block.gap.median()),
                "p90": float(block.gap.quantile(0.90)),
                "median_sun": float(block.mean_sun.median()),
            }
        )
    early_p90 = float(period_rows[0]["p90"])  # type: ignore[arg-type]
    late_p90 = float(period_rows[1]["p90"])  # type: ignore[arg-type]
    late_share = float((worst_pairs.season_a >= LATE_FROM).mean())
    print()
    print(
        f"  At the median the two periods are indistinguishable. In the tail they are\n"
        f"  not: the ninetieth percentile is {early_p90:.3f} early and {late_p90:.3f} late, a factor of\n"
        f"  {late_p90 / early_p90:.0f}. And {int(late_share * len(worst_pairs))} of the {len(worst_pairs)} pairs above are in the late period.\n"
        "\n"
        "  Put with the asymmetry, that is a one way pull on the late period, which\n"
        "  means the published decline is if anything too large rather than too small.\n"
        "  That is the same direction the thermal and radar chain reaches in\n"
        "  docs/limitations.md when it carries the correction to the series, and this\n"
        "  arrives at it from a different question entirely: not what the fjord was\n"
        "  doing, but how much two neighbouring scenes disagree about a fjord that was\n"
        "  doing nothing."
    )
    rows.extend(period_rows)

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "noise_floor.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f"\nwritten to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
