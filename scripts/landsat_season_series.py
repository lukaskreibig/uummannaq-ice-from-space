#!/usr/bin/env python3
"""A second, independent ice-fraction series from one sensor, 2013 to 2026.

The record is ten seasons and that is the binding limit on everything this
project can conclude. Going further back with Landsat looked blocked, and the
plan behind this repository said so, but its numbers came from the wrong
catalogue. Measured over the USGS archive by `landsat_l1_inventory.py --reach`
there is far more data than it claimed: 36 seasons from 1990, at a median of 31
scenes inside the window.

What is genuinely blocked is the calibration. A fixed threshold needs
same-overpass pairs to be carried across a sensor change, and over this AOI, in
the whole archive, there are zero between TM and ETM+ and zero between TM and
OLI. The boundaries fall in 1999 and 2013, exactly where an early-late split
would sit, so an uncalibrated join would be indistinguishable from the trend it
is meant to measure. ETM+ against OLI has two pairs and neither is a calibration:
2019-06-06 is midnight sun at 10 degrees over ice already breaking up, and
2013-03-30, which is otherwise perfect, fixes the relationship at exactly ONE
surface state. That state turns out to be dark ice near the bottom of the range,
and a gain and an offset across the dynamic range cannot be fitted from one
point. Steiro et al. (2021) did reach back to 1985 here, by setting thresholds
per image from histogram analysis, which sidesteps calibration by putting an
analyst inside every measurement. That is a study; this is a pipeline.

So this takes the one extension that crosses no boundary at all: **Landsat 8 and
9 alone**, one instrument family throughout.

    python3 scripts/landsat_season_series.py --seasons 2013-2026

The sun-angle correction of landsat_l1_crosscheck.py applies here unchanged and
for the same reason: Sentinel-2 L1C carries it and Landsat Level 1 does not.

WHAT A SEASON MEAN IS HERE, because two versions of this were wrong before the
third. Landsat contributes 9 to 30 usable days a season against Sentinel-2's 25
to 68, and they are not spread the same way through the window, so a plain mean
over whatever days each sensor holds compares two different estimators and calls
the gap an instrument difference. Fifteen-day bins fix that much. They do not fix
the part that mattered more: averaging over the bins a sensor HAPPENED to fill
still compares different parts of the season, and ice falls steeply through the
window. Landsat 2017 samples February to mid May and nothing after, reads 0.993
that way, and sitting next to Sentinel-2's whole-window 0.864 it manufactured a
difference of +0.129 that has nothing to do with instruments. On the six bins
both sensors filled, 2017 reads 0.993 against 0.981.

So: nine bins, gaps inside the sampled range interpolated, and a season that
never sampled the break-up dropped rather than reported. The two-sensor
comparison is taken only over bins both sensors filled, which is a different
question from a season mean and is allowed to keep seasons the series drops.

A CUT THAT USED TO BE HERE, and why it is gone. Four scenes in March and early
April 2013 are nearly cloud free over a fjord every other year calls frozen and
still read 5, 10, 15 and 15 percent ice. On 22 March the whole fjord measures
green 0.206 and near infrared 0.090, where fast ice sits between 0.44 and 0.74,
so every cell fails the brightness gate and falls through to water. They are all
Tier 1, so it is not a catalogue flag. The obvious suspect was the satellite:
Landsat 8 launched on 11 February 2013 and reached its operational WRS-2 orbit on
11 April, and all four scenes are earlier, so this file used to drop everything
before that published date.

That was wrong, and commissioning_check.py is what proved it. On 30 March 2013
ETM+ crossed the same fjord in the same hour at the same sun elevation, fourteen
years into normal operations, and it reads the same surface: green 0.223 against
0.226, near infrared 0.120 against 0.115, ice 0.112 against 0.098. The radiometry
was never the problem.

The thermal band then said what reflectance could not. All four days radiate
between 263.7 and 267.7 K over a fjord where seawater freezes near 271.35 K and
open water cannot go colder. The fjord was frozen, and the chain read it as water
because the surface was too dark for the brightness gate. That is the same
failure limitations.md documents on twelve wet April days, here across a whole
early season, and it is a property of the classifier rather than of 2013. So the
date cut is gone, 2013 is treated like every other season, and the error is
measured uniformly across the record by thermal_audit.py instead.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from landsat_l1_crosscheck import (  # noqa: E402
    AOI,
    MIN_CLASSIFIED_SHARE,
    SEASON_WINDOW,
    USGS_STAC,
    classify,
    read_scene,
    sentinel_series,
)

LOGGER = logging.getLogger("landsat_season_series")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / "archive/reprocessed_2026/summary.csv"
LATE_FROM = 2021

# Season means are the mean over these bins, not over scenes, so that a season
# rich in April days is not compared against one rich in February days.
#
# The upper limit is 180 and not 181, and the difference is not cosmetic. With an
# edge sitting exactly on day 180, which SEASON_WINDOW admits, np.digitize opens a
# tenth bin one calendar day wide that still casts a full vote. Four scenes in
# this record land on day 180, all after break-up at 0.000 to 0.003 ice, and the
# one in Landsat 2024 moved that season's mean by 0.084, which is ten times the
# effect this file was built to measure. Nine bins, the last spanning day 165 to
# 180 inclusive.
BIN_EDGES = np.arange(45, 180, 15)
N_BINS = len(BIN_EDGES)
MIN_BINS = 5  # a season below this is coverage, not a season
# The last two bins are the break-up. A season that never sampled them is not a
# season mean at all, it is a winter mean, and ice falls through the window: the
# per-bin means across this record run 0.65, 0.63, 0.93, 0.97, 0.84, 0.75, 0.49,
# 0.18, 0.00. Landsat 2017 fills bins 0 to 5 only and reads 0.993 that way, next
# to Sentinel-2's 0.864 over the whole window, and reporting that gap as an
# instrument difference is what this rule exists to stop.
BREAKUP_BINS = (N_BINS - 2, N_BINS - 1)


def candidates(seasons: range):
    from pystac_client import Client

    client = Client.open(USGS_STAC)
    found = []
    for year in seasons:
        for attempt in range(4):
            try:
                for item in client.search(
                    collections=["landsat-c2l1"],
                    bbox=AOI,
                    datetime=f"{year}-01-01/{year}-12-31",
                    limit=100,
                ).items():
                    p = item.properties
                    sun = p.get("view:sun_elevation")
                    when = item.datetime
                    if when is None:
                        continue
                    doy = when.timetuple().tm_yday
                    day = when.date().isoformat()
                    if sun is None or sun <= 0:
                        continue
                    if not item.id.startswith("LC0"):  # OLI only, no TM, no ETM+
                        continue
                    if not (SEASON_WINDOW[0] <= doy <= SEASON_WINDOW[1]):
                        continue
                    found.append(
                        {
                            "item": item,
                            "day": day,
                            "season": year,
                            "doy": doy,
                            "sun": sun,
                            "cloud": p.get("eo:cloud_cover") or 100.0,
                        }
                    )
                break
            except Exception:  # pragma: no cover - network-driven
                time.sleep(3 * (attempt + 1))
    # One scene per day, least cloudy, so a day cannot vote twice.
    by_day: dict[str, dict] = {}
    for c in found:
        if c["day"] not in by_day or c["cloud"] < by_day[c["day"]]["cloud"]:
            by_day[c["day"]] = c
    return sorted(by_day.values(), key=lambda c: c["day"])


def per_season_bins(
    frame: pd.DataFrame, doy: str, value: str, season: str
) -> dict[int, pd.Series]:
    """Every season's mean in every bin, NaN where the sensor never looked."""
    work = frame.dropna(subset=[value]).copy()
    work["bin"] = np.clip(np.digitize(work[doy], BIN_EDGES) - 1, 0, N_BINS - 1)
    per_bin = work.groupby([season, "bin"])[value].mean()
    return {
        int(year): per_bin.loc[year].reindex(range(N_BINS))
        for year in sorted(work[season].unique())
    }


def binned_means(
    frame: pd.DataFrame, doy: str, value: str, season: str
) -> dict[int, tuple[float, int]]:
    """Season mean over fifteen-day bins, with the number of bins observed.

    Two rules beyond the averaging, and both throw seasons away rather than
    quietly filling them in.

    A season that never sampled the break-up is dropped, because a mean over
    February to mid May is a different quantity from a mean over the whole window
    and the two must not share a column.

    Gaps INSIDE the sampled range are filled by linear interpolation between the
    bins on either side. That is the smallest assumption available and it is the
    one the story's own daily series already makes; the alternative, averaging
    over whichever bins each season happened to fill, is what produced the error
    this rule replaces. The count returned is bins actually OBSERVED, so a reader
    can see how much of a season was interpolated.
    """
    out: dict[int, tuple[float, int]] = {}
    for year, block in per_season_bins(frame, doy, value, season).items():
        if all(pd.isna(block[b]) for b in BREAKUP_BINS):
            continue
        observed = int(block.notna().sum())
        filled = block.interpolate(limit_area="inside").dropna()
        if len(filled) >= MIN_BINS:
            out[year] = (float(filled.mean()), observed)
    return out


def common_bin_comparison(
    left: dict[int, pd.Series], right: dict[int, pd.Series]
) -> list[tuple[int, int, float, float]]:
    """Compare two sensors only where both actually looked.

    A season mean is a statement about a season; this is a statement about two
    instruments, and for that the parts of the window only one of them sampled
    are not evidence about the other. A season can appear here and still be
    absent from the series above, which is not an inconsistency: 2017 has six
    bins both sensors filled, enough to compare them, and no break-up coverage on
    the Landsat side, so it cannot carry a season mean.
    """
    rows: list[tuple[int, int, float, float]] = []
    for year in sorted(set(left) & set(right)):
        both = left[year].notna() & right[year].notna()
        if int(both.sum()) >= MIN_BINS:
            rows.append(
                (
                    year,
                    int(both.sum()),
                    float(left[year][both].mean()),
                    float(right[year][both].mean()),
                )
            )
    return rows


def decline(table: dict[int, tuple[float, int]], seasons: list[int]) -> float:
    early = [table[s][0] for s in seasons if s < LATE_FROM]
    late = [table[s][0] for s in seasons if s >= LATE_FROM]
    return 100.0 * (1 - float(np.mean(late)) / float(np.mean(early)))


def decline_interval(
    table: dict[int, tuple[float, int]], seasons: list[int], draws: int = 20000
) -> tuple[float, float]:
    """Percentile bootstrap over seasons, which is the only sample there is."""
    rng = np.random.default_rng(20260811)
    early = np.array([table[s][0] for s in seasons if s < LATE_FROM])
    late = np.array([table[s][0] for s in seasons if s >= LATE_FROM])
    draw = [
        100.0
        * (
            1
            - rng.choice(late, late.size).mean() / rng.choice(early, early.size).mean()
        )
        for _ in range(draws)
    ]
    lo, hi = np.percentile(draw, [2.5, 97.5])
    return float(lo), float(hi)


def main(argv: list[str] | None = None) -> int:
    import rasterio

    from uummannaq_ice.assets import default_landmask_path

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    parser.add_argument("--seasons", default="2013-2026")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8, help="concurrent scene reads")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("rasterio").setLevel(logging.ERROR)
    logging.getLogger("botocore").setLevel(logging.WARNING)

    lo, hi = (int(x) for x in args.seasons.split("-"))
    chosen = candidates(range(lo, hi + 1))
    if args.limit:
        chosen = chosen[: args.limit]
    LOGGER.info("%d Landsat 8/9 days, %d to %d", len(chosen), lo, hi)

    with rasterio.open(default_landmask_path()) as lm:
        land_source = {"array": lm.read(1), "transform": lm.transform, "crs": lm.crs}

    # This loop is almost entirely waiting, not computing. Measured on this
    # machine: 1.6 percent CPU against a 197 ms round trip to us-west-2, and a
    # windowed read of four assets plus the MTL costs twenty to thirty of those
    # round trips. pipeline.py already found the same thing on the Sentinel-2
    # side and wrote it down: 60.9 s serially at 17 percent CPU against 7.8 s
    # with one thread per band. So the scenes go through a pool, and the only
    # reason the pool is not larger is that the far end is somebody else's
    # bucket.
    rows: list[dict] = []
    done = 0

    def measure(c: dict) -> dict | None:
        try:
            bands, land, sun = read_scene(c["item"], land_source)
            got = classify(bands, land)
        except Exception as exc:  # pragma: no cover - network-driven
            LOGGER.warning("%s: %s", c["day"], type(exc).__name__)
            return None
        return {
            "day": c["day"],
            "season": c["season"],
            "doy": c["doy"],
            "scene": c["item"].id,
            "sun_elevation": sun,
            "scene_cloud": c["cloud"],
            **got,
        }

    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for got in pool.map(measure, chosen):
            done += 1
            if got is not None:
                rows.append(got)
            if done % 50 == 0 or done == len(chosen):
                LOGGER.info("[%d/%d]", done, len(chosen))
    rows.sort(key=lambda r: r["day"])

    frame = pd.DataFrame(rows)
    if frame.empty:
        print("nothing measured")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "landsat_season_series.csv"
    frame.to_csv(path, index=False)
    LOGGER.info("written to %s", path)

    kept = frame[frame.landsat_share >= MIN_CLASSIFIED_SHARE]
    print()
    print(
        f"{len(kept)} of {len(frame)} days clear the {MIN_CLASSIFIED_SHARE} share gate"
    )
    print()
    s2 = sentinel_series(args.archive)
    s2 = s2[(s2.doy >= SEASON_WINDOW[0]) & (s2.doy <= SEASON_WINDOW[1])]
    s2["season"] = s2.day.str[:4].astype(int)

    landsat = binned_means(kept, "doy", "landsat_ice", "season")
    sentinel = binned_means(s2[s2.s2_share >= 0.30], "doy", "s2_ice", "season")

    print(
        f"{'season':8s}{'days':>6s}{'bins':>6s}{'Landsat':>10s}{'bins':>6s}{'Sentinel-2':>13s}{'diff':>9s}"
    )
    for season in sorted(landsat):
        a, na = landsat[season]
        n = int((kept.season == season).sum())
        if season in sentinel:
            b, nb = sentinel[season]
            print(f"{season:<8d}{n:6d}{na:6d}{a:10.3f}{nb:6d}{b:13.3f}{a - b:+9.3f}")
        else:
            print(f"{season:<8d}{n:6d}{na:6d}{a:10.3f}{'.':>6s}{'.':>13s}")

    shared = sorted(set(landsat) & set(sentinel))

    # Three ways of asking the same question, printed together because the spread
    # between them IS the result. Only the first is a like-for-like comparison.
    bins_l = per_season_bins(kept, "doy", "landsat_ice", "season")
    bins_s = per_season_bins(s2[s2.s2_share >= 0.30], "doy", "s2_ice", "season")
    common = common_bin_comparison(bins_l, bins_s)
    if common:
        d = np.array([a - b for _, _, a, b in common])
        r = float(
            np.corrcoef([a for *_, a, _ in common], [b for *_, b in common])[0, 1]
        )
        print()
        print(f"{'agreement over':44s}{'n':>4s}{'bias':>9s}{'RMSE':>8s}{'r':>8s}")
        print(
            f"{'bins BOTH sensors filled':44s}{len(common):4d}{d.mean():+9.4f}"
            f"{np.sqrt((d**2).mean()):8.4f}{r:8.3f}"
        )
        if len(shared) >= 3:
            e = np.array([landsat[s][0] - sentinel[s][0] for s in shared])
            print(
                f"{'each sensor over its own filled bins':44s}{len(shared):4d}"
                f"{e.mean():+9.4f}{np.sqrt((e**2).mean()):8.4f}"
                f"{np.corrcoef([landsat[s][0] for s in shared], [sentinel[s][0] for s in shared])[0, 1]:8.3f}"
            )
        raw_l = kept.groupby("season").landsat_ice.mean()
        raw_s = s2[s2.s2_share >= 0.30].groupby("season").s2_ice.mean()
        both_raw = sorted(set(raw_l.index) & set(raw_s.index))
        raw = np.array([raw_l[s] - raw_s[s] for s in both_raw])
        print(
            f"{'the days each sensor happens to have':44s}{len(both_raw):4d}"
            f"{raw.mean():+9.4f}{np.sqrt((raw**2).mean()):8.4f}"
            f"{np.corrcoef([raw_l[s] for s in both_raw], [raw_s[s] for s in both_raw])[0, 1]:8.3f}"
        )
        print()
        print(
            "  Only the first row compares the two instruments. The other two also\n"
            "  compare the parts of the season each of them happened to sample, and\n"
            "  most of the disagreement they report is that, not the sensors."
        )
        print()
        print(
            f"  {'season':8s}{'shared bins':>13s}{'Landsat':>10s}{'Sentinel-2':>13s}{'diff':>9s}"
        )
        for year, n, a, b in common:
            print(f"  {year:<8d}{n:13d}{a:10.3f}{b:13.3f}{a - b:+9.3f}")

    # The question the extension exists to answer. If the three seasons before
    # Sentinel-2 lift the early baseline, the ten-season window began on an
    # unusually icy stretch and the published decline is partly an accident of
    # where the record starts. If they do not, it is not.
    added = [s for s in landsat if s < min(sentinel, default=9999)]
    overlap_early = [s for s in shared if s < LATE_FROM]
    if added and overlap_early:
        short = float(np.mean([landsat[s][0] for s in overlap_early]))
        long_ = float(
            np.mean([landsat[s][0] for s in sorted(landsat) if s < LATE_FROM])
        )
        print()
        print("does reaching further back move the early baseline?")
        print(
            f"  early mean over the {len(overlap_early)} seasons Sentinel-2 also sees: {short:.4f}"
        )
        print(
            f"  early mean once {len(added)} earlier seasons join it:              {long_:.4f}"
        )
        print(
            f"  the shift the extension buys:                            {long_ - short:+.4f}"
        )
        print(
            "  added seasons: " + ", ".join(f"{s} {landsat[s][0]:.3f}" for s in added)
        )

    print()
    print("decline from the early seasons to the late ones, 95 percent bootstrap")
    for name, table, seasons in (
        (f"Landsat 8/9, {len(landsat)} seasons", landsat, sorted(landsat)),
        (f"Landsat, the {len(shared)} shared only", landsat, shared),
        (f"Sentinel-2, {len(sentinel)} seasons", sentinel, sorted(sentinel)),
    ):
        if len(seasons) >= 4:
            low, high = decline_interval(table, seasons)
            print(
                f"  {name:34s}{decline(table, seasons):6.1f} %   {low:6.1f} to {high:5.1f}"
            )

    try:
        from scipy.stats import kendalltau

        print()
        print("Mann-Kendall over the season means")
        for name, table, seasons in (
            (f"Landsat, {len(landsat)} seasons", landsat, sorted(landsat)),
            (f"Landsat, the {len(shared)} shared", landsat, shared),
            (f"Sentinel-2, {len(sentinel)} seasons", sentinel, sorted(sentinel)),
        ):
            tau, p = kendalltau(
                np.array(seasons), np.array([table[s][0] for s in seasons])
            )
            print(f"  {name:28s}tau {tau:+.3f}, p {p:.4f}")
    except ImportError:  # pragma: no cover
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
