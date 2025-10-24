#!/usr/bin/env python3
"""Recompute every number the story publishes, and say which ones moved.

Twice now a figure on a published page turned out to be unreproducible: the
clear-sky decline in methods.md, and the denominator comparison in the story's
method panel. Both were found by hand, months after they went stale, and the
second one could not be recovered from the archive under any reading. That is a
class of defect, not two incidents, and the fix for a class is a gate.

    python3 scripts/story_numbers.py
    python3 scripts/story_numbers.py --expect docs/published_numbers.json

Run without --expect it prints what the archive says today. Run with --expect it
compares against a committed set of claims and exits non-zero when any of them
has drifted, so it can sit in CI next to check_summary.py.

What it recomputes, all from archive/reprocessed_2026/summary.csv plus the
published daily series, and nothing from memory:

  spring means      the ten seasonal means limitations.md prints
  headline          early against late, and the decline between them
  permutation       the exact test over all C(10,4) = 210 splits
  mann kendall      the monotone trend test
  coverage          the share of days in the window with a scene of their own
  bootstrap         the per season sampling interval the API serves

The daily series is read rather than rebuilt. Rebuilding it here would mean a
second implementation of the gap filling, and two implementations that agree
prove nothing about which one the story ships.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_ARCHIVE = Path("archive/reprocessed_2026/summary.csv")
# The daily series is produced by the story repo's cleaning step, and until
# recently this defaulted to that repo's working copy. That made the gate
# unrunnable on a fresh clone and unrunnable in CI, which is the opposite of
# what a gate is for. It now reads a COMMITTED snapshot, and --live points at
# the source of truth so the two can be compared.
DEFAULT_SERIES = Path("archive/reprocessed_2026/daily_series.csv")
LIVE_SERIES = Path("../climate-dashboard/frontend/public/data/summary_test_cleaned.csv")

SEASON_WINDOW = (53, 180)
LATE_FROM = 2021
BOOTSTRAP_DRAWS = 2000
SEED = 20260811


def spring_means(series: pd.DataFrame) -> pd.Series:
    """Season means of the gap-filled daily series, which is what the charts plot."""
    lo, hi = SEASON_WINDOW
    win = series[(series.doy >= lo) & (series.doy <= hi)]
    return win.groupby("year")["frac_filled"].mean()


def exact_permutation(
    values: np.ndarray, n_early: int
) -> tuple[float, float, int, float]:
    """Every way of cutting the seasons into a group of n_early and the rest.

    Two sided, on the WIDTH of the gap rather than its sign, which is what the
    published figure means by "at least as wide as the real one". Writing this
    one sided instead halves it, from 25 of 210 to 13, and turns p = 0.119 into
    p = 0.062. The published pages have it right; the first version of this
    script did not, which is a fair illustration of why the gate exists.
    """
    observed = values[:n_early].mean() - values[n_early:].mean()
    idx = range(len(values))
    hits = 0
    total = 0
    widest = 0.0
    for combo in itertools.combinations(idx, n_early):
        rest = [i for i in idx if i not in combo]
        gap = values[list(combo)].mean() - values[rest].mean()
        total += 1
        if abs(gap) >= abs(observed):
            hits += 1
        widest = max(widest, abs(gap))
    return observed, hits / total, total, widest


def mann_kendall(values: np.ndarray) -> float:
    """Two sided p for a monotone trend, normal approximation with tie correction."""
    n = len(values)
    s = sum(
        np.sign(values[j] - values[i]) for i in range(n - 1) for j in range(i + 1, n)
    )
    _, counts = np.unique(values, return_counts=True)
    tie = sum(c * (c - 1) * (2 * c + 5) for c in counts if c > 1)
    var = (n * (n - 1) * (2 * n + 5) - tie) / 18.0
    if var <= 0:
        return float("nan")
    z = (s - np.sign(s)) / math.sqrt(var)
    return 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))


def bootstrap_interval(values: np.ndarray) -> float:
    """Sampling standard error of a season mean, resampling its measured days."""
    rng = random.Random(SEED)
    n = len(values)
    if n < 2:
        return float("nan")
    means = [
        float(np.mean([values[rng.randrange(n)] for _ in range(n)]))
        for _ in range(BOOTSTRAP_DRAWS)
    ]
    return float(np.std(means, ddof=1))


def _snapshot_drift(snapshot: Path, live: Path) -> str:
    """Empty string if the committed copy still equals the story repo's."""
    if not snapshot.exists():
        return f"no committed snapshot at {snapshot}"
    a, b = pd.read_csv(snapshot), pd.read_csv(live)
    if len(a) != len(b):
        return (
            f"snapshot has {len(a)} rows against {len(b)} live. Refresh it with\n"
            f"  cp {live} {snapshot}\n"
            "and rerun without --live to see what the numbers do."
        )
    for column in ("frac", "frac_filled", "frac_smooth"):
        if column not in a or column not in b:
            continue
        gap = (a[column] - b[column]).abs().max()
        if gap > 1e-9:
            return (
                f"snapshot and live series disagree on {column} by up to {gap:.6f}. "
                f"Refresh with\n  cp {live} {snapshot}"
            )
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--series", type=Path, default=DEFAULT_SERIES)
    parser.add_argument(
        "--live",
        action="store_true",
        help="read the story repo's working copy instead of the committed "
        "snapshot, and fail if the two disagree",
    )
    parser.add_argument(
        "--expect", type=Path, help="committed claims to compare against"
    )
    parser.add_argument("--tolerance", type=float, default=0.0006)
    args = parser.parse_args(argv)

    if args.live:
        if not LIVE_SERIES.exists():
            print(f"the story repo is not next door: {LIVE_SERIES}")
            return 2
        drift = _snapshot_drift(DEFAULT_SERIES, LIVE_SERIES)
        if drift:
            print(drift)
            return 2
        print(f"snapshot matches the live series at {LIVE_SERIES}")
        args.series = LIVE_SERIES
    if not args.series.exists():
        print(f"published series not found: {args.series}")
        return 2

    series = pd.read_csv(args.series)
    series["doy"] = pd.to_numeric(series["doy"], errors="coerce")
    series["year"] = pd.to_numeric(series["year"], errors="coerce")

    means = spring_means(series)
    seasons = sorted(means.index)
    values = means.loc[seasons].to_numpy()
    n_early = sum(1 for s in seasons if s < LATE_FROM)

    early = values[:n_early].mean()
    late = values[n_early:].mean()
    decline = 100.0 * (1.0 - late / early)
    gap, p_perm, n_splits, widest = exact_permutation(values, n_early)
    p_mk = mann_kendall(values)

    lo, hi = SEASON_WINDOW
    win = series[(series.doy >= lo) & (series.doy <= hi)]
    measured = win.dropna(subset=["frac"])
    coverage = len(measured) / len(win)
    per_season_coverage = (
        measured.groupby("year").size() / win.groupby("year").size()
    ).round(4)

    computed = {
        "spring_means": {
            int(s): round(float(v), 3) for s, v in zip(seasons, values, strict=True)
        },
        "early_mean": round(float(early), 4),
        "late_mean": round(float(late), 4),
        "decline_percent": round(float(decline), 1),
        "permutation_p": round(float(p_perm), 3),
        "permutation_splits": n_splits,
        "observed_gap": round(float(gap), 3),
        "widest_gap": round(float(widest), 3),
        "mann_kendall_p": round(float(p_mk), 3),
        "coverage": round(float(coverage), 3),
        "coverage_min_season": int(per_season_coverage.idxmin()),
        "coverage_min": round(float(per_season_coverage.min()), 3),
        "bootstrap_se": {
            int(y): round(bootstrap_interval(g["frac"].dropna().to_numpy()), 3)
            for y, g in measured.groupby("year")
        },
    }

    print("Story numbers, recomputed from the published series")
    print("=" * 66)
    print(f"seasons        {seasons[0]} to {seasons[-1]}, n = {len(seasons)}")
    print(
        "spring means   "
        + "  ".join(f"{s}:{v:.3f}" for s, v in zip(seasons, values, strict=True))
    )
    print(f"early / late   {early:.4f} / {late:.4f}")
    print(f"decline        {decline:.1f} percent")
    print(f"permutation    p = {p_perm:.3f} over all {n_splits} splits, two sided")
    print(
        f"               observed gap {gap:.3f}, widest gap of any split {widest:.3f}"
    )
    print(f"mann kendall   p = {p_mk:.3f}")
    print(f"coverage       {coverage:.1%} of days in the window have a scene")
    print(
        f"thinnest       {computed['coverage_min_season']} at {computed['coverage_min']:.1%}"
    )
    print()

    if not args.expect:
        print("no --expect given, nothing compared. Write this out with:")
        print(
            "    python3 scripts/story_numbers.py > /dev/null && "
            'python3 -c "..."  # or commit docs/published_numbers.json'
        )
        print(json.dumps(computed, indent=2, sort_keys=True))
        return 0

    if not args.expect.exists():
        args.expect.write_text(json.dumps(computed, indent=2, sort_keys=True) + "\n")
        print(f"no claims file yet, wrote the current values to {args.expect}")
        return 0

    claimed = json.loads(args.expect.read_text())
    # Compare through the same serialisation both sides will live in. JSON turns
    # the integer season keys into strings, so comparing the in-memory dict
    # against the parsed file reports every season as drifted forever.
    computed = json.loads(json.dumps(computed, sort_keys=True))
    drifted = []

    def compare(path: str, want, got):
        if isinstance(want, dict):
            for k in want:
                compare(f"{path}.{k}", want[k], (got or {}).get(k))
            return
        if isinstance(want, (int, float)) and isinstance(got, (int, float)):
            if abs(float(want) - float(got)) > args.tolerance:
                drifted.append((path, want, got))
        elif want != got:
            drifted.append((path, want, got))

    compare("", claimed, computed)
    if drifted:
        print(f"{len(drifted)} claims have drifted:")
        for path, want, got in drifted:
            print(f"    {path.lstrip('.'):32s} published {want}   now {got}")
        print()
        print("Either the archive changed and the pages need updating, or something")
        print("upstream moved without anyone noticing. Both are worth stopping for.")
        return 1

    print(f"all {len(json.dumps(claimed))} bytes of claims still reproduce")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
