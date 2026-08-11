#!/usr/bin/env python3
"""Carry the thermal and radar correction onto the series the story publishes.

Everything in landsat-crosscheck.md part four is measured on the LANDSAT series.
The story publishes Sentinel-2. Part three showed the two agree on the days in
question to r = +0.986, so the failure is in both, but a correction measured on
one series is not a correction of the other until it is computed there. This
computes it there.

    python3 scripts/sentinel_correction.py
    python3 scripts/sentinel_correction.py --match 0 --match 1 --match 2 --match 3

HOW A SENTINEL-2 DAY GETS A VERDICT. Sentinel-2 carries no thermal band, so the
evidence has to come from Landsat, which flies on other days. Each Sentinel-2
scene is matched to the nearest Landsat thermal reading within `--match` days and
is CONTRADICTED when it reports less than half ice while that reading puts more
than half the fjord below the freezing point of seawater. Zero days is the
cleanest match and the thinnest sample; the run reports several so the trade is
visible rather than chosen.

Two days is defensible in the frozen part of the season, where a fjord does not
change state overnight, and less so through break-up. The doy distribution of the
flagged days is printed for that reason.

WHAT REPLACES A CONTRADICTED VALUE. The radar position of that day where
sar_thermal_days.py could place one, and the median position of the placed days
otherwise. Only the pixel counts are rewritten, because those are what the
published cleaning reads, and the cleaning then runs unchanged: the same
interpolation, the same day-of-year climatology, the same double smoothing that
produces frac_smooth. The climatology is recomputed from the corrected values,
which is correct and does mean a corrected day moves the days that were filled
from it.

THE PUBLISHED NUMBER THIS HAS TO REPRODUCE FIRST. 22.6 percent comes from
frac_smooth over day 53 to 180, not from the observed scenes, which give 27.0.
The run refuses to report a correction if it cannot reproduce the published
baseline to the decimal.
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
    exact_permutation,
    mann_kendall,
    spring_means,
)

DEFAULT_ARCHIVE = ROOT / "archive/reprocessed_2026/summary.csv"
DEFAULT_THERMAL = ROOT / "archive/reprocessed_2026/thermal_audit.csv"
DEFAULT_VERDICTS = ROOT / "archive/reprocessed_2026/sar_thermal_verdicts.csv"
DEFAULT_PIPELINE = ROOT.parent / "climate-dashboard/data-pipeline"

COUNTS = ("solid_px", "light_px", "water_px", "cloud_px", "land_px", "nodata_px")
MIN_SHARE = 0.30
OPEN_CALL = 0.50  # the chain is calling the fjord mostly open
FROZEN_CALL = 0.50  # the thermal band is calling it mostly frozen
PUBLISHED_DECLINE = 22.6


def load_raw(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    for col in COUNTS:
        # float, not int: the corrected variants write fractional counts
        frame[col] = (
            pd.to_numeric(frame[col], errors="coerce").fillna(0.0).astype(float)
        )
    stamp = pd.to_datetime(frame.timestamp.astype(str), format="%Y%m%dT%H%M%S")
    frame["doy"] = stamp.dt.dayofyear
    frame["season"] = stamp.dt.year
    frame["day"] = stamp.dt.date
    classified = frame.solid_px + frame.light_px + frame.water_px
    grid = classified + frame.cloud_px + frame.land_px + frame.nodata_px
    frame["classified"] = classified
    frame["ice"] = (frame.solid_px + frame.light_px).divide(
        classified.where(classified > 0)
    )
    frame["share"] = classified.divide(grid.where(grid > 0))
    return frame


def evidence(thermal: Path, verdicts: Path) -> pd.DataFrame:
    """One row per Landsat day: was it frozen, and where did radar place it?"""
    t = pd.read_csv(thermal)[["day", "frozen_share", "landsat_ice"]]
    t["date"] = pd.to_datetime(t.day).astype("datetime64[ns]")
    v = pd.read_csv(verdicts)
    # A day radar could not place carries no position; filter on that
    # rather than on the label, which is prose and may be reworded.
    v = v[v.pos.notna()][["day", "pos", "verdict"]]
    out = t.merge(v, on="day", how="left")
    out["radar_ice"] = out.pos.clip(0.0, 1.0)
    return out.sort_values("date")


def flag(raw: pd.DataFrame, ev: pd.DataFrame, match: int) -> pd.DataFrame:
    """Attach the nearest Landsat evidence within `match` days to every scene."""
    left = raw.copy()
    left["date"] = pd.to_datetime(left.day).astype("datetime64[ns]")
    joined = pd.merge_asof(
        left.sort_values("date"),
        ev.sort_values("date")[["date", "frozen_share", "radar_ice", "verdict"]],
        on="date",
        direction="nearest",
        tolerance=pd.Timedelta(days=match),
    )
    joined["contradicted"] = (
        (joined.share >= MIN_SHARE)
        & (joined.ice < OPEN_CALL)
        & (joined.frozen_share > FROZEN_CALL)
    ).fillna(False)
    return joined


def set_ice(frame: pd.DataFrame, index, target) -> pd.DataFrame:
    """Rewrite the pixel counts of those rows to a given ice fraction."""
    out = frame.copy()
    classified = out.loc[index, "classified"]
    out.loc[index, "solid_px"] = classified * target
    out.loc[index, "light_px"] = 0.0
    out.loc[index, "water_px"] = classified * (1.0 - target)
    return out


def statistics(daily: pd.DataFrame) -> dict:
    means = spring_means(daily)
    seasons = sorted(means.index)
    values = means.loc[seasons].to_numpy()
    n_early = sum(1 for s in seasons if s < LATE_FROM)
    early, late = float(values[:n_early].mean()), float(values[n_early:].mean())
    gap, p_perm, _, _ = exact_permutation(values, n_early)
    return {
        "means": {int(s): float(v) for s, v in zip(seasons, values, strict=True)},
        "early": early,
        "late": late,
        "decline": 100.0 * (1.0 - late / early),
        "p_perm": float(p_perm),
        "p_mk": float(mann_kendall(values)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--thermal", type=Path, default=DEFAULT_THERMAL)
    parser.add_argument("--verdicts", type=Path, default=DEFAULT_VERDICTS)
    parser.add_argument("--pipeline", type=Path, default=DEFAULT_PIPELINE)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    parser.add_argument("--match", type=int, action="append", default=None)
    args = parser.parse_args(argv)
    matches = args.match or [0, 1, 2, 3]

    sys.path.insert(0, str(args.pipeline))
    from refresh_fjord_season import clean_series  # noqa: PLC0415

    raw = load_raw(args.archive)
    ev = evidence(args.thermal, args.verdicts)
    median_pos = float(ev.radar_ice.median())

    base = statistics(clean_series(raw))
    print("Does this reproduce the published baseline?")
    print("=" * 78)
    print(
        f"  computed {base['decline']:.1f} percent against a published "
        f"{PUBLISHED_DECLINE:.1f}"
    )
    if abs(base["decline"] - PUBLISHED_DECLINE) > 0.05:
        print("\n  It does not. Nothing below would be a correction OF the headline.")
        return 1
    print("  yes, so what follows is a correction of that number and not of another")
    print()
    print(
        f"Radar placed days have a median position of {median_pos:.2f} between their "
        f"own\nseason's open water and its fast ice. That is what a contradicted day "
        "with no\nradar verdict of its own is given."
    )

    rows: list[dict] = []
    for match in matches:
        marked = flag(raw, ev, match)
        hits = marked.index[marked.contradicted]
        if not len(hits):
            continue
        early = int((marked.loc[hits, "season"] < LATE_FROM).sum())
        late = int((marked.loc[hits, "season"] >= LATE_FROM).sum())

        target = marked.loc[hits, "radar_ice"].fillna(median_pos)
        radar = statistics(clean_series(set_ice(marked, hits, target)))
        frozen = statistics(clean_series(set_ice(marked, hits, 1.0)))
        rows.append(
            {
                "match_days": match,
                "flagged": len(hits),
                "flagged_early": early,
                "flagged_late": late,
                "with_radar_verdict": int(marked.loc[hits, "radar_ice"].notna().sum()),
                "published": base["decline"],
                "radar_corrected": radar["decline"],
                "all_frozen": frozen["decline"],
                "p_perm_published": base["p_perm"],
                "p_perm_corrected": radar["p_perm"],
                "doy_median": float(marked.loc[hits, "doy"].median()),
            }
        )

    frame = pd.DataFrame(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "sentinel_correction.csv"
    frame.to_csv(path, index=False)

    print()
    print("The correction on the published series")
    print("=" * 78)
    print(
        f"{'match':>7s}{'flagged':>9s}{'early':>7s}{'late':>6s}{'w/ radar':>10s}"
        f"{'published':>11s}{'corrected':>11s}{'all frozen':>12s}{'median doy':>12s}"
    )
    for r in rows:
        print(
            f"{r['match_days']:>5d} d{r['flagged']:9d}{r['flagged_early']:7d}"
            f"{r['flagged_late']:6d}{r['with_radar_verdict']:10d}"
            f"{r['published']:10.1f} %{r['radar_corrected']:10.1f} %"
            f"{r['all_frozen']:11.1f} %{r['doy_median']:12.0f}"
        )
    print()
    print(
        "  match is how many days a Sentinel-2 scene may be from the Landsat\n"
        "  reading that judges it. Zero is the cleanest and the thinnest."
    )
    print(f"\nwritten to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
