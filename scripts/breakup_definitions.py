#!/usr/bin/env python3
"""What is break-up, on days that were actually observed?

The shipped detector reads the smoothed, gap-filled series. backend/main.py
renames frac_smooth to frac before calling it, and frac_raw sits unused beside
it. limitations.md measures the consequence: smoothing dates break-up 6 days
early on average, up to 26 days in 2023, and always early, never late.

Pointing the same detector at the observed series does not work, and the failure
is instructive rather than a bug. It asks for seven CONSECUTIVE rows below the
threshold, and with coverage between 19 and 50 percent and gaps up to 17 days,
seven consecutive observations essentially never occur. Run that way it returns
nothing for all ten seasons.

So the definition has to survive irregular sampling, and this measures what
different reasonable definitions give.

    python3 scripts/breakup_definitions.py

    Run it with the story backend's interpreter, because the published baseline
    is taken from the shipped function rather than reimplemented:
    ../climate-dashboard/backend/.venv/bin/python

The observed-day definition used here, and every part of it is a choice:

    break-up is the first OBSERVED day d such that every observed day inside the
    calendar window [d, d + N - 1] is below the threshold, the window contains at
    least `min_obs` observations, and at least one earlier observed day in the
    season was at or above the threshold.

Calendar persistence rather than consecutive-observation persistence, because a
gap is missing data and not evidence of thaw. Requiring `min_obs` is what keeps a
single clear day inside a two-week hole from deciding a season, and raising it
trades confidence against censoring. Both are reported.

Thresholds are stated as ICE fraction. Cooley and Ryan (2024) phrase their
criteria as open water, so their 25, 50, 75 and 90 percent open correspond to
0.75, 0.50, 0.25 and 0.10 here, and they call 75 percent open the one that
matters to people travelling on the ice. Walsh et al. (2022) use a per-season
threshold of the winter mean minus two standard deviations, floored at 0.15, with
two weeks of persistence, and that variant is computed separately.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERIES = (
    ROOT.parent / "climate-dashboard/frontend/public/data/summary_test_cleaned.csv"
)
DEFAULT_BACKEND = ROOT.parent / "climate-dashboard/backend"

SEASON_WINDOW = (45, 180)
PUBLISHED_THRESHOLD = 0.15
PUBLISHED_PERSISTENCE = 7

# Ice fraction. Cooley and Ryan phrase these as open water, so 0.25 ice is their
# community-relevant "75 percent open".
THRESHOLDS = (0.15, 0.25, 0.50, 0.75)
PERSISTENCE = (1, 7, 14)
MIN_OBS = (1, 2, 3)
LATE_FROM = 2021


def breakup_observed(
    doy: np.ndarray, frac: np.ndarray, threshold: float, need: int, min_obs: int
) -> int | None:
    """First observed day after which the fjord stays open, on observed days only."""
    seen_frozen = False
    for i, d in enumerate(doy):
        if frac[i] >= threshold:
            seen_frozen = True
            continue
        if not seen_frozen:
            continue
        inside = (doy >= d) & (doy < d + need)
        if inside.sum() < min_obs:
            continue
        if bool((frac[inside] < threshold).all()):
            return int(d)
    return None


def walsh_threshold(doy: np.ndarray, frac: np.ndarray) -> float:
    """Winter mean minus two standard deviations, floored at 0.15."""
    winter = frac[(doy >= 45) & (doy <= 105)]
    if winter.size < 3:
        return PUBLISHED_THRESHOLD
    return max(PUBLISHED_THRESHOLD, float(winter.mean() - 2 * winter.std(ddof=1)))


def shift(dates: dict[int, int | None]) -> tuple[float, float, float, int]:
    """Early and late means over the seasons that produced a date, and the gap."""
    early = [v for s, v in dates.items() if v is not None and s < LATE_FROM]
    late = [v for s, v in dates.items() if v is not None and s >= LATE_FROM]
    censored = sum(1 for v in dates.values() if v is None)
    if not early or not late:
        return float("nan"), float("nan"), float("nan"), censored
    a, b = float(np.mean(early)), float(np.mean(late))
    return a, b, b - a, censored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--series", type=Path, default=DEFAULT_SERIES)
    parser.add_argument("--backend", type=Path, default=DEFAULT_BACKEND)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    args = parser.parse_args(argv)

    sys.path.insert(0, str(args.backend))
    try:
        from main import _freeze_and_breakup
    except ModuleNotFoundError as exc:
        print(
            f"cannot import the shipped detector ({exc.name} missing).\n"
            f"Run this with {args.backend}/.venv/bin/python so the published\n"
            "baseline comes from the function that ships rather than a copy."
        )
        return 2

    series = pd.read_csv(args.series)
    lo, hi = SEASON_WINDOW
    seasons = sorted(series.year.dropna().unique().astype(int))

    published: dict[int, int | None] = {}
    rows: list[dict] = []
    for season in seasons:
        block = series[series.year == season].sort_values("doy")
        published[season] = _freeze_and_breakup(block.assign(frac=block.frac_smooth))[1]

    obs = {}
    for season in seasons:
        block = series[
            (series.year == season)
            & (series.doy >= lo)
            & (series.doy <= hi)
            & series.frac.notna()
        ].sort_values("doy")
        obs[season] = (block.doy.to_numpy(), block.frac.to_numpy())

    for threshold in THRESHOLDS:
        for need in PERSISTENCE:
            for min_obs in MIN_OBS:
                if need == 1 and min_obs > 1:
                    continue
                dates = {
                    s: breakup_observed(*obs[s], threshold, need, min_obs)
                    for s in seasons
                }
                early, late, gap, censored = shift(dates)
                rows.append(
                    {
                        "definition": "observed",
                        "threshold": threshold,
                        "persistence": need,
                        "min_obs": min_obs,
                        "censored": censored,
                        "early": early,
                        "late": late,
                        "shift": gap,
                        **{f"s{s}": dates[s] for s in seasons},
                    }
                )

    # Walsh et al. 2022: a per-season threshold, two weeks of persistence.
    walsh = {}
    for season in seasons:
        d, f = obs[season]
        walsh[season] = breakup_observed(d, f, walsh_threshold(d, f), 14, 2)
    early, late, gap, censored = shift(walsh)
    rows.append(
        {
            "definition": "walsh2022",
            "threshold": float("nan"),
            "persistence": 14,
            "min_obs": 2,
            "censored": censored,
            "early": early,
            "late": late,
            "shift": gap,
            **{f"s{s}": walsh[s] for s in seasons},
        }
    )

    pe, pl, pg, pc = shift(published)
    rows.insert(
        0,
        {
            "definition": "published (smoothed)",
            "threshold": PUBLISHED_THRESHOLD,
            "persistence": PUBLISHED_PERSISTENCE,
            "min_obs": float("nan"),
            "censored": pc,
            "early": pe,
            "late": pl,
            "shift": pg,
            **{f"s{s}": published[s] for s in seasons},
        },
    )

    frame = pd.DataFrame(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "breakup_definitions.csv"
    frame.to_csv(path, index=False)

    print("Break-up under every definition, day of year")
    print("=" * 96)
    print(
        f"{'definition':22s}{'thr':>6s}{'N':>4s}{'obs':>5s}{'cens':>6s}"
        + "".join(f"{s % 100:>5d}" for s in seasons)
        + f"{'early':>8s}{'late':>7s}{'shift':>8s}"
    )
    for _, r in frame.iterrows():
        thr: str = "adap" if np.isnan(r.threshold) else f"{r.threshold:.2f}"
        mo: str = "  " if np.isnan(r.min_obs) else f"{int(r.min_obs)}"
        cells: str = "".join(
            "    ." if pd.isna(r[f"s{s}"]) else f"{int(r[f's{s}']):5d}" for s in seasons
        )
        shown: str = "      ." if np.isnan(r["shift"]) else f"{r['shift']:+8.1f}"
        print(
            f"{r.definition:22s}{thr:>6s}{int(r.persistence):4d}{mo:>5s}"
            f"{int(r.censored):6d}{cells}{r.early:8.1f}{r.late:7.1f}{shown}"
        )
    print()
    print(f"written to {path}")
    print()
    print(
        "cens is how many of the ten seasons produced no date at all. A definition\n"
        "that censors half the record is not a stricter measurement, it is a\n"
        "different and smaller sample, and its shift is not comparable to a row\n"
        "that dates every season."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
