#!/usr/bin/env python3
"""A second, independent ice-fraction series from one sensor, 2013 to 2026.

The record is ten seasons and that is the binding limit on everything this
project can conclude. Going further back with Landsat looked blocked, and the
plan behind this repository said so, but its numbers came from the wrong
catalogue. Measured over the USGS archive there is far more data than it claimed:
from 1990 there would be 36 seasons with a median of 25 usable scenes each.

What is genuinely blocked is the calibration, and measuring it made the case
worse rather than better. Same-overpass pairs over this AOI, which is what a
fixed threshold needs in order to survive a sensor change, counted by
`landsat_l1_inventory.py --reach` over the whole archive:

    TM   against ETM+   0
    TM   against OLI    0
    ETM+ against OLI    2

Zero is not a small number of pairs, it is none, and the sensor boundaries fall
exactly where an early-late split would sit. The two that exist do not help
either. 2013-03-30 is a near-perfect pair, same hour, same sun, both under one
percent cloud, and it lands inside Landsat 8's commissioning phase, where this
pipeline reads 0.098 ice over a frozen fjord. 2019-06-06 is midnight sun at 10
degrees on 6 June over ice already breaking up. Steiro et al. (2021) did reach
back to 1985 on this fjord, but by setting thresholds per image from histogram
analysis, which sidesteps calibration by putting an analyst inside every
measurement. That is a study; this is a pipeline.

So this takes the one extension that crosses no boundary at all: **Landsat 8 and
9 alone, 2014 to 2026**, one instrument family throughout. Three seasons before
Sentinel-2 begins, ten that overlap it.

    python3 scripts/landsat_season_series.py --seasons 2013-2026

Two things the overlap buys that a longer record alone would not. The new seasons
extend the series, and the ten shared ones are a standing comparison between two
instruments measuring the same thing on the same days, which is a stronger check
than any single-scene agreement table.

The sun-angle correction of landsat_l1_crosscheck.py applies here unchanged and
for the same reason: Sentinel-2 L1C carries it and Landsat Level 1 does not.

Two things this run has to get right or the comparison is worthless.

**The commissioning phase.** Searching from 2013 returns scenes, and four of them
were nearly cloud free over a fjord that any other year says is frozen solid, yet
they read 5, 10, 15 and 15 percent ice. 22 March 2013 measures green 0.206 and
NIR 0.090 across the whole fjord where fast ice sits between 0.44 and 0.74, so
every cell fails the brightness gate and falls through to water. It is not the
catalogue quality flag, they are all Tier 1. The dates decide it: USGS records
Landsat 8 as launched 11 February 2013 and reaching its operational WRS-2 orbit
on 11 April 2013, with everything before that acquired on the way there. All four
dark scenes are earlier; the first scene after that boundary, 23 April, reads
0.83. So the cut is that published mission date rather than a judgement about
which numbers look wrong. 2013 then drops out on coverage rather than by hand:
what survives the cut and the share gate is three days, on 23 April, 29 May and
12 June, filling three of the nine bins where five are required.

**Uneven sampling.** Landsat contributes 9 to 30 usable days a season and
Sentinel-2 contributes 25 to 68, and they are not spread the same way through the
window. A plain mean over the days each sensor happens to have compares two
different estimators and calls the gap an instrument difference. Season means are
therefore taken as the mean over fifteen-day bins, so a season crowded with April
scenes cannot outvote one weighted towards February. Measured, that is not
cosmetic: it moves the two sensors from 0.040 apart to 0.004.
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

# The day Landsat 8 reached its operational WRS-2 orbit, per USGS. Anything
# earlier was acquired on the way there and is not a measurement of this fjord.
OPERATIONAL_FROM = "2013-04-11"
# Season means are the mean over these bins, not over scenes, so that a season
# rich in April days is not compared against one rich in February days.
BIN_EDGES = np.arange(45, 181, 15)
MIN_BINS = 5  # a season below this is coverage, not a season


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
                    if day < OPERATIONAL_FROM:
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


def binned_means(
    frame: pd.DataFrame, doy: str, value: str, season: str
) -> dict[int, tuple[float, int]]:
    """Season mean as the mean over fifteen-day bins, with the bins it filled."""
    work = frame.dropna(subset=[value]).copy()
    work["bin"] = np.digitize(work[doy], BIN_EDGES) - 1
    per_bin = work.groupby([season, "bin"])[value].mean()
    out: dict[int, tuple[float, int]] = {}
    for year in sorted(work[season].unique()):
        block = per_bin.loc[year]
        if len(block) >= MIN_BINS:
            out[int(year)] = (float(block.mean()), len(block))
    return out


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
    if len(shared) >= 3:
        diff = np.array([landsat[s][0] - sentinel[s][0] for s in shared])
        r = float(
            np.corrcoef(
                [landsat[s][0] for s in shared], [sentinel[s][0] for s in shared]
            )[0, 1]
        )
        raw_l = kept.groupby("season").landsat_ice.mean()
        raw_s = s2[s2.s2_share >= 0.30].groupby("season").s2_ice.mean()
        raw = np.array([raw_l[s] - raw_s[s] for s in shared])
        print()
        print(
            f"over the {len(shared)} shared seasons, day balanced: bias {diff.mean():+.4f}, "
            f"RMSE {np.sqrt((diff**2).mean()):.4f}, correlation r = {r:+.3f}"
        )
        print(
            f"{'':22s}over the days each sensor happens to have: bias {raw.mean():+.4f}, "
            f"RMSE {np.sqrt((raw**2).mean()):.4f}"
        )

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
