#!/usr/bin/env python3
"""Can a sub-pixel treatment work here at all? The cheap test, run first.

Every cross-check in this project has ended at the same wall. A 40 m cell gets
ONE label, so a cell that is half ice and half water falls to whichever side of
the threshold it lands on, and near a hard cut a small radiometric difference
moves a great deal of area. landsat-crosscheck.md names it outright as the
strongest argument for reporting a fraction instead of a class.

Unmixing is the standard answer: solve r = E a for the abundances a, with a
non-negative and summing to one, and report the ice share of the cell. Before
building any of that, one question decides whether it can work:

    Are the pure spectra separable in the bands this instrument has?

If April ice and open water are spectrally close, no unmixing can separate them
and the direction dies here for the price of one script.

    python3 scripts/endmember_separability.py
    python3 scripts/endmember_separability.py --reuse   # skip the downloads

Three anchor days, each run through the pipeline's OWN loader, cloud model and
classifier so the cells are exactly the cells the archive counted:

  2019-07-07  open water, July, the fjord is certainly open
  2018-04-20  fast ice, ice = 0.9993, 157730 solid cells against 103 water
  2023-03-31  fast ice, ice = 0.9939, twelve days before the contested one and
              on the same processing baseline, which is the control that keeps
              the reading below from resting on a radiometric artefact
  2023-04-12  the contested day: optics report 0.52 ice six weeks before that
              season ever broke up, Landsat reads it wetter still, and radar
              puts it within 2 dB of its own winter ice

Three traps this script is built around, each of which produces a confident
wrong answer if ignored:

  The atmosphere. The water anchor is July and the contested day is April, so
  the two carry different air masses and Rayleigh scattering lifts the blue end
  at top of atmosphere. Fitted without a term for it, the residual is shaped
  exactly like a third surface, and the honest reading of that residual would
  have been "melt ponds". Every fit here may spend a free non-negative term
  proportional to lambda^-4, and the difference it makes is reported.

  The sounding bands. B9 sits on a water vapour feature and B10 is the cirrus
  band, placed where the atmosphere is opaque precisely so that neither carries
  surface signal. They belong in a cloud screen, not in a surface mixture. The
  remaining eleven are weighted by their own measured within-class spread.

  The processing baseline. The 2018 anchor is baseline 02.06 and the contested
  day is 05.09, and from 04.00 onward the products carry a radiometric offset
  worth 0.1 in reflectance. If that correction were wrong, a cross-baseline
  comparison would show exactly the kind of brightness step this script is
  trying to interpret. The 2023-03-31 anchor removes the question: it is the
  same baseline as the contested day and its answer is not in doubt.
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

from scipy.optimize import nnls  # noqa: E402

from uummannaq_ice.config_loader import load_run_config  # noqa: E402
from uummannaq_ice.model import load_cloud_model, resolve_device  # noqa: E402
from uummannaq_ice.processing import BANDS  # noqa: E402

LOGGER = logging.getLogger("endmember_separability")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/baseline.yaml"

# Anchor days, and which class of cells supplies each spectrum. The contested
# day supplies two: the cells the classifier called water, which is the surface
# the whole argument is about, and the cells it called ice, which turn out to
# matter more.
ANCHORS: list[tuple[str, str, str, str]] = [
    ("2019-07-07", "water", "water", "open water, July"),
    ("2018-04-20", "ice", "ice_solid", "fast ice, April 2018"),
    ("2023-03-31", "ice_2023", "ice_solid", "fast ice, 12 days before"),
    ("2023-04-12", "wet", "water", "contested cells, April 2023"),
    ("2023-04-12", "wet_ice", "ice", "ice cells of the same day"),
]

# Sentinel-2A band centres in nanometres, in the order of BANDS.
BAND_NM = {
    "coastal": 442.7,
    "blue": 492.4,
    "green": 559.8,
    "red": 664.6,
    "rededge1": 704.1,
    "rededge2": 740.5,
    "rededge3": 782.8,
    "nir": 832.8,
    "nir08": 864.7,
    "nir09": 945.1,
    "cirrus": 1373.5,
    "swir16": 1613.7,
    "swir22": 2202.4,
}

# The two atmospheric sounding bands, excluded from every surface fit.
SOUNDING = ("nir09", "cirrus")

MIN_CELLS = 500


def measure_anchors(config_path: Path) -> pd.DataFrame:
    """Median spectrum and within-class spread for each anchor, via the pipeline."""
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

    scenes: dict[str, tuple[str, np.ndarray, dict]] = {}
    rows: list[dict] = []

    for day, key, cls_key, label in ANCHORS:
        if day not in scenes:
            config = load_run_config(config_path)
            config.start_date = config.end_date = date.fromisoformat(day)
            items = fetch_tiles(config)
            if not items:
                raise SystemExit(f"{day}: no scene in the catalogue")
            item = items[0]
            dataset = odc_load(
                [item], geopolygon=config.search_aoi, bands=BAND_SELECTION, chunks={}
            ).compute()
            baseline_str = item.properties.get("s2:processing_baseline", "0.0")
            try:
                baseline_major = int(float(baseline_str))
            except (TypeError, ValueError):
                baseline_major = 0
            small = downsample_cube(reflectance_cube(dataset, baseline_major))
            if small.ndim == 4:
                small = small.squeeze(0)
            _, h4, w4 = small.shape
            land = land_mask_from_raster(
                config.landmask_path, dataset.odc.geobox, w4, h4
            )
            classification = classify_tile(
                small,
                land,
                config.thresholds,
                model,
                device,
                build_rgb_preview(dataset),
                baseline_str,
            )
            scenes[day] = (item.id, small.numpy(), classification.masks)

        scene_id, cube, masks = scenes[day]
        if cls_key == "ice":
            selected = masks["ice_solid"] | masks["ice_light"]
        else:
            selected = masks[cls_key]
        count = int(selected.sum())
        if count < MIN_CELLS:
            raise SystemExit(f"{day}/{key}: only {count} cells, too few to anchor on")

        values = np.stack([cube[b][selected] for b in range(len(BANDS))])
        median = np.median(values, axis=1)
        # Robust spread, so "the same" has a scale that outliers cannot inflate.
        spread = 1.4826 * np.median(np.abs(values - median[:, None]), axis=1)
        for i, band in enumerate(BANDS):
            rows.append(
                {
                    "member": key,
                    "day": day,
                    "scene": scene_id,
                    "label": label,
                    "cells": count,
                    "band": band,
                    "reflectance": float(median[i]),
                    "spread": float(spread[i]),
                }
            )
        LOGGER.info("%-28s %s  %-26s n = %7d", label, day, scene_id, count)

    return pd.DataFrame(rows)


def as_vectors(frame: pd.DataFrame) -> tuple[dict, dict, dict]:
    spectra, spread, meta = {}, {}, {}
    for member, block in frame.groupby("member"):
        block = block.set_index("band").loc[BANDS]
        spectra[member] = block.reflectance.to_numpy()
        spread[member] = block.spread.to_numpy()
        meta[member] = (
            str(block.label.iloc[0]),
            str(block.day.iloc[0]),
            int(block.cells.iloc[0]),
        )
    return spectra, spread, meta


class Mixer:
    """Constrained least squares on the surface bands, weighted by their noise.

    The sum-to-one constraint enters as a heavily weighted extra equation, which
    is the standard way to hold it inside a non-negative solver. The atmospheric
    term sits outside that constraint because it is not a surface.
    """

    def __init__(self, sigma: np.ndarray, mu: float = 1e4) -> None:
        self.keep = np.array([i for i, b in enumerate(BANDS) if b not in SOUNDING])
        self.names = [BANDS[i] for i in self.keep]
        self.sigma = sigma[self.keep]
        self.weight = 1.0 / self.sigma
        lam = np.array([BAND_NM[b] for b in self.names])
        rayleigh = (lam / 550.0) ** -4.0
        self.rayleigh = rayleigh / rayleigh.max()
        self.mu = mu

    def fit(self, target: np.ndarray, members: list[np.ndarray], atmosphere: bool):
        r = target[self.keep]
        basis = np.stack([m[self.keep] for m in members], axis=1)
        if atmosphere:
            basis = np.concatenate([basis, self.rayleigh[:, None]], axis=1)
        row = np.zeros((1, basis.shape[1]))
        row[0, : len(members)] = self.mu
        design = np.concatenate([basis * self.weight[:, None], row])
        observed = np.concatenate([r * self.weight, [self.mu]])
        x, _ = nnls(design, observed)
        model = basis @ x
        residual = (r - model) / self.sigma
        share = float(x[0] / max(x[:2].sum(), 1e-9))
        return {
            "share": share,
            "atmosphere": float(x[-1]) if atmosphere else 0.0,
            "rms": float(np.sqrt(np.mean(residual**2))),
            "observed": r,
            "model": model,
            "residual": residual,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    parser.add_argument(
        "--reuse", action="store_true", help="read the spectra instead of downloading"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("rasterio").setLevel(logging.ERROR)

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "endmember_spectra.csv"
    if args.reuse and path.exists():
        frame = pd.read_csv(path)
        LOGGER.info("reusing %s", path)
    else:
        frame = measure_anchors(args.config)
        frame.to_csv(path, index=False)
        LOGGER.info("written to %s", path)

    spectra, spread, meta = as_vectors(frame)
    water, ice, wet, wet_ice, ice_2023 = (
        spectra["water"],
        spectra["ice"],
        spectra["wet"],
        spectra["wet_ice"],
        spectra["ice_2023"],
    )
    sigma = np.sqrt(spread["water"] ** 2 + spread["ice"] ** 2) / 2
    mixer = Mixer(sigma)

    print()
    print("The spectra, in top of atmosphere reflectance")
    print("=" * 78)
    order = ["water", "ice", "ice_2023", "wet_ice", "wet"]
    print(f"{'band':10s}" + "".join(f"{k:>11s}" for k in order) + f"{'spread':>11s}")
    for i, band in enumerate(BANDS):
        marker = "  (sounding)" if band in SOUNDING else ""
        print(
            f"{band:10s}"
            + "".join(f"{spectra[k][i]:11.4f}" for k in order)
            + f"{sigma[i]:11.4f}{marker}"
        )
    print()
    for key in order:
        label, day, cells = meta[key]
        print(f"  {key:8s} {label:28s} {day}   {cells:7d} cells")

    print()
    print("1. Separability of the two poles, per band, in their own spread")
    print("=" * 78)
    print(f"{'band':10s}{'ice - water':>14s}{'in spreads':>13s}")
    for i, band in enumerate(BANDS):
        if band in SOUNDING:
            continue
        gap = ice[i] - water[i]
        print(f"{band:10s}{gap:+14.4f}{gap / sigma[i]:13.0f}")

    print()
    print("2. The contested surface, explained as a mixture")
    print("=" * 78)
    cases = [
        ("ice 2018 + water July", [ice, water], False),
        ("ice 2018 + water July + atmosphere", [ice, water], True),
        ("ice 12 days before + water July", [ice_2023, water], False),
        ("ice 12 days before + water July + atmosphere", [ice_2023, water], True),
        ("ice same day + water July", [wet_ice, water], False),
        ("ice same day + water July + atmosphere", [wet_ice, water], True),
    ]
    print(f"{'model':46s}{'ice share':>10s}{'atmos':>8s}{'residual':>12s}")
    best = None
    for name, members, atmosphere in cases:
        got = mixer.fit(wet, members, atmosphere)
        print(
            f"{name:46s}{got['share']:10.3f}{got['atmosphere']:8.4f}"
            f"{got['rms']:10.1f} sp"
        )
        best = got if best is None or got["rms"] < best["rms"] else best

    print()
    print("   controls, on surfaces whose answer is not in question")
    for label, target in (
        ("open water July", water),
        ("fast ice April 2018", ice),
        ("fast ice 2023-03-31, same baseline", ice_2023),
        ("ice cells of the contested day", wet_ice),
    ):
        got = mixer.fit(target, [ice, water], True)
        print(
            f"   {label:43s}{got['share']:10.3f}{got['atmosphere']:8.4f}"
            f"{got['rms']:10.1f} sp"
        )

    print()
    print("3. Residual of the best model, in multiples of the band's own spread")
    print("=" * 78)
    assert best is not None
    print(
        f"{'band':10s}{'observed':>11s}{'model':>11s}{'residual':>11s}{'spreads':>10s}"
    )
    for i, band in enumerate(mixer.names):
        print(
            f"{band:10s}{best['observed'][i]:11.4f}{best['model'][i]:11.4f}"
            f"{best['observed'][i] - best['model'][i]:+11.4f}"
            f"{best['residual'][i]:10.1f}"
        )

    print()
    print("4. What the classifier reads, for the same four surfaces")
    print("=" * 78)
    gi, ni, si = BANDS.index("green"), BANDS.index("nir"), BANDS.index("swir16")
    config = load_run_config(args.config)
    thresholds = config.thresholds
    print(
        f"{'surface':30s}{'NDSI':>7s}{'NDWI':>7s}{'green':>8s}{'NIR':>8s}  brightness gate"
    )
    for key in order:
        s = spectra[key]
        green, nir, swir = max(s[gi], 0.0), max(s[ni], 0.0), max(s[si], 0.0)
        ndsi = (green - swir) / (green + swir + 1e-6)
        ndwi = (green - nir) / (green + nir + 1e-6)
        passes = s[gi] > thresholds.vis_bright_min and s[ni] > thresholds.nir_bright_min
        print(
            f"{meta[key][0]:30s}{ndsi:7.3f}{ndwi:7.3f}{s[gi]:8.3f}{s[ni]:8.3f}"
            f"  {'passes' if passes else 'FAILS'}"
        )
    print()
    print(
        f"   thresholds in play: ndwi {thresholds.ndwi}, "
        f"green > {thresholds.vis_bright_min}, nir > {thresholds.nir_bright_min}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
