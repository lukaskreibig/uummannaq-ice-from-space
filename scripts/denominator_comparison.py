#!/usr/bin/env python3
"""What the choice of denominator does to the published decline.

The pipeline has used three denominators over its life, and the difference
between them is larger than any other analysis choice in this project. Every
page that describes the method quotes a number from this comparison, so the
comparison needs a script rather than a memory.

    python3 scripts/denominator_comparison.py
    python3 scripts/denominator_comparison.py --window 45 180

The three:

  whole grid    Every cell of the AOI, including cloud, land and data gaps. A
                cell classified as cloud can never also be ice, so a cloudy day
                mechanically reports less ice however much ice lies under it.
                Cloud is not evenly spread over this record, which is what makes
                this denominator a trap rather than merely a conservative choice.

  clear cells   Everything that is not cloud, not land and not a data gap. This
                is what the archive's `clear_px` column carries and what the
                pipeline published until August 2026.

  classified    The cells that came out as something: solid, light or water. A
                cell can be perfectly visible and still land in no class, because
                ice needs NDSI and both brightness floors while water needs NDWI,
                and a dark cell reaches neither. Those cells sat in the clear-sky
                denominator while they could never reach a numerator, which is
                the same error as the whole grid one scale down, pointing the
                same way. This is what the series publishes now.

The gate belongs with the third: a scene that classified less than 30 percent of
the AOI is not a measurement of it and is dropped rather than averaged in.

The estimator here is the mean of the per-day values in each period, which is
the honest one to compare denominators with because it touches no gap filling.
It is NOT the published headline, which is a gap-filled seasonal mean and is
computed in the story repository. Two different questions, two numbers, and this
script prints the one it is answering.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

DEFAULT_ARCHIVE = Path("archive/reprocessed_2026/summary.csv")
STORY_WINDOW = (53, 180)
MIN_CLASSIFIED_SHARE = 0.30
LATE_FROM = 2021


def load(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    counts = ["solid_px", "light_px", "water_px", "cloud_px", "land_px", "nodata_px"]
    for col in counts:
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
    day = pd.to_datetime(frame["timestamp"].astype(str).str[:8], format="%Y%m%d")
    frame["day"] = day
    frame["doy"] = day.dt.dayofyear
    frame["season"] = day.dt.year

    ice = frame.solid_px + frame.light_px
    classified = ice + frame.water_px
    grid = classified + frame.cloud_px + frame.land_px + frame.nodata_px
    clear = pd.to_numeric(frame.get("clear_px"), errors="coerce")

    frame["ice_grid"] = ice.divide(grid.where(grid > 0))
    frame["ice_clear"] = ice.divide(clear.where(clear > 0))
    frame["ice_classified"] = ice.divide(classified.where(classified > 0))
    frame["cloud_frac"] = frame.cloud_px.divide(grid.where(grid > 0))
    frame["classified_share"] = classified.divide(grid.where(grid > 0))
    return frame


def decline(frame: pd.DataFrame, column: str) -> tuple[float, float, float, int]:
    """Early and late period means over days, and the decline between them."""
    daily = (
        frame.dropna(subset=[column])
        .groupby(["season", "doy"])[column]
        .mean()
        .reset_index()
    )
    early = daily[daily.season < LATE_FROM][column].mean()
    late = daily[daily.season >= LATE_FROM][column].mean()
    return early, late, 100.0 * (1.0 - late / early), len(daily)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument(
        "--window",
        type=int,
        nargs=2,
        default=list(STORY_WINDOW),
        metavar=("START_DOY", "END_DOY"),
    )
    args = parser.parse_args(argv)

    if not args.archive.exists():
        print(f"archive not found: {args.archive}")
        return 2

    frame = load(args.archive)
    lo, hi = args.window
    win = frame[(frame.doy >= lo) & (frame.doy <= hi)]
    gated = win[win.classified_share >= MIN_CLASSIFIED_SHARE]

    print(f"Denominator comparison, day {lo} to {hi}, archive {args.archive}")
    print("=" * 72)
    print(
        f"{len(win)} scenes in the window, {len(gated)} clear the "
        f"{MIN_CLASSIFIED_SHARE:.0%} gate, {len(win) - len(gated)} dropped "
        f"({100 * (1 - len(gated) / len(win)):.1f} %)"
    )
    early_cloud = win[win.season < LATE_FROM].cloud_frac.mean()
    late_cloud = win[win.season >= LATE_FROM].cloud_frac.mean()
    print(
        f"mean cloud cover: {early_cloud:.3f} in 2017 to 2020, "
        f"{late_cloud:.3f} from 2021, a rise of "
        f"{100 * (late_cloud / early_cloud - 1):.0f} percent"
    )
    print()
    print("decline from the early to the late period, mean of the daily values:")
    rows = [
        ("whole grid, every scene", win, "ice_grid"),
        ("clear cells, every scene", win, "ice_clear"),
        ("classified, every scene", win, "ice_classified"),
        ("classified, after the gate", gated, "ice_classified"),
    ]
    for label, source, column in rows:
        early, late, pct, n = decline(source, column)
        print(f"    {label:28s} {n:4d} days   {early:.4f} to {late:.4f}   {pct:5.1f} %")
    print()
    print(
        "The last row is the one the series publishes. The first is what it used\n"
        "to publish, and the gap between them is the cloud trend being read as ice\n"
        "loss. The third row shows why the gate belongs with the new denominator:\n"
        "without it, scenes that classified almost nothing still carry a full vote."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
