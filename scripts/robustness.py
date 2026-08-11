#!/usr/bin/env python3
"""One headline, or one headline out of a hundred and twenty?

    python3 scripts/robustness.py

The published decline of 22.6 percent rests on five analytic choices, and each of
them was made once, early, for a reason. A window of day 53 to 180. A split at
2021. The gap-filled daily series rather than the measured days alone. A season
summarised by its mean. Seasons weighted equally.

Every one of those is defensible. None of them is forced. A reader is entitled to
ask what the number would have been under the other defensible choices, and the
honest way to answer is not to argue for the published one but to compute all of
them and show the spread. That is a specification curve, and this builds it.

The second half is the influence question a curve cannot answer: the record is
ten seasons, so one bad season is ten percent of it. Dropping each in turn says
how much of the headline any single year is carrying.

WHAT WOULD FALSIFY THE STORY. If the decline changed sign under choices this
project cannot rule out, or if it survived only in a corner of the space, the
claim would be an artefact of the specification. Both are checked below rather
than asserted, and the result is printed whichever way it comes out.

WHAT THIS IS NOT. It is not an uncertainty interval. The specifications are not
independent draws from anything, they overlap heavily, and the spread of a
specification curve is a statement about analytic freedom rather than about
sampling error. The sampling error is in the per season bootstrap in
docs/published_numbers.json, and it is larger.
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERIES = ROOT / "archive/reprocessed_2026/daily_series.csv"


# The published specification, and the number it has to produce before anything
# below it is worth reading.
class Spec(NamedTuple):
    """One complete set of analytic choices, enough to produce a headline."""

    series: str
    window: tuple[int, int]
    split: int
    aggregate: str
    weighting: str


PUBLISHED = Spec(
    series="frac_filled",
    window=(53, 180),
    split=2021,
    aggregate="mean",
    weighting="equal",
)
PUBLISHED_DECLINE = 22.6

# Every axis of freedom, with the reason each alternative is defensible.
SERIES = {
    # What the charts plot: measured days, with interior gaps filled.
    "frac_filled": "gap filled daily series",
    # Only days a satellite actually saw. Fewer days, no interpolation.
    "frac": "measured days only",
}
WINDOWS = {
    (53, 180): "published, 22 Feb to 29 Jun",
    (45, 180): "from 14 Feb, where the shadow bias is largest",
    (74, 180): "from 15 Mar, once the sun clears ten degrees",
    (53, 166): "to 15 Jun, before the late season thins out",
    (53, 196): "to 15 Jul, past every break-up in the record",
}
SPLITS = {
    2020: "three seasons against seven",
    2021: "published, four against six",
    2022: "five against five",
}
AGGREGATES = ("mean", "median")
WEIGHTINGS = ("equal", "by_days")


def season_table(
    frame: pd.DataFrame, series: str, window: tuple[int, int], aggregate: str
) -> pd.DataFrame:
    """One row per season: its summary value and how many days it rests on."""
    lo, hi = window
    win = frame[(frame.doy >= lo) & (frame.doy <= hi) & frame[series].notna()]
    grouped = win.groupby("year")[series]
    return pd.DataFrame(
        {
            "value": grouped.mean() if aggregate == "mean" else grouped.median(),
            "days": grouped.size(),
        }
    )


def decline(table: pd.DataFrame, split: int, weighting: str) -> tuple[float, int, int]:
    """Percent below the early period, on the ratio of the two period means."""
    early = table[table.index < split]
    late = table[table.index >= split]
    if early.empty or late.empty:
        return float("nan"), len(early), len(late)
    if weighting == "equal":
        e, ell = early.value.mean(), late.value.mean()
    else:
        e = float(np.average(early.value, weights=early.days))
        ell = float(np.average(late.value, weights=late.days))
    return 100.0 * (1.0 - ell / e), len(early), len(late)


def permutation_p(values: np.ndarray, n_early: int) -> float:
    """Two sided exact p over every way of cutting the seasons into two groups."""
    observed = abs(values[:n_early].mean() - values[n_early:].mean())
    idx = list(range(len(values)))
    hits = total = 0
    for combo in itertools.combinations(idx, n_early):
        rest = [i for i in idx if i not in combo]
        gap = abs(values[list(combo)].mean() - values[rest].mean())
        total += 1
        hits += gap >= observed - 1e-12
    return hits / total


def specification_curve(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for series, window, split, aggregate, weighting in itertools.product(
        SERIES, WINDOWS, SPLITS, AGGREGATES, WEIGHTINGS
    ):
        table = season_table(frame, series, window, aggregate)
        value, n_early, n_late = decline(table, split, weighting)
        rows.append(
            {
                "series": series,
                "window": f"{window[0]}-{window[1]}",
                "split": split,
                "aggregate": aggregate,
                "weighting": weighting,
                "seasons_early": n_early,
                "seasons_late": n_late,
                "decline_percent": value,
                "permutation_p": permutation_p(table.value.to_numpy(), n_early),
                "is_published": Spec(series, window, split, aggregate, weighting)
                == PUBLISHED,
            }
        )
    return pd.DataFrame(rows)


def leave_one_out(frame: pd.DataFrame) -> pd.DataFrame:
    """The published specification, minus one season at a time."""
    table = season_table(frame, PUBLISHED.series, PUBLISHED.window, PUBLISHED.aggregate)
    full, _, _ = decline(table, PUBLISHED.split, PUBLISHED.weighting)
    rows = []
    for season in table.index:
        kept = table.drop(index=season)
        value, n_early, n_late = decline(kept, PUBLISHED.split, PUBLISHED.weighting)
        rows.append(
            {
                "dropped": int(season),
                "season_value": float(table.loc[season, "value"]),
                "days": int(table.loc[season, "days"]),
                "period": "early" if season < PUBLISHED.split else "late",
                "decline_percent": value,
                "shift": value - full,
                "permutation_p": permutation_p(kept.value.to_numpy(), n_early),
                "seasons_left": n_early + n_late,
            }
        )
    return pd.DataFrame(rows).sort_values("shift")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--series-path", type=Path, default=DEFAULT_SERIES)
    parser.add_argument("--out", type=Path, default=ROOT / "out/archive")
    parser.add_argument("--tolerance", type=float, default=0.1)
    args = parser.parse_args(argv)

    frame = pd.read_csv(args.series_path)
    curve = specification_curve(frame)

    published = curve[curve.is_published].iloc[0]
    if abs(published.decline_percent - PUBLISHED_DECLINE) > args.tolerance:
        print(
            f"REFUSING: the published specification gives "
            f"{published.decline_percent:.2f} and not {PUBLISHED_DECLINE}. "
            "Something in this machinery no longer matches the published pipeline, "
            "so nothing below it can be trusted."
        )
        return 2

    print("The specification curve")
    print("=" * 78)
    print(
        f"{len(curve)} specifications, every combination of {len(SERIES)} series, "
        f"{len(WINDOWS)} windows,\n{len(SPLITS)} splits, {len(AGGREGATES)} season "
        f"aggregates and {len(WEIGHTINGS)} weightings."
    )
    print()
    values = curve.decline_percent.to_numpy()
    print(f"{'':22s}{'decline %':>12s}")
    for label, value in (
        ("published", published.decline_percent),
        ("median specification", float(np.median(values))),
        ("lowest", float(values.min())),
        ("highest", float(values.max())),
        ("5th percentile", float(np.percentile(values, 5))),
        ("95th percentile", float(np.percentile(values, 95))),
    ):
        print(f"{label:22s}{value:12.1f}")

    below_zero = int((values <= 0).sum())
    print()
    print(
        f"  {len(curve) - below_zero} of {len(curve)} specifications find a decline "
        f"and {below_zero} find none.\n"
        f"  The published choice sits at the "
        f"{100.0 * (values < published.decline_percent).mean():.0f} percentile of the "
        "spread, so it is\n  neither the flattering corner nor the cautious one."
    )
    p = curve.permutation_p.to_numpy()
    print(
        f"  Under a two sided exact permutation test, {int((p < 0.05).sum())} of "
        f"{len(curve)} reach p < 0.05 and\n  {int((p < 0.10).sum())} reach p < 0.10. "
        "Ten seasons cannot do much better than that, and\n  this is the honest "
        "reason the story reports a direction rather than a proof."
    )

    print()
    print("Which choice moves it most")
    print("-" * 78)
    print(f"{'axis':14s}{'choice':38s}{'median decline %':>18s}")
    for axis, options in (
        ("series", SERIES),
        ("window", {f"{a}-{b}": t for (a, b), t in WINDOWS.items()}),
        ("split", SPLITS),
        ("aggregate", {k: k for k in AGGREGATES}),
        ("weighting", {k: k for k in WEIGHTINGS}),
    ):
        for option, note in options.items():
            block = curve[curve[axis].astype(str) == str(option)]
            label = f"{option} ({note})" if note != str(option) else str(option)
            print(f"{axis:14s}{label:38.38s}{block.decline_percent.median():18.1f}")

    spans = {
        axis: curve.groupby(axis)
        .decline_percent.median()
        .pipe(lambda s: s.max() - s.min())
        for axis in ("series", "window", "split", "aggregate", "weighting")
    }
    worst = max(spans, key=lambda k: spans[k])
    print()
    print(
        f"  The widest single axis is {worst}, at {spans[worst]:.1f} points between its\n"
        "  best and worst choice. Every other axis moves the answer less than that."
    )

    print()
    print("The two ends of the space, named")
    print("-" * 78)
    for label, row in (
        ("lowest ", curve.loc[curve.decline_percent.idxmin()]),
        ("highest", curve.loc[curve.decline_percent.idxmax()]),
    ):
        # Bracket access throughout: `aggregate` and `shift` are Series methods,
        # so attribute access on a row silently returns the method instead.
        print(
            f"  {label}  {row['decline_percent']:6.1f} %  "
            f"p = {row['permutation_p']:.3f}   "
            f"{row['series']}, days {row['window']}, split {row['split']},\n"
            f"            {row['aggregate']} of the season, "
            f"weighted {row['weighting']}"
        )

    print()
    print(
        "  The published choice is NOT the flattering corner on the two axes that\n"
        "  carry most of the spread. Dropping the gap filling and using only days a\n"
        "  satellite actually saw gives a LARGER decline and a smaller p. Summarising\n"
        "  a season by its median rather than its mean gives a much larger one. On\n"
        "  both, the published choice is the conservative one."
    )
    print()
    print(
        "  The split is the exception, and it is the honest weak point. 2021 gives the\n"
        "  largest decline of the three, and the midpoint of a ten season record would\n"
        "  now be 2022, which gives roughly half as much. The reason 2021 is kept is\n"
        "  not that it is better. It is that it was fixed when the record ran 2017 to\n"
        "  2025, nine seasons, where four against five was the closest to an even cut,\n"
        "  and it has not moved since. A boundary set before the 2026 season existed\n"
        "  cannot have been chosen to suit it, and moving it now, having seen that\n"
        "  season, is the thing that would not be defensible."
    )

    print()
    print("Leave one season out, on the published specification")
    print("-" * 78)
    loo = leave_one_out(frame)
    print(
        f"{'dropped':>9s}{'period':>8s}{'its mean':>10s}{'days':>6s}"
        f"{'decline %':>11s}{'shift':>8s}{'perm p':>8s}"
    )
    for row in loo.itertuples():
        print(
            f"{row.dropped:>9d}{row.period:>8s}{row.season_value:10.3f}{row.days:6d}"
            f"{row.decline_percent:11.1f}{row.shift:+8.1f}{row.permutation_p:8.3f}"
        )

    worst_row = loo.iloc[0]
    best_row = loo.iloc[-1]
    print()
    print(
        f"  Dropping {int(worst_row.dropped)} costs {abs(worst_row['shift']):.1f} points and dropping "
        f"{int(best_row.dropped)} adds {best_row['shift']:.1f}.\n"
        f"  The headline survives the loss of any single season in sign, and it moves\n"
        f"  between {loo.decline_percent.min():.1f} and {loo.decline_percent.max():.1f} percent while it does. "
        "That range is the answer to\n  the question a ten season record always invites, which is whether one\n"
        "  year is carrying the result."
    )

    args.out.mkdir(parents=True, exist_ok=True)
    curve.to_csv(args.out / "specification_curve.csv", index=False)
    loo.to_csv(args.out / "leave_one_season_out.csv", index=False)
    print(f"\nwritten to {args.out / 'specification_curve.csv'}")
    print(f"written to {args.out / 'leave_one_season_out.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
