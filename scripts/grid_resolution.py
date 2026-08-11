#!/usr/bin/env python3
"""What does the 40 m analysis grid cost, and what else hides behind that number?

The pipeline loads every band onto a 10 m grid and then average-pools 4 by 4
onto a 40 m analysis grid. Nothing in the documentation says why 40, and it is
not one of the sensor's native resolutions: green is 10 m, SWIR1 is 20 m, the
atmospheric bands are 60 m. Three separate questions hide behind that number and
they can all be answered from one load.

    python3 scripts/grid_resolution.py
    python3 scripts/grid_resolution.py --per-season 3 --reuse

**One: does the answer move with the grid?** The same scene classified at 20, 40
and 80 m. The cloud mask is held fixed for this comparison, computed once and
resampled, so only the grid the indices and gates are evaluated on changes.

**Two: how much does the resolution the cloud model runs at matter?**
compute_cloud_mask receives the POOLED cube, so UNetMobV2 sees a cloud at a
sixteenth of the pixel count it was trained on and every edge gradient four times
steeper. The test is cheap because the 10 m cube is already in memory: run the
mask before pooling, pool the result, and hold it against the mask computed
after pooling.

This question is posed as a magnitude, not as a defect, and the wording matters.
It is tempting to write it as "the model is being run wrong", and the first
version of this file did. Looking at the masks refuses that reading: over bright
April ice the native-resolution mask flags large areas of a visibly cloudless
fjord, including the island, while on hazy February scenes it catches veil the
pooled mask misses. Which setting is closer to the truth appears to depend on
the regime, and nothing here can settle it, because settling it needs labels.
What this measures is what the choice is worth.

**Three: what does pooling reflectance before forming the indices do?** NDSI and
NDWI are ratios, so they are not linear in reflectance. Pooling first and then
indexing is not the same operation as indexing first and then pooling, and the
difference lives exactly in the mixed cells at the ice edge that the whole
project keeps running into. This measures it against the finest reference
available: classify at 10 m, then count what share of each 40 m cell's classified
pixels came out as ice.

Two honest limits on that reference, both stated rather than buried.

The 10 m cube is not fully native. SWIR1 arrives at 20 m and the atmospheric
bands at 60 m, and the loader upsamples both. So the 10 m NDSI carries a SWIR
term that was interpolated, and the reference measures discretisation rather
than truth.

And the cloud mask ends with a 3 by 3 binary closing, which is 30 m on the 10 m
grid and 120 m on the 40 m grid. The morphological scale therefore travels with
the grid. Question one holds the mask fixed so this cannot contaminate it;
question two is comparing the masks, so the closing is part of what is compared
and is named here rather than corrected away.
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

import torch  # noqa: E402
import torch.nn.functional as fn  # noqa: E402

from uummannaq_ice.config_loader import load_run_config  # noqa: E402
from uummannaq_ice.model import load_cloud_model, resolve_device  # noqa: E402

LOGGER = logging.getLogger("grid_resolution")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/baseline.yaml"
DEFAULT_ARCHIVE = ROOT / "archive/reprocessed_2026/summary.csv"

# Pool factors from the 10 m grid. 4 is what the pipeline ships.
POOLS = (1, 2, 4, 8)
PUBLISHED_POOL = 4
METRES = {1: 10, 2: 20, 4: 40, 8: 80}

SEASON_WINDOW = (53, 180)
MIN_CLASSIFIED_SHARE = 0.30


def sample_days(archive: Path, per_season: int) -> list[str]:
    """The same doy-spread sample gate_sensitivity.py uses, for the same reason.

    The transition is the only place a grid change can matter, and sorting by
    coverage buries it in deep winter.
    """
    frame = pd.read_csv(archive)
    for col in ("solid_px", "light_px", "water_px", "cloud_px", "land_px", "nodata_px"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
    stamp = pd.to_datetime(frame.timestamp.astype(str), format="%Y%m%dT%H%M%S")
    frame["day"] = stamp.dt.date
    frame["season"] = stamp.dt.year
    frame["doy"] = stamp.dt.dayofyear
    classified = frame.solid_px + frame.light_px + frame.water_px
    grid = classified + frame.cloud_px + frame.land_px + frame.nodata_px
    frame["share"] = classified.divide(grid.where(grid > 0))

    lo, hi = SEASON_WINDOW
    ok = frame[
        (frame.doy >= lo) & (frame.doy <= hi) & (frame.share >= MIN_CLASSIFIED_SHARE)
    ]
    picked: list[str] = []
    for _, block in ok.groupby("season"):
        block = block.sort_values("doy")
        targets = np.linspace(lo, hi, per_season)
        rows: list[int] = []
        for target in targets:
            if block.empty:
                break
            candidate = (block.doy - target).abs().idxmin()
            rows.append(candidate)
            block = block.drop(index=candidate)
        picked.extend(str(d) for d in ok.loc[rows].day)
    return sorted(picked)


def classify_at(cube: np.ndarray, land: np.ndarray, cloud: np.ndarray, thresholds):
    """The pipeline's own decision rule, on whatever grid it is handed.

    Written out rather than taken from classify_tile because that function also
    renders two preview images per call, and this script calls it up to five
    times per scene. gate_sensitivity.py checks the same transcription against
    the archive to six decimals.
    """
    from uummannaq_ice.processing import (
        GREEN_IDX,
        INDEX_DENOMINATOR_FLOOR,
        NIR_IDX,
        SWIR_IDX,
    )

    green, nir, swir = cube[GREEN_IDX], cube[NIR_IDX], cube[SWIR_IDX]
    green_pos = np.maximum(green, 0.0)
    nir_pos = np.maximum(nir, 0.0)
    swir_pos = np.maximum(swir, 0.0)
    ndsi = (green_pos - swir_pos) / (green_pos + swir_pos + 1e-6)
    ndwi = (green_pos - nir_pos) / (green_pos + nir_pos + 1e-6)
    ndsi_stable = (green_pos + swir_pos) > INDEX_DENOMINATOR_FLOOR
    ndwi_stable = (green_pos + nir_pos) > INDEX_DENOMINATOR_FLOOR
    bright = (green > thresholds.vis_bright_min) & (nir > thresholds.nir_bright_min)
    usable = ~cloud & ~land
    solid = (ndsi > thresholds.ndsi_solid) & ndsi_stable & bright & usable
    light = (
        (ndsi > thresholds.ndsi_light)
        & (ndsi < thresholds.ndsi_solid)
        & ndsi_stable
        & bright
        & usable
    )
    water = (ndwi > thresholds.ndwi) & ndwi_stable & ~light & ~solid & usable
    return solid | light, water


def pool(array: np.ndarray, factor: int, how: str = "mean") -> np.ndarray:
    if factor == 1:
        return array
    tensor = torch.from_numpy(array.astype("float32"))
    if tensor.ndim == 2:
        tensor = tensor[None, None]
        out = fn.avg_pool2d(tensor, factor, factor)[0, 0].numpy()
    else:
        out = fn.avg_pool2d(tensor[None], factor, factor)[0].numpy()
    return out >= 0.5 if how == "majority" else out


def measure(days: list[str], config_path: Path) -> pd.DataFrame:
    from odc.stac import load as odc_load

    from uummannaq_ice.pipeline import BAND_SELECTION
    from uummannaq_ice.processing import (
        compute_cloud_mask,
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
            if not items:
                LOGGER.warning("%s: no scene", day)
                continue
            item = items[0]
            dataset = odc_load(
                [item], geopolygon=config.search_aoi, bands=BAND_SELECTION, chunks={}
            ).compute()
        except Exception as exc:  # pragma: no cover - network-driven
            LOGGER.warning("%s: %s", day, type(exc).__name__)
            continue

        baseline_str = item.properties.get("s2:processing_baseline", "0.0")
        try:
            baseline_major = int(float(baseline_str))
        except (TypeError, ValueError):
            baseline_major = 0
        cube10 = reflectance_cube(dataset, baseline_major)
        geobox = dataset.odc.geobox
        thresholds = config.thresholds

        cubes = {p: pool(cube10, p) for p in POOLS}
        lands = {
            p: land_mask_from_raster(
                config.landmask_path, geobox, cubes[p].shape[2], cubes[p].shape[1]
            )
            for p in POOLS
        }

        # The two cloud masks the second question is about.
        cloud_published = compute_cloud_mask(
            model, torch.from_numpy(cubes[PUBLISHED_POOL]), device
        )
        cloud_native = compute_cloud_mask(model, torch.from_numpy(cube10), device)
        cloud_native_pooled = pool(cloud_native, PUBLISHED_POOL, "majority")
        cloud_native_pooled = cloud_native_pooled[
            : cloud_published.shape[0], : cloud_published.shape[1]
        ]

        row = {
            "day": day,
            "scene": item.id,
            "sun_elevation": float(
                item.properties.get("view:sun_elevation", float("nan"))
            ),
            "cloud_at_40m": float(cloud_published.mean()),
            "cloud_at_10m": float(cloud_native.mean()),
            "cloud_10m_pooled": float(cloud_native_pooled.mean()),
            "cloud_agreement": float((cloud_native_pooled == cloud_published).mean()),
        }

        # Question one: the grid sweep, cloud mask held fixed.
        for p in POOLS:
            shape = cubes[p].shape[1:]
            cloud = pool(cloud_published.astype("float32"), 1)
            cloud = np.array(
                torch.nn.functional.interpolate(
                    torch.from_numpy(cloud_published.astype("float32"))[None, None],
                    size=shape,
                    mode="nearest",
                )[0, 0]
            ).astype(bool)
            ice, water = classify_at(cubes[p], lands[p], cloud, thresholds)
            classified = int(ice.sum() + water.sum())
            row[f"ice_{METRES[p]}m"] = (
                float(ice.sum() / classified) if classified else float("nan")
            )
            row[f"share_{METRES[p]}m"] = classified / int(ice.size)
            if p == 1:
                # Question three: the true subcell fraction, aggregated to 40 m.
                ice10, water10 = ice, water
        # Question two: the published grid with the natively computed mask.
        ice, water = classify_at(
            cubes[PUBLISHED_POOL],
            lands[PUBLISHED_POOL],
            cloud_native_pooled,
            thresholds,
        )
        classified = int(ice.sum() + water.sum())
        row["ice_40m_native_cloud"] = (
            float(ice.sum() / classified) if classified else float("nan")
        )
        row["share_40m_native_cloud"] = classified / int(ice.size)

        # Question three, continued: how many 40 m cells are mixed at 10 m.
        icef = pool(ice10.astype("float32"), PUBLISHED_POOL)
        watf = pool(water10.astype("float32"), PUBLISHED_POOL)
        both = icef + watf
        mixed = (icef > 0) & (watf > 0)
        row["mixed_cells"] = float(mixed[both > 0].mean()) if (both > 0).any() else 0.0

        rows.append(row)
        LOGGER.info(
            "[%d/%d] %s  sun %4.1f  ice 20/40/80 %.3f %.3f %.3f  cloud 40/10 %.3f %.3f",
            index,
            len(days),
            day,
            row["sun_elevation"],
            row["ice_20m"],
            row["ice_40m"],
            row["ice_80m"],
            row["cloud_at_40m"],
            row["cloud_at_10m"],
        )
    return pd.DataFrame(rows)


def report(frame: pd.DataFrame) -> None:
    print()
    print("1. Does the answer move with the grid?")
    print("=" * 78)
    print(
        f"{'grid':>8s}{'mean ice':>11s}{'vs 40 m':>10s}{'worst scene':>14s}"
        f"{'classified share':>19s}"
    )
    base = frame["ice_40m"]
    for p in POOLS:
        col = frame[f"ice_{METRES[p]}m"]
        delta = col - base
        mark = "   published" if p == PUBLISHED_POOL else ""
        print(
            f"{METRES[p]:>6d} m{col.mean():11.4f}{delta.mean():+10.4f}"
            f"{delta.abs().max():14.4f}{frame[f'share_{METRES[p]}m'].mean():19.3f}{mark}"
        )
    print()
    print(
        f"Over {len(frame)} scenes the grid moves the reported ice fraction by\n"
        f"{(frame['ice_20m'] - base).abs().mean():.4f} on average between 20 and 40 m and by "
        f"{(frame['ice_80m'] - base).abs().mean():.4f} between 80 and 40 m."
    )

    print()
    print("2. What is the resolution the cloud mask runs at worth?")
    print("=" * 78)
    print(
        f"cloud share, mask computed on the pooled 40 m cube   "
        f"{frame.cloud_at_40m.mean():.3f}"
    )
    print(
        f"cloud share, mask computed on the native 10 m cube   "
        f"{frame.cloud_at_10m.mean():.3f}"
    )
    print(
        f"the two masks agree on                               "
        f"{frame.cloud_agreement.mean():.3f} of cells"
    )
    print(
        f"worst scene                                          "
        f"{frame.cloud_agreement.min():.3f}"
    )
    shift = frame.ice_40m_native_cloud - frame.ice_40m
    print()
    print(
        f"What that does to the reported ice fraction: mean {shift.mean():+.4f}, "
        f"worst {shift.abs().max():.4f}"
    )
    print()
    print(
        "Which of the two masks is closer to the truth is NOT decided here, and\n"
        "looking at them refuses an easy answer: over bright April ice the native\n"
        "mask flags a visibly cloudless fjord including the island, while on hazy\n"
        "February scenes it catches veil the pooled mask misses. The direction\n"
        "appears to depend on the regime. Settling it needs labels, which is the\n"
        "reference dataset this project does not have."
    )

    print()
    print("3. What does pooling reflectance before the indices cost?")
    print("=" * 78)
    diff = frame.ice_10m - frame.ice_40m
    print(f"{'':34s}{'mean':>10s}{'worst':>10s}")
    print(
        f"{'10 m reference minus published':34s}{diff.mean():+10.4f}{diff.abs().max():10.4f}"
    )
    print(
        f"{'40 m cells that are mixed at 10 m':34s}"
        f"{frame.mixed_cells.mean():10.3f}{frame.mixed_cells.max():10.3f}"
    )
    print()
    print(
        "The 10 m column is a reference, not truth: SWIR1 arrives at 20 m and is\n"
        "upsampled by the loader, so its NDSI term is interpolated. It measures\n"
        "the cost of discretisation, not the error against the real surface."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    parser.add_argument("--per-season", type=int, default=3)
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("rasterio").setLevel(logging.ERROR)

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "grid_resolution.csv"
    if args.reuse and path.exists():
        frame = pd.read_csv(path)
        LOGGER.info("reusing %s, %d scenes", path, len(frame))
    else:
        days = sample_days(args.archive, args.per_season)
        LOGGER.info(
            "%d scenes, each classified at %s m", len(days), list(METRES.values())
        )
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
