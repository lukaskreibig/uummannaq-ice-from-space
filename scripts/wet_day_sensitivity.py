#!/usr/bin/env python3
"""How much of the published decline rests on twelve suspect April scenes?

Three measurements now point at the same twelve days, and they are the twelve
[limitations.md](../docs/limitations.md) already flags: April scenes reporting
below 0.90 ice three to six weeks before their own season broke up, clustered in
2021, 2023 and 2025 at a permutation p of 0.0018, all in the late period.

    season_end_calibration.py  found them, and measured the median April scene
                               as accurate to 0.0019
    landsat_crosscheck.py      showed a second optical instrument reads the same
                               surface wetter still, four times out of four
    ice_endmember_stability.py explained why: the fast ice of 2023 was 34 percent
                               darker than the ten-season median, and a fixed
                               brightness gate loses more of a darker surface

What none of them answers is the only question a reader will actually ask. If
those readings are partly a reading error rather than ice loss, does the
headline survive?

    python3 scripts/wet_day_sensitivity.py

Three variants of the SAME raw archive, each pushed through the published
cleaning implementation rather than a second copy of it:

    published   the archive as it stands
    dropped     the suspect scenes removed, so the gap filling interpolates
                across them from their own neighbours
    frozen      the suspect scenes forced to a fully frozen fjord, which is the
                most generous assumption available: every one of them was ice

The third is the bound that matters. If the decline still stands when every
suspect day is handed back its ice in full, then nothing in the headline rests
on them.

Importing clean_series from the story's pipeline is deliberate. story_numbers.py
refuses to rebuild the daily series because two implementations that agree prove
nothing about which one ships. That objection does not apply to using the one
that ships.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from story_numbers import (  # noqa: E402
    LATE_FROM,
    SEASON_WINDOW,
    exact_permutation,
    mann_kendall,
    spring_means,
)

DEFAULT_ARCHIVE = ROOT / "archive/reprocessed_2026/summary.csv"
DEFAULT_PIPELINE = ROOT.parent / "climate-dashboard/data-pipeline"
DEFAULT_PUBLISHED = ROOT / "docs/published_numbers.json"

# The same window season_end_calibration.py uses, and for the same reason: the
# earliest break-up in the whole record is 30 April 2021, so a fjord cannot be
# legitimately open here.
APRIL_WINDOW = (91, 110)
MIN_CLASSIFIED_SHARE = 0.30
OUTLIER_BELOW = 0.90

COUNTS = ("solid_px", "light_px", "water_px", "cloud_px", "land_px", "nodata_px")


def load_raw(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    for col in COUNTS:
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
    stamp = pd.to_datetime(frame.timestamp.astype(str), format="%Y%m%dT%H%M%S")
    frame["doy"] = stamp.dt.dayofyear
    frame["season"] = stamp.dt.year
    frame["day"] = stamp.dt.date
    classified = frame.solid_px + frame.light_px + frame.water_px
    grid = classified + frame.cloud_px + frame.land_px + frame.nodata_px
    frame["ice"] = (frame.solid_px + frame.light_px).divide(
        classified.where(classified > 0)
    )
    frame["share"] = classified.divide(grid.where(grid > 0))
    return frame


def suspects(frame: pd.DataFrame) -> pd.Index:
    lo, hi = APRIL_WINDOW
    return frame.index[
        (frame.doy >= lo)
        & (frame.doy <= hi)
        & (frame.share >= MIN_CLASSIFIED_SHARE)
        & (frame.ice < OUTLIER_BELOW)
    ]


def statistics(daily: pd.DataFrame) -> dict:
    means = spring_means(daily)
    seasons = sorted(means.index)
    values = means.loc[seasons].to_numpy()
    n_early = sum(1 for s in seasons if s < LATE_FROM)
    early = float(values[:n_early].mean())
    late = float(values[n_early:].mean())
    gap, p_perm, _, _ = exact_permutation(values, n_early)
    return {
        "means": {
            int(s): round(float(v), 3) for s, v in zip(seasons, values, strict=True)
        },
        "early": early,
        "late": late,
        "decline": 100.0 * (1.0 - late / early),
        "gap": float(gap),
        "p_perm": float(p_perm),
        "p_mk": float(mann_kendall(values)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--pipeline", type=Path, default=DEFAULT_PIPELINE)
    args = parser.parse_args(argv)

    if not args.pipeline.exists():
        print(f"story pipeline not found at {args.pipeline}")
        return 2
    sys.path.insert(0, str(args.pipeline))
    from refresh_fjord_season import clean_series  # noqa: PLC0415

    raw = load_raw(args.archive)
    flagged = suspects(raw)
    lo, hi = APRIL_WINDOW
    window = raw[
        (raw.doy >= lo) & (raw.doy <= hi) & (raw.share >= MIN_CLASSIFIED_SHARE)
    ]

    print("The suspect scenes")
    print("=" * 72)
    print(
        f"{len(flagged)} of {len(window)} April scenes (day {lo} to {hi}, "
        f"classified share at least {MIN_CLASSIFIED_SHARE:.2f}) read below "
        f"{OUTLIER_BELOW:.2f} ice"
    )
    print()
    print(f"{'day':12s}{'season':>8s}{'ice':>8s}{'share':>8s}")
    for _, r in raw.loc[flagged].sort_values("day").iterrows():
        print(f"{str(r.day):12s}{int(r.season):8d}{r.ice:8.3f}{r.share:8.3f}")
    per_season = raw.loc[flagged].groupby("season").size()
    print()
    print("per season: " + ", ".join(f"{s}: {n}" for s, n in per_season.items()))

    # Variant construction. Only the pixel counts are touched, because those are
    # what the published cleaning reads.
    dropped = raw.drop(index=flagged)
    frozen = raw.copy()
    frozen.loc[flagged, "solid_px"] = (
        frozen.loc[flagged, "solid_px"]
        + frozen.loc[flagged, "light_px"]
        + frozen.loc[flagged, "water_px"]
    )
    frozen.loc[flagged, "light_px"] = 0.0
    frozen.loc[flagged, "water_px"] = 0.0

    variants = {
        "published": raw,
        "dropped": dropped,
        "frozen": frozen,
    }
    results = {name: statistics(clean_series(f)) for name, f in variants.items()}

    print()
    print("What each variant does to the headline")
    print("=" * 72)
    win_lo, win_hi = SEASON_WINDOW
    print(f"spring means over day {win_lo} to {win_hi}, early is before {LATE_FROM}")
    print()
    print(
        f"{'variant':12s}{'early':>8s}{'late':>8s}{'decline':>10s}"
        f"{'perm p':>9s}{'MK p':>8s}"
    )
    for name, got in results.items():
        print(
            f"{name:12s}{got['early']:8.4f}{got['late']:8.4f}"
            f"{got['decline']:9.1f} %{got['p_perm']:9.3f}{got['p_mk']:8.3f}"
        )

    print()
    print("Season means, and how far each variant moves them")
    print("-" * 72)
    seasons = sorted(results["published"]["means"])
    print(f"{'season':10s}" + "".join(f"{n:>12s}" for n in variants))
    for season in seasons:
        row = "".join(f"{results[n]['means'][season]:12.3f}" for n in variants)
        print(f"{season:<10d}{row}")

    # The check that makes the rest readable: does the published variant
    # reproduce the committed claims? If it does not, nothing below it means
    # anything, because the baseline is not the baseline.
    print()
    print("Baseline check against docs/published_numbers.json")
    print("-" * 72)
    if DEFAULT_PUBLISHED.exists():
        import json

        claimed = json.loads(DEFAULT_PUBLISHED.read_text())
        got = results["published"]
        pairs = [
            ("decline_percent", claimed["decline_percent"], got["decline"]),
            ("permutation_p", claimed["permutation_p"], got["p_perm"]),
            ("early_mean", claimed["early_mean"], got["early"]),
            ("late_mean", claimed["late_mean"], got["late"]),
        ]
        worst = 0.0
        for label, want, have in pairs:
            delta = abs(float(want) - float(have))
            worst = max(worst, delta)
            print(f"{label:20s} published {want:8.4f}   rebuilt {have:8.4f}")
        if worst > 0.05:
            print()
            print(
                "The rebuilt baseline does not match what is published. The\n"
                "variants below are therefore not comparable to the story and\n"
                "this run should not be quoted until that is resolved."
            )
            return 1
        print()
        print(f"largest difference {worst:.4f}, so the variants are comparable")
    else:
        print("no committed claims to compare against")

    published, frozen_got = results["published"], results["frozen"]
    print()
    print("The bound")
    print("=" * 72)
    kept = 100.0 * frozen_got["decline"] / max(published["decline"], 1e-9)
    print(
        f"Handing every suspect scene back a fully frozen fjord, the decline goes\n"
        f"from {published['decline']:.1f} percent to {frozen_got['decline']:.1f} "
        f"percent, which is {kept:.0f} percent of it, and the permutation p goes\n"
        f"from {published['p_perm']:.3f} to {frozen_got['p_perm']:.3f}."
    )
    print()
    print("And what this does NOT bound")
    print("-" * 72)
    print(
        "Only the days that crossed 0.90 are tested here. ice_endmember_stability\n"
        "measured a brightness shift that runs through a whole season, not through\n"
        "twelve days, so a milder version of the same error can sit on every day\n"
        "of 2023 and 2025 without any single one of them falling far enough to be\n"
        "caught by this. That version has no anchor: outside the April window and\n"
        "before July there is no day in this fjord whose answer is certain, so\n"
        "there is nothing to measure it against. The bound above is a bound on the\n"
        "identified days, not on the mechanism."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
