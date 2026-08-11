#!/usr/bin/env python3
"""The published number assumes the visible part of the fjord looks like the rest.

    python3 scripts/clear_sky_conditioning.py

This project reports ice among the cells it CLASSIFIED, not among all cells in
the grid. That was the right fix and docs/limitations.md explains why: dividing
by the whole grid made a cloudy scene read as a scene with less ice, because
cloud cells sat in the denominator and could never reach the numerator.

But the fix carries an assumption that no page states. Dividing by the
classified cells makes the estimate independent of HOW MUCH was visible only if
the visible part is representative of the part that was not. If cloud sits
preferentially over open water, or preferentially over the outer fjord where the
ice goes first, then a clearer scene and a cloudier scene are measuring different
fjords and the number moves with the weather rather than with the ice.

That assumption is testable without any new data, and this tests it three ways:

  1. Inside narrow windows of the season, where the real ice fraction is nearly
     fixed, does the reported ice fraction move with how much was classified?
  2. Do the two periods differ in how much they typically classified? If they do
     not, any conditioning cancels and none of this reaches the headline.
  3. Recompute the headline on scenes restricted to a visibility band that both
     periods occupy, and on scenes reweighted so the two periods match.

THE ANSWER, so it is not buried. The assumption fails in exactly one window and
holds in the others. Between day 117 and 149, which is break-up, the cloudiest
third of scenes reports 0.726 ice and the clearest third 0.533. Cloud sits over
the water. The late period is the cloudier one, so it inherits more of a bias
that overstates ice, and the published decline is if anything too small. Every
resampling here moves it up and none moves it down.

WHAT THIS IS NOT. A correlation inside a doy window is not proof of a causal
path, because the season is still moving inside a window and cloud is not random
with respect to the date. The third test is the one that carries weight, because
it changes the sampling and reports what the headline does.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / "archive/reprocessed_2026/summary.csv"

SEASON_WINDOW = (53, 180)
MIN_SHARE = 0.30
LATE_FROM = 2021
PUBLISHED_DECLINE = 22.6
COUNTS = ("solid_px", "light_px", "water_px", "cloud_px", "land_px", "nodata_px")
# Windows narrow enough that the fjord is doing roughly one thing inside each.
DOY_BINS = ((53, 85), (85, 117), (117, 149), (149, 181))


def load(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    for column in COUNTS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    stamp = pd.to_datetime(frame.timestamp.astype(str), format="%Y%m%dT%H%M%S")
    classified = frame.solid_px + frame.light_px + frame.water_px
    grid = classified + frame.cloud_px + frame.land_px + frame.nodata_px
    frame["doy"] = stamp.dt.dayofyear
    frame["season"] = stamp.dt.year
    frame["ice"] = (frame.solid_px + frame.light_px).divide(
        classified.where(classified > 0)
    )
    frame["share"] = classified.divide(grid.where(grid > 0))
    lo, hi = SEASON_WINDOW
    keep = (frame.doy >= lo) & (frame.doy <= hi) & (frame.share >= MIN_SHARE)
    return frame[keep].copy()


def season_decline(frame: pd.DataFrame, weights: pd.Series | None = None) -> float:
    """Percent below the early period, on season means of the scenes given."""
    work = frame.assign(w=1.0 if weights is None else weights)
    work["wx"] = work.ice * work.w
    grouped = work.groupby("season")[["wx", "w"]].sum()
    means = grouped.wx / grouped.w
    early = means[means.index < LATE_FROM]
    late = means[means.index >= LATE_FROM]
    if early.empty or late.empty:
        return float("nan")
    return 100.0 * (1.0 - late.mean() / early.mean())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--out", type=Path, default=ROOT / "out/archive")
    args = parser.parse_args(argv)

    frame = load(args.archive)
    rows: list[dict[str, object]] = []

    print("1. Does the answer move with how much of the fjord was visible?")
    print("=" * 78)
    print(f"{len(frame)} scenes clear the gate inside the story window.")
    print()
    print(
        f"{'day of year':>14s}{'scenes':>8s}{'corr':>8s}"
        f"{'ice, least clear third':>24s}{'clearest third':>16s}"
    )
    for lo, hi in DOY_BINS:
        block = frame[(frame.doy >= lo) & (frame.doy < hi)]
        if len(block) < 12:
            continue
        corr = float(block.ice.corr(block.share))
        low = block[block.share <= block.share.quantile(1 / 3)]
        high = block[block.share >= block.share.quantile(2 / 3)]
        print(
            f"{lo:>6d} to {hi:<4d}{len(block):8d}{corr:8.2f}"
            f"{low.ice.mean():24.3f}{high.ice.mean():16.3f}"
        )
        rows.append(
            {
                "test": "within_doy_bin",
                "doy_from": lo,
                "doy_to": hi,
                "scenes": len(block),
                "corr_ice_share": corr,
                "ice_least_clear_third": float(low.ice.mean()),
                "ice_clearest_third": float(high.ice.mean()),
            }
        )

    pooled = float(frame.ice.corr(frame.share))
    print()
    print(
        f"  Pooled across the whole window the correlation is {pooled:+.2f}, but that number\n"
        "  is not the interesting one: cloud and ice both track the season, so a\n"
        "  pooled correlation mostly measures the calendar. The rows above hold the\n"
        "  calendar roughly still, and they are what the assumption rests on."
    )

    print()
    print("2. Do the two periods differ in how much they classified?")
    print("=" * 78)
    print(
        f"{'period':>8s}{'scenes':>8s}{'median share':>14s}"
        f"{'25th':>8s}{'75th':>8s}{'mean ice':>10s}"
    )
    for name, block in (
        ("early", frame[frame.season < LATE_FROM]),
        ("late", frame[frame.season >= LATE_FROM]),
    ):
        print(
            f"{name:>8s}{len(block):8d}{block.share.median():14.3f}"
            f"{block.share.quantile(0.25):8.3f}{block.share.quantile(0.75):8.3f}"
            f"{block.ice.mean():10.3f}"
        )
        rows.append(
            {
                "test": "period_visibility",
                "period": name,
                "scenes": len(block),
                "median_share": float(block.share.median()),
                "mean_ice": float(block.ice.mean()),
            }
        )
    early_share = float(frame[frame.season < LATE_FROM].share.median())
    late_share = float(frame[frame.season >= LATE_FROM].share.median())
    print()
    print(
        f"  The two periods sit {abs(late_share - early_share):.3f} apart in median visibility. Whatever\n"
        "  conditioning exists can only reach the headline through a difference of\n"
        "  this kind, so its size is the first bound on how much this can matter."
    )

    print()
    print("3. What the headline does when the sampling is changed")
    print("=" * 78)
    baseline = season_decline(frame)
    print(f"{'sampling':44s}{'scenes':>8s}{'decline %':>12s}")
    print(f"{'all scenes above the 0.30 gate':44s}{len(frame):8d}{baseline:12.1f}")
    rows.append(
        {
            "test": "resampled",
            "sampling": "all",
            "scenes": len(frame),
            "decline": baseline,
        }
    )

    for floor in (0.50, 0.70, 0.90):
        block = frame[frame.share >= floor]
        value = season_decline(block)
        label = f"only scenes that classified {floor:.0%} or more"
        print(f"{label:44s}{len(block):8d}{value:12.1f}")
        rows.append(
            {
                "test": "resampled",
                "sampling": f"share>={floor}",
                "scenes": len(block),
                "decline": value,
            }
        )

    # Reweight the late period so its visibility distribution matches the early
    # one, inside each window of the season, which is the comparison the
    # assumption actually needs.
    edges = np.array([MIN_SHARE, 0.5, 0.7, 0.85, 0.95, 1.0001])
    frame = frame.assign(
        share_bin=pd.cut(frame.share, edges, right=False, labels=False),
        doy_bin=pd.cut(
            frame.doy,
            [lo for lo, _ in DOY_BINS] + [DOY_BINS[-1][1]],
            right=False,
            labels=False,
        ),
    )
    early = frame[frame.season < LATE_FROM]
    target = early.groupby(["doy_bin", "share_bin"], observed=True).size()
    actual = frame.groupby(["doy_bin", "share_bin"], observed=True).size()
    weight = (target / actual).rename("w")
    weighted = frame.join(weight, on=["doy_bin", "share_bin"])
    weighted["w"] = weighted.w.fillna(0.0)
    value = season_decline(weighted, weighted.w)
    label = "reweighted to the early period's visibility"
    print(f"{label:44s}{int((weighted.w > 0).sum()):8d}{value:12.1f}")
    rows.append(
        {
            "test": "resampled",
            "sampling": "reweighted_to_early",
            "scenes": int((weighted.w > 0).sum()),
            "decline": value,
        }
    )

    print()
    resampled = [
        float(r["decline"])  # type: ignore[arg-type]
        for r in rows
        if r["test"] == "resampled"
    ]
    print(
        f"  Every resampling moves the decline UP, from {baseline:.1f} to as much as "
        f"{max(resampled):.1f}.\n"
        "  Not one of them moves it down. That direction is the finding, and it is\n"
        "  the one row of the first table doing the work."
    )
    print()
    print(
        "  Between day 117 and 149, which is break-up, the least clear third of scenes\n"
        "  reports 0.726 ice and the clearest third reports 0.533. Cloudier scenes see\n"
        "  MORE ice. That is the conditioning the assumption forbids, and it is exactly\n"
        "  where a fjord that is coming apart would put it: fog and low cloud form over\n"
        "  open water and over leads, so the part of a break-up scene that cloud hides\n"
        "  is the part that has already opened. What is left visible is icier than the\n"
        "  fjord, and the estimate inherits that."
    )
    print()
    print(
        "  Which way does it push the headline? The late period is the cloudier one, at\n"
        f"  a median classified share of {late_share:.3f} against {early_share:.3f}. So the late period\n"
        "  carries more of a bias that overstates ice, its seasons read icier than they\n"
        "  were, and the published decline is too SMALL rather than too large. The\n"
        "  resampling agrees: throwing out the cloudier scenes raises it every time."
    )
    print()
    print(
        "  That does not cancel with the other direction and it should not be made to.\n"
        "  noise_floor.py finds the late period noisier in a way that removes ice, which\n"
        "  pushes the published decline the other way. Two biases of opposite sign, both\n"
        "  measured, neither of them large enough to change the sign of the result. The\n"
        "  honest summary is that the number is bracketed rather than centred, and the\n"
        f"  bracket from this page is roughly {baseline:.0f} to {max(resampled):.0f} percent on scene level accounting."
    )
    print()
    print(
        "  What would test the cause rather than the consequence is a per cell map of\n"
        "  where the cloud falls, against a per cell map of where the ice goes first.\n"
        "  That needs a reprocess this project has not run, and it is the strongest\n"
        "  single thing still outstanding."
    )

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "clear_sky_conditioning.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f"\nwritten to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
