#!/usr/bin/env python3
"""Does fast ice have a spectrum, or only a spectrum for the day?

endmember_separability.py established two things and tripped over a third.
Ice and water are separable by 110 to 220 within-class spreads, so separability
is not what limits a sub-pixel treatment. A two-endmember mixture plus a term
for the atmosphere reproduces the contested April surface to 1.3 spreads, so no
third material is needed.

Then the control ran. 2023-03-31 is fast ice by every measure the archive has,
ice = 0.9939 over 156753 cells, twelve days before the contested day and on the
same processing baseline. Unmixed against the 2018 anchor it comes out at 0.559
ice. An error of 0.44 on a day whose answer is certain is larger than the entire
effect the story measures.

The ratio between the two ice spectra is 1.70, and it is nearly flat: 1.57 in
the coastal band, 1.95 in SWIR22, median 1.70 with a spread of 0.10 across all
eleven surface bands. Snow properties do not do that. Grain size, wetness and
contamination all bite far harder in the near infrared than in the blue. A gain
that is the same at 443 nm and at 2202 nm is illumination, and the sun elevation
on those two days was 30.93 and 23.44 degrees.

Two days cannot settle that, so this measures many:

    python3 scripts/ice_endmember_stability.py
    python3 scripts/ice_endmember_stability.py --per-season 3

Every day the archive calls unambiguously frozen (ice at or above the floor,
enough of the fjord classified, February to April so break-up cannot be in
play), sampled across all ten seasons, each run through the pipeline's own
loader, cloud model and classifier. For each, the median spectrum of the cells
it called solid ice.

What the answer decides:

  If the spectra cluster, a fixed endmember library is legitimate and unmixing
  can report a calibrated fraction. The 2018 anchor was simply a bad choice.

  If they spread as widely as those two days suggest, no fixed library can work
  here, and the honest options are a per-scene endmember, an illumination
  correction against the terrain, or dropping the direction.

  If the spread is large but explained by sun elevation, it is correctable, and
  the correction is worth more than the unmixing was.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")

from uummannaq_ice.config_loader import load_run_config  # noqa: E402
from uummannaq_ice.model import load_cloud_model, resolve_device  # noqa: E402
from uummannaq_ice.processing import BANDS  # noqa: E402

LOGGER = logging.getLogger("ice_endmember_stability")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/baseline.yaml"
DEFAULT_ARCHIVE = ROOT / "archive/reprocessed_2026/summary.csv"

# A day qualifies as certainly frozen. February to April keeps break-up out of
# it: the earliest the fjord has ever opened is 30 April 2021.
FROZEN_MONTHS = (2, 3, 4)
MIN_ICE = 0.99
MIN_SHARE = 0.85
MIN_CELLS = 5000
SURFACE_BANDS = [b for b in BANDS if b not in ("nir09", "cirrus")]


def frozen_days(archive: Path, per_season: int) -> list[str]:
    frame = pd.read_csv(archive)
    for col in ("solid_px", "light_px", "water_px", "cloud_px", "land_px", "nodata_px"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
    stamp = pd.to_datetime(frame.timestamp.astype(str).str[:8], format="%Y%m%d")
    frame["day"] = stamp.dt.date
    frame["season"] = stamp.dt.year
    frame["month"] = stamp.dt.month
    classified = frame.solid_px + frame.light_px + frame.water_px
    grid = classified + frame.cloud_px + frame.land_px + frame.nodata_px
    frame["ice"] = (frame.solid_px + frame.light_px).divide(
        classified.where(classified > 0)
    )
    frame["share"] = classified.divide(grid.where(grid > 0))

    ok = frame[
        frame.month.isin(FROZEN_MONTHS)
        & (frame.ice >= MIN_ICE)
        & (frame.share >= MIN_SHARE)
    ]
    picked: list[str] = []
    for season, block in ok.groupby("season"):
        # Most of the fjord classified first, so the spectrum rests on cells the
        # cloud mask was confident about rather than on the edge of a hole.
        best = block.sort_values("share", ascending=False).head(per_season)
        picked.extend(str(d) for d in best.day)
        LOGGER.info(
            "%d: %d qualifying days, taking %d", season, len(block), len(best.day)
        )
    return sorted(picked)


def measure(days: list[str], config_path: Path) -> pd.DataFrame:
    from odc.stac import load as odc_load

    from uummannaq_ice.pipeline import BAND_SELECTION
    from uummannaq_ice.processing import (
        build_rgb_preview,
        classify_tile,
        downsample_cube,
        land_mask_from_raster,
        reflectance_cube,
    )
    from uummannaq_ice.stac import fetch_tiles

    device = resolve_device(None)
    model = load_cloud_model(load_run_config(config_path).checkpoint_path, device)

    rows: list[dict] = []
    for index, day in enumerate(days, start=1):
        config = load_run_config(config_path)
        config.start_date = config.end_date = date.fromisoformat(day)
        try:
            items = fetch_tiles(config)
        except Exception as exc:  # pragma: no cover - network-driven
            LOGGER.warning("%s: search failed, %s", day, exc)
            continue
        if not items:
            LOGGER.warning("%s: no scene", day)
            continue
        item = items[0]
        try:
            dataset = odc_load(
                [item], geopolygon=config.search_aoi, bands=BAND_SELECTION, chunks={}
            ).compute()
        except Exception as exc:  # pragma: no cover - network-driven
            LOGGER.warning("%s: load failed, %s", day, type(exc).__name__)
            continue

        baseline_str = item.properties.get("s2:processing_baseline", "0.0")
        try:
            baseline_major = int(float(baseline_str))
        except (TypeError, ValueError):
            baseline_major = 0
        small = downsample_cube(reflectance_cube(dataset, baseline_major))
        if small.ndim == 4:
            small = small.squeeze(0)
        _, h4, w4 = small.shape
        land = land_mask_from_raster(config.landmask_path, dataset.odc.geobox, w4, h4)
        classification = classify_tile(
            small,
            land,
            config.thresholds,
            model,
            device,
            build_rgb_preview(dataset),
            baseline_str,
        )
        cube = small.numpy()
        selected = classification.masks["ice_solid"]
        count = int(selected.sum())
        if count < MIN_CELLS:
            LOGGER.warning("%s: only %d solid cells, skipped", day, count)
            continue

        row = {
            "day": day,
            "scene": item.id,
            "cells": count,
            "sun_elevation": float(
                item.properties.get("view:sun_elevation", float("nan"))
            ),
            "baseline": str(baseline_str),
            "scene_cloud": float(item.properties.get("eo:cloud_cover", float("nan"))),
        }
        for i, band in enumerate(BANDS):
            row[band] = float(np.median(cube[i][selected]))
        rows.append(row)
        LOGGER.info(
            "[%d/%d] %s  %s  sun %.1f  n = %d  green %.4f",
            index,
            len(days),
            day,
            item.id,
            row["sun_elevation"],
            count,
            row["green"],
        )
    return pd.DataFrame(rows)


def report(frame: pd.DataFrame) -> None:
    print()
    print("Fast ice at top of atmosphere, one row per certainly frozen day")
    print("=" * 84)
    print(
        f"{'day':12s}{'sun':>6s}{'base':>7s}{'cells':>8s}"
        + "".join(f"{b[:7]:>9s}" for b in ("green", "nir", "swir16"))
        + f"{'brightness':>12s}{'of median':>11s}"
    )
    frame = frame.sort_values("sun_elevation").reset_index(drop=True)
    frame["brightness"] = frame[SURFACE_BANDS].mean(axis=1)
    frame["day"] = frame.day.astype(str)
    frame["season"] = frame.day.str[:4].astype(int)
    # Read back from CSV the baseline arrives as a float, and "02.06" is not a
    # number this file should ever round.
    frame["baseline"] = frame.baseline.map(
        lambda v: v if isinstance(v, str) else f"{float(v):05.2f}"
    )
    typical = float(frame.brightness.median())
    for _, r in frame.iterrows():
        ratio = r.brightness / typical
        mark = "  <<" if ratio < 0.85 else ""
        print(
            f"{r.day:12s}{r.sun_elevation:6.1f}{r.baseline:>7s}{int(r.cells):8d}"
            f"{r.green:9.4f}{r.nir:9.4f}{r.swir16:9.4f}{r.brightness:12.4f}"
            f"{ratio:11.2f}{mark}"
        )

    print()
    print("Per season, because the outlier seasons are the ones under suspicion")
    print("-" * 84)
    print(f"{'season':10s}{'days':>6s}{'brightness':>12s}{'of median':>11s}")
    for season, block in frame.groupby("season"):
        mean = float(block.brightness.mean())
        print(f"{season:<10d}{len(block):6d}{mean:12.4f}{mean / typical:11.2f}")

    print()
    print("How much does the endmember move, band by band")
    print("-" * 84)
    print(f"{'band':10s}{'min':>10s}{'median':>10s}{'max':>10s}{'max/min':>10s}")
    for band in SURFACE_BANDS:
        v = frame[band].to_numpy()
        print(
            f"{band:10s}{v.min():10.4f}{np.median(v):10.4f}{v.max():10.4f}"
            f"{v.max() / max(v.min(), 1e-9):10.2f}"
        )

    print()
    print("Is it the sun?")
    print("-" * 84)
    sun = frame.sun_elevation.to_numpy()
    bright = frame.brightness.to_numpy()
    good = np.isfinite(sun) & np.isfinite(bright)
    if good.sum() >= 3:
        r = float(np.corrcoef(sun[good], bright[good])[0, 1])
        slope, intercept = np.polyfit(sun[good], bright[good], 1)
        predicted = slope * sun[good] + intercept
        resid = bright[good] - predicted
        print(f"correlation of brightness with sun elevation   r = {r:+.3f}")
        print(f"slope                                          {slope:+.5f} per degree")
        print(
            f"spread of brightness                           {bright[good].std():.4f}"
        )
        print(f"spread after removing the sun                  {resid.std():.4f}")
        print(
            f"share of the variance the sun explains         {100 * r * r:.0f} percent"
        )
        # Sentinel-2 L1C is already divided by the cosine of the solar zenith
        # angle, so a residual dependence on sun elevation is NOT the nominal
        # normalisation. It is what the normalisation fails to remove: terrain
        # shadow from 1000 m walls, and the anisotropy of snow at low sun.
        print()
        print(
            "L1C reflectance is already divided by the cosine of the solar zenith\n"
            "angle, so any dependence left here is what that division does not\n"
            "reach: shadow from the walls around this fjord, and the anisotropy of\n"
            "snow under a low sun."
        )
    else:
        print("too few days with a sun elevation to fit")

    print()
    print("What a fixed endmember would cost")
    print("-" * 84)
    # The median day is the library an honest implementation would build, not
    # the brightest. Both errors matter: a day read below 1.00 is ice reported
    # as water, a day above is water reported as ice.
    ratio = (frame.brightness / typical).to_numpy()
    inside = float(np.mean(np.abs(ratio - 1.0) <= 0.05))
    print(
        f"median frozen day, the library an implementation would build: {typical:.4f}"
    )
    print(
        f"the {len(frame)} certainly frozen days read {ratio.min():.2f} to "
        f"{ratio.max():.2f} of it, when every one of them is 1.00"
    )
    print(f"within 5 points of the truth: {100 * inside:.0f} percent of them")
    worst = frame.loc[int(np.argmin(ratio))]
    print(
        f"worst: {worst.day} at {ratio.min():.2f}, and the story's own effect "
        f"is a decline of 0.32"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    parser.add_argument("--per-season", type=int, default=2)
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("rasterio").setLevel(logging.ERROR)

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "ice_endmember_stability.csv"
    if args.reuse and path.exists():
        frame = pd.read_csv(path)
        LOGGER.info("reusing %s, %d days", path, len(frame))
    else:
        days = frozen_days(args.archive, args.per_season)
        LOGGER.info("%d certainly frozen days to measure", len(days))
        frame = measure(days, args.config)
        if frame.empty:
            print("nothing measured")
            return 1
        frame.to_csv(path, index=False)
        LOGGER.info("written to %s", path)

    report(frame)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
