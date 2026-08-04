"""Re-derive the classification thresholds on radiometrically corrected reflectance.

WHY THIS EXISTS
---------------
The thresholds shipped before this script (ndsi_solid 0.52, ndsi_light 0.31) were
tuned while every reflectance in the pipeline sat 0.1 too high, because the
baseline 04.00 RADIO_ADD_OFFSET was applied with the wrong sign. Correcting the
sign moves every NDSI value, so the old numbers no longer mean what they meant.
They have to be derived again, on corrected values, by a procedure someone else
can re-run and disagree with.

WHAT NDSI TURNS OUT TO BE WORTH HERE
------------------------------------
The headline result of running this, and it is not what anyone expected: over
this fjord, at top of atmosphere, NDSI carries almost no information about the
surface. On 12 May 2020, the one cached scene that holds bright fast ice, grey
thin ice and open water at the same time under the same sun, sorting every pixel
by near-infrared reflectance and walking up the deciles moves brightness from
0.016 to 0.68 while NDSI stays between 0.92 and 0.95 the whole way. All three
surfaces are nearly black at 1.6 um, so the index is close to green over green.

The old thresholds worked only because the offset bug was doing the work.
Adding 0.1 to both terms of a normalised difference destroys its scale
invariance and turns it into a brightness proxy: biased water came out near 0.07
and biased ice near 0.68, which is why a cut at 0.31 or 0.52 separated anything
at all. Correcting the sign restores NDSI to what it really is here, and that is
why processing.py had to grow a brightness gate, the construction Dozier (1989)
introduced for Landsat snow mapping and the MODIS snow product still uses: snow
and ice are bright in the visible and the near infrared, water is dark in both.

So brightness is the ice/water discriminator. NDSI's remaining job is only to
reject bright surfaces that are not cryosphere at all. It cannot be asked to
separate solid ice from thin ice, and this script says so with numbers rather
than assuming otherwise.

HOW THE LABELS ARE OBTAINED
---------------------------
Hand-labelling pixels is not realistic. The evidence comes instead from scenes
where the scene-level answer is not in doubt, each one confirmed on its cached
RGB preview before the label was written down:

  * a fjord under continuous fast ice, an unbroken cracked white sheet with no
    resolvable lead, so every usable pixel should be classified ice and the
    gated fraction measures recall;
  * an open fjord, dark water with discrete icebergs, so no usable pixel should
    be classified ice and the gated fraction measures the false ice rate.

Neither label is exactly true. The open scenes carry icebergs, which are genuine
ice, so the measured false ice rate is an UPPER bound on the error. The frozen
scenes carry tidal cracks, so the measured recall is a LOWER bound. Both biases
push the same way for every candidate, so the ranking between candidates holds
even though the absolute numbers are bounds.

Assumptions about the calendar were checked and several failed. April is not
reliably fast ice at Uummannaq any more: 30 April 2021 and 21 April 2025 are
broken floes on open water, and 24 April 2020 is a continuous but dark thin-ice
sheet. February is not reliably frozen either: 19 February 2025 is open water
with floes. Every one of those was demoted to an unlabelled diagnostic rather
than asserted, which is why there are only three high-sun ice anchors.

USAGE
-----
    AWS_NO_SIGN_REQUEST=YES python scripts/derive_thresholds.py --cache-dir /tmp/uum-thresholds

The first run downloads the scenes listed in SCENES, one to four minutes each,
and caches the 40 m cube, the cloud mask and an RGB preview per scene. Every later
run reads the cache and costs nothing. Pass --stage cache to download only, or
--stage analyse to re-run the analysis over an existing cache.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# The scene set
# ---------------------------------------------------------------------------
#
# Eighteen acquisition days. The slots were chosen before any scene was looked
# at, on three criteria:
#
#   1. they span the observable season. Uummannaq sits at 70.7 N, so Sentinel-2
#      sees nothing between early November and early February; February to October
#      is the whole record;
#   2. they span the processing baseline boundary of 25 January 2022, with anchors
#      on both sides, so the derivation cannot be an artefact of one encoding;
#   3. within each slot the clearest available scene was taken, by the catalogue's
#      own eo:cloud_cover, because cloud is the main contaminant of a reflectance
#      distribution.
#
# The LABELS were assigned afterwards, from the cached RGB preview, and several
# slots that were expected to be anchors turned out not to be. Those kept their
# place in the set as unlabelled diagnostics rather than being dropped, because a
# scene that contradicts an assumption is worth more than one that confirms it.
#
# 2019-05-30 is listed twice on purpose. The catalogue holds that acquisition in
# both the original 02.07 encoding and the reprocessed 05.00 encoding. Loading
# both and comparing is a direct test of the offset correction: if the correction
# is right the two must agree to rounding, and if it is wrong they must differ by
# 0.1 in every band.

CROSS_BASELINE_DAY = date(2019, 5, 30)


@dataclass(frozen=True)
class Scene:
    """One acquisition day, with whatever scene-level truth can be asserted."""

    day: date
    role: str
    label: str | None
    why: str


SCENES: Tuple[Scene, ...] = (
    # --- frozen anchors ------------------------------------------------------
    # Continuous fast ice from shore to shore, confirmed on the cached RGB
    # preview: an unbroken white sheet, cracked but not separated, no lead wide
    # enough to resolve at 40 m. Every usable pixel should read as ice.
    Scene(date(2019, 4, 28), "frozen", "ice", "April fast ice, baseline 02.07"),
    Scene(date(2022, 4, 2), "frozen", "ice", "April fast ice, baseline 04.00"),
    Scene(date(2024, 3, 25), "frozen", "ice", "late March fast ice, baseline 05.10"),
    # --- low sun frozen ------------------------------------------------------
    # Also continuous fast ice, but at a sun elevation of eight degrees the
    # island throws kilometre-long shadows across it. The surface is ice; a
    # shadowed ice pixel is not something any reflectance floor can recover.
    # Labelled, so the cost of that is measured rather than assumed, and the
    # sweep is reported both with and without it.
    Scene(date(2024, 2, 20), "frozen_lowsun", "ice", "February fast ice in shadow"),
    # --- open anchors --------------------------------------------------------
    # Open fjord, confirmed on the preview: dark water, brown island, scattered
    # small icebergs. The bergs are real ice, so the measured false ice rate on
    # these scenes is an upper bound, not an error rate.
    Scene(date(2020, 8, 30), "open", "water", "August open fjord, baseline 02.09"),
    Scene(date(2021, 8, 22), "open", "water", "August open fjord, baseline 03.01"),
    Scene(date(2023, 8, 9), "open", "water", "August open fjord, baseline 05.09"),
    Scene(date(2024, 8, 6), "open", "water", "August open fjord, baseline 05.11"),
    # --- low sun open --------------------------------------------------------
    # September, sun elevation 19. Rayleigh path radiance lifts water in the
    # visible at long atmospheric path, which is the failure mode the visible
    # floor has to survive.
    Scene(date(2024, 9, 22), "open_lowsun", "water", "September, sun elevation 19"),
    # Mid October, sun elevation 12. Freeze-up in this fjord begins in November
    # at the earliest, and the preview shows open water with discrete icebergs
    # and no continuous ice, so the label is safe and it doubles the low-sun
    # open-water evidence, which is where the visible floor is actually tested.
    Scene(date(2024, 10, 12), "open_lowsun", "water", "October, sun elevation 12"),
    # --- unlabelled diagnostics ---------------------------------------------
    # The answer here is genuinely in doubt, so no label is asserted. These
    # scenes are loaded to check that a chosen threshold set behaves sensibly
    # across them, not to score it.
    # The thin-ice case, and the reason the light class needs a rethink. A
    # continuous cracked ice sheet, but dark: green 0.24, near infrared 0.10,
    # SWIR 0.006. That is a wet or thin ice surface, where a water film absorbs
    # the infrared while the visible still reflects off the ice underneath. It
    # is unambiguously ice, and it is unambiguously not bright, so it cannot be
    # an anchor for a brightness floor. It is kept as the evidence base for what
    # the light class would have to look like.
    Scene(date(2020, 4, 24), "thin_ice", None, "April, wet or thin ice, dark in NIR"),
    # The one scene that holds bright fast ice, grey thin ice and open water side
    # by side under one illumination. It is the whole argument about NDSI in a
    # single frame and it is reported separately below.
    Scene(date(2020, 5, 12), "mixed", None, "mid May, all three surfaces at once"),
    Scene(date(2021, 4, 30), "breakup", None, "April 2021, dark floes not fast ice"),
    Scene(date(2021, 5, 5), "breakup", None, "early May, ice decaying"),
    Scene(date(2022, 6, 20), "breakup", None, "June, mixed ice and water"),
    Scene(date(2025, 4, 21), "breakup", None, "April 2025, broken pack not fast ice"),
    Scene(date(2025, 2, 19), "shoulder", None, "February 2025, fjord not frozen over"),
    # --- the paired-encoding day, also a breakup diagnostic ------------------
    Scene(CROSS_BASELINE_DAY, "breakup", None, "late May, both encodings on file"),
)

BAND_KEYS = ("green", "red", "nir", "swir")

# ---------------------------------------------------------------------------
# Reference points from the literature, used as sanity anchors, not as answers
# ---------------------------------------------------------------------------
#
# Dozier (1989), Remote Sensing of Environment 28:9-22, "Spectral signature of
# alpine snow cover from the Landsat Thematic Mapper", introduced the normalised
# difference snow index and the pairing with a near-infrared brightness test.
#
# Hall, Riggs and Salomonson (1995), Remote Sensing of Environment 54:127-140,
# "Development of methods for mapping global snow cover using MODIS data", fixed
# the operational form still in use: NDSI > 0.4 together with NIR reflectance
# above roughly 0.11 and a visible floor, the latter added because dark water can
# reach a high NDSI on its own.
#
# Riggs, Hall and Roman (2017), Earth System Science Data 9:765-777, document the
# MODIS Collection 6 revision that kept NDSI 0.4 as the snow cut.
#
# These are TOA snow cuts over land. Sea ice is not alpine snow: young and wet ice
# is darker and less spectrally contrasted than dry snow, so the sea-ice cut is
# expected to sit at or below the snow cut, never above it. The measured numbers
# below are checked against that expectation rather than derived from it.
LITERATURE = {
    "dozier_1989_ndsi_snow": 0.40,
    "modis_c6_ndsi_snow": 0.40,
    "modis_nir_brightness_floor": 0.11,
    "modis_green_brightness_floor": 0.10,
}

# What config/baseline.yaml actually ships, mirrored here so the report always
# scores the numbers in production rather than the numbers this script would
# like. tests/test_derive_thresholds.py asserts the two agree.
# What config/baseline.yaml actually ships. Kept in step by
# tests/test_derive_thresholds.py so this script always scores the live rule.
#
# ndsi_solid is 0.70 rather than the 0.83 this derivation produced. Measured
# against a completely frozen fjord (2023-04-20, tile 22WDD, 151,150 bright
# usable cells) NDSI runs 0.687 to 0.755 with a median of 0.720, so 0.83 empties
# the solid class entirely. It does not move the published ice fraction, which
# is solid + light, only what the two class names mean. The disagreement with
# the eighteen-scene derivation is unresolved.
SHIPPED = {
    "vis_min": 0.10,
    "nir_min": 0.17,
    "ndsi_light": 0.40,
    "ndsi_solid": 0.70,
    "ndwi_min": 0.20,
}


# ---------------------------------------------------------------------------
# Pure numerics. No network, no torch, no odc. Unit tested.
# ---------------------------------------------------------------------------


def ndsi_of(green: np.ndarray, swir: np.ndarray) -> np.ndarray:
    """Normalised difference snow index, the same expression processing.py uses."""
    return (green - swir) / (green + swir + 1e-6)


def ndwi_of(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """Normalised difference water index, the same expression processing.py uses."""
    return (green - nir) / (green + nir + 1e-6)


def brightness_gate(
    green: np.ndarray, nir: np.ndarray, vis_min: float, nir_min: float
) -> np.ndarray:
    """The Dozier/MODIS brightness floor: bright in the visible AND in the NIR."""
    return (green > vis_min) & (nir > nir_min)


def otsu_threshold(
    values: np.ndarray,
    bins: int = 512,
    value_range: Tuple[float, float] = (-1.0, 1.0),
) -> Tuple[float, float]:
    """Otsu's cut and its separability.

    Returns (threshold, eta) where eta is the maximised between-class variance
    divided by the total variance, in [0, 1]. Otsu always returns a number; eta
    is what says whether that number means anything. A genuinely bimodal
    distribution gives eta above roughly 0.7. Anything much lower is Otsu
    slicing a single mode in half, and the cut should not be trusted.
    """
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return float("nan"), 0.0
    hist, edges = np.histogram(finite, bins=bins, range=value_range)
    total = hist.sum()
    if total == 0:
        return float("nan"), 0.0
    centres = 0.5 * (edges[:-1] + edges[1:])
    prob = hist.astype(np.float64) / float(total)
    omega = np.cumsum(prob)
    mu = np.cumsum(prob * centres)
    mu_total = mu[-1]
    variance_total = float(np.sum(prob * (centres - mu_total) ** 2))
    denominator = omega * (1.0 - omega)
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mu_total * omega - mu) ** 2 / denominator
    between = np.where(np.isfinite(between), between, -np.inf)
    # Between two well separated modes the criterion is flat: moving the cut
    # across an empty stretch of the histogram changes nothing. A plain argmax
    # would return the left edge of that stretch, which is not the middle of the
    # gap and is not what anyone means by the Otsu cut. Take the centre of the
    # tied run instead.
    best = float(between.max())
    tied = np.flatnonzero(between >= best - 1e-12)
    index = int(tied[tied.size // 2])
    eta = float(best / variance_total) if variance_total > 0 else 0.0
    return float(centres[index]), eta


def histogram_valley(
    values: np.ndarray,
    bins: int = 256,
    value_range: Tuple[float, float] = (-1.0, 1.0),
    smooth: int = 9,
    min_mode_share: float = 0.05,
) -> Tuple[float, int]:
    """Deepest valley between the two largest modes of a smoothed histogram.

    Returns (valley position, number of modes found). This is the second, weaker
    reading of the same question Otsu answers. When Otsu and the valley agree the
    boundary is a real feature of the data; when they disagree the distribution
    is not cleanly bimodal and neither should be quoted as a point value.
    """
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return float("nan"), 0
    hist, edges = np.histogram(finite, bins=bins, range=value_range)
    centres = 0.5 * (edges[:-1] + edges[1:])
    kernel = np.ones(smooth) / float(smooth)
    smoothed = np.convolve(hist.astype(np.float64), kernel, mode="same")
    peak = smoothed.max()
    if peak <= 0:
        return float("nan"), 0
    interior = np.arange(1, len(smoothed) - 1)
    is_peak = (smoothed[interior] > smoothed[interior - 1]) & (
        smoothed[interior] >= smoothed[interior + 1]
    )
    peaks = interior[is_peak & (smoothed[interior] >= min_mode_share * peak)]
    if peaks.size < 2:
        return float("nan"), int(peaks.size)
    order = peaks[np.argsort(smoothed[peaks])[::-1]][:2]
    left, right = int(min(order)), int(max(order))
    span = smoothed[left : right + 1]
    # Same tie problem as in otsu_threshold: a wide empty gap gives a long run of
    # equal minima and argmin would return its left edge.
    tied = np.flatnonzero(span <= span.min() + 1e-12)
    valley = left + int(tied[tied.size // 2])
    return float(centres[valley]), int(peaks.size)


def sweep_brightness_floors(
    ice_green: np.ndarray,
    ice_nir: np.ndarray,
    water_green: np.ndarray,
    water_nir: np.ndarray,
    vis_grid: Sequence[float],
    nir_grid: Sequence[float],
) -> Dict[str, np.ndarray]:
    """Recall and false-ice rate of the brightness gate over a 2-D floor grid.

    ice_* are pixels from scenes labelled ice, water_* from scenes labelled water,
    both already restricted to usable pixels. Returns arrays indexed
    [vis index, nir index].
    """
    recall = np.zeros((len(vis_grid), len(nir_grid)))
    false_ice = np.zeros_like(recall)
    for i, vis in enumerate(vis_grid):
        for j, nir_floor in enumerate(nir_grid):
            recall[i, j] = float(
                brightness_gate(ice_green, ice_nir, vis, nir_floor).mean()
            )
            false_ice[i, j] = float(
                brightness_gate(water_green, water_nir, vis, nir_floor).mean()
            )
    return {
        "recall": recall,
        "false_ice": false_ice,
        "balanced_accuracy": 0.5 * (recall + (1.0 - false_ice)),
    }


def plateau_interval(
    scores: np.ndarray, grid: Sequence[float], tolerance: float
) -> Tuple[float, float]:
    """Range of grid values whose score is within `tolerance` of the best.

    Used instead of quoting the arg-max alone. If a whole stretch of the grid
    scores the same to within a thousandth, the arg-max is noise and the honest
    answer is the stretch.
    """
    best = float(np.nanmax(scores))
    good = np.asarray(grid, dtype=float)[np.asarray(scores) >= best - tolerance]
    if good.size == 0:
        return float("nan"), float("nan")
    return float(good.min()), float(good.max())


def classify(
    green: np.ndarray,
    nir: np.ndarray,
    swir: np.ndarray,
    usable: np.ndarray,
    vis_min: float,
    nir_min: float,
    ndsi_light: float,
    ndsi_solid: float,
    ndwi_min: float,
) -> Dict[str, np.ndarray]:
    """Reproduce the class assignment of processing.classify_tile.

    Kept deliberately as a separate small copy rather than importing the tile
    classifier, because the tile classifier also wants a cloud model, a land mask
    template and an RGB preview. The two must agree; tests assert that they do.
    """
    ndsi = ndsi_of(green, swir)
    ndwi = ndwi_of(green, nir)
    bright = brightness_gate(green, nir, vis_min, nir_min)
    solid = (ndsi > ndsi_solid) & bright & usable
    light = (ndsi > ndsi_light) & (ndsi < ndsi_solid) & bright & usable
    water = (ndwi > ndwi_min) & ~light & ~solid & usable
    return {
        "ice_solid": solid,
        "ice_light": light,
        "ice_any": solid | light,
        "water": water,
        "unclassified": usable & ~solid & ~light & ~water,
    }


def score_candidate(
    scenes: Sequence[Dict[str, Any]],
    vis_min: float,
    nir_min: float,
    ndsi_light: float,
    ndsi_solid: float,
    ndwi_min: float,
    mask_key: str = "usable",
) -> Dict[str, float]:
    """Confusion of one threshold set over the labelled scenes, pixel weighted."""
    ice_hit = ice_total = water_hit = water_total = 0
    unclassified = 0
    for scene in scenes:
        if scene["label"] is None:
            continue
        usable = scene.get(mask_key, scene["usable"])
        masks = classify(
            scene["green"],
            scene["nir"],
            scene["swir"],
            usable,
            vis_min,
            nir_min,
            ndsi_light,
            ndsi_solid,
            ndwi_min,
        )
        usable_n = int(usable.sum())
        if usable_n == 0:
            continue
        unclassified += int(masks["unclassified"].sum())
        if scene["label"] == "ice":
            ice_hit += int(masks["ice_any"].sum())
            ice_total += usable_n
        else:
            water_hit += int(masks["water"].sum())
            water_total += usable_n
    recall = ice_hit / ice_total if ice_total else float("nan")
    water_recall = water_hit / water_total if water_total else float("nan")
    return {
        "ice_recall_lower_bound": recall,
        "water_recall": water_recall,
        "balanced_accuracy": 0.5 * (recall + water_recall),
        "unclassified_px": unclassified,
    }


# ---------------------------------------------------------------------------
# Caching. Network and torch live here and nowhere else.
# ---------------------------------------------------------------------------


def cache_path(cache_dir: Path, day: date, suffix: str = "") -> Path:
    return cache_dir / f"{day.isoformat()}{suffix}.npz"


def build_cache(cache_dir: Path, force: bool = False) -> None:
    """Download each scene once and store the 40 m cube plus masks."""
    os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Imported here so the analysis half of this module, and its tests, need
    # neither the network stack nor torch.
    from odc.stac import load as odc_load
    from pystac_client import Client

    from uummannaq_ice.config import build_config
    from uummannaq_ice.model import load_cloud_model, resolve_device
    from uummannaq_ice.processing import (
        BANDS,
        build_rgb_preview,
        compute_cloud_mask,
        downsample_cube,
        make_land_mask,
        reflectance_cube,
        refresh_landmask,
        void_reflectance,
    )
    from uummannaq_ice.stac import fetch_tiles

    device = resolve_device(None)
    config = build_config(output_dir=cache_dir / "_scratch")
    model = load_cloud_model(config.checkpoint_path, device)
    landmask_template = refresh_landmask(config.landmask_path)

    band_index = {name: BANDS.index(name) for name in ("green", "red", "nir", "swir16")}

    def store(item: Any, path: Path) -> None:
        baseline = str(item.properties.get("s2:processing_baseline", "0.0"))
        try:
            baseline_major = int(float(baseline))
        except ValueError:
            baseline_major = 0
        dataset = odc_load([item], geopolygon=config.search_aoi, chunks={})
        cube = reflectance_cube(dataset, baseline_major)
        small = downsample_cube(cube)
        if small.ndim == 4:
            small = small.squeeze(0)
        array = small.numpy()
        _, height, width = array.shape
        void = void_reflectance(baseline_major)
        nodata = np.all(np.abs(array - void) < 1e-4, axis=0)
        cloud = compute_cloud_mask(model, small, device)
        land = make_land_mask(landmask_template, width, height)
        build_rgb_preview(dataset).save(path.with_suffix(".png"))
        np.savez_compressed(
            path,
            green=array[band_index["green"]],
            red=array[band_index["red"]],
            nir=array[band_index["nir"]],
            swir=array[band_index["swir16"]],
            cloud=cloud,
            land=land,
            nodata=nodata,
            meta=np.array(
                json.dumps(
                    {
                        "item_id": item.id,
                        "baseline": baseline,
                        "sun_elevation": item.properties.get("view:sun_elevation"),
                        "eo_cloud_cover": item.properties.get("eo:cloud_cover"),
                        "datetime": item.datetime.isoformat() if item.datetime else "",
                    }
                )
            ),
        )
        logging.info("cached %s -> %s", item.id, path.name)

    for scene in SCENES:
        path = cache_path(cache_dir, scene.day)
        if path.exists() and not force:
            logging.info("cache hit %s", path.name)
            continue
        day_config = build_config(
            start_date=scene.day,
            end_date=scene.day,
            output_dir=cache_dir / "_scratch",
        )
        items = fetch_tiles(day_config)
        if not items:
            logging.warning("no item for %s", scene.day)
            continue
        store(items[0], path)

    # The paired encoding of the same acquisition, fetched by explicit id so the
    # pipeline's one-scene-per-day rule cannot hide the second one.
    pair_path = cache_path(cache_dir, CROSS_BASELINE_DAY, "_alt")
    primary_path = cache_path(cache_dir, CROSS_BASELINE_DAY)
    if (not pair_path.exists() or force) and primary_path.exists():
        client = Client.open(config.stac_url)
        search = client.search(
            collections=[config.collection],
            intersects=dict(config.search_aoi),
            datetime=(
                f"{CROSS_BASELINE_DAY.isoformat()}T00:00:00Z/"
                f"{CROSS_BASELINE_DAY.isoformat()}T23:59:59Z"
            ),
        )
        with np.load(primary_path) as data:
            primary = json.loads(str(data["meta"]))
        chosen = primary["item_id"]
        stem = chosen.rsplit("_", 2)[0]
        alternatives = [
            item
            for item in search.items()
            if item.id != chosen
            and item.id.rsplit("_", 2)[0] == stem
            and str(item.properties.get("s2:processing_baseline", ""))
            != primary["baseline"]
        ]
        if alternatives:
            store(alternatives[0], pair_path)
        else:
            logging.warning("no alternative encoding found for %s", CROSS_BASELINE_DAY)


def load_cache(cache_dir: Path) -> List[Dict[str, Any]]:
    """Read the cached scenes back, attaching labels and the usable mask."""
    loaded: List[Dict[str, Any]] = []
    for scene in SCENES:
        path = cache_path(cache_dir, scene.day)
        if not path.exists():
            logging.warning("missing cache entry %s", path.name)
            continue
        with np.load(path) as data:
            record: Dict[str, Any] = {key: data[key] for key in BAND_KEYS}
            cloud = data["cloud"].astype(bool)
            land = data["land"].astype(bool)
            nodata = data["nodata"].astype(bool)
            record["meta"] = json.loads(str(data["meta"]))
        record["cloud"] = cloud
        record["land"] = land
        record["nodata"] = nodata
        record["usable"] = ~cloud & ~land & ~nodata
        record["day"] = scene.day.isoformat()
        record["role"] = scene.role
        record["label"] = scene.label
        record["why"] = scene.why
        loaded.append(record)
    return loaded


def pooled(
    scenes: Sequence[Dict[str, Any]],
    label: str,
    key: str,
    mask_key: str = "usable",
    exclude_roles: Sequence[str] = (),
) -> np.ndarray:
    """All usable pixels of one band across every scene carrying `label`."""
    chunks = [
        s[key][s[mask_key]]
        for s in scenes
        if s["label"] == label and s["role"] not in exclude_roles
    ]
    if not chunks:
        return np.empty(0, dtype=np.float32)
    return np.concatenate(chunks)


# At 1.6 um bare rock and dry tundra sit above 0.10, open water is under 0.01,
# sea ice runs 0.02 to 0.06 and snow lower still, so a single SWIR cut separates
# rock from everything else this fjord contains in August.
ROCK_SWIR_MIN = 0.10


def summer_rock_mask(scenes: Sequence[Dict[str, Any]]) -> np.ndarray:
    """Bare rock, found from the SWIR on the open-water anchors.

    The shipped land mask is one PNG stretched onto whatever grid a scene
    happens to have, and over this AOI it does not register exactly: the island
    sits a few pixels off and the eastern peninsula is not covered at all. That
    is a pipeline matter rather than a threshold matter, but it contaminates the
    evidence used here, because unmasked sunlit rock in August is bright in the
    visible and the near infrared and would be charged to the brightness gate as
    a false ice detection when it is really a land-mask miss.

    Taking any pixel that exceeds the cut on ANY open-water anchor is
    deliberately over-inclusive: it removes more than it strictly must, and what
    it removes is not sea. Numbers are reported both ways so the difference
    between the two is visible rather than assumed away.
    """
    rock: np.ndarray | None = None
    for scene in scenes:
        if scene["label"] != "water":
            continue
        bright_swir = scene["swir"] > ROCK_SWIR_MIN
        if rock is None:
            rock = bright_swir
        elif rock.shape == bright_swir.shape:
            rock = rock | bright_swir
        else:
            logging.warning(
                "grid mismatch on %s, not merged into rock mask", scene["day"]
            )
    if rock is None:
        return np.zeros(0, dtype=bool)
    return rock


# ---------------------------------------------------------------------------
# The analysis
# ---------------------------------------------------------------------------

VIS_GRID = [round(0.02 + 0.01 * k, 2) for k in range(29)]
NIR_GRID = [round(0.02 + 0.01 * k, 2) for k in range(39)]


def cross_baseline_check(cache_dir: Path) -> Dict[str, Any]:
    """Do the two encodings of one acquisition agree after the correction?"""
    primary = cache_path(cache_dir, CROSS_BASELINE_DAY)
    alternate = cache_path(cache_dir, CROSS_BASELINE_DAY, "_alt")
    if not (primary.exists() and alternate.exists()):
        return {"available": False}
    with np.load(primary) as a, np.load(alternate) as b:
        meta_a = json.loads(str(a["meta"]))
        meta_b = json.loads(str(b["meta"]))
        result: Dict[str, Any] = {
            "available": True,
            "item_a": meta_a["item_id"],
            "baseline_a": meta_a["baseline"],
            "item_b": meta_b["item_id"],
            "baseline_b": meta_b["baseline"],
            "bands": {},
        }
        for key in BAND_KEYS:
            left, right = a[key], b[key]
            if left.shape != right.shape:
                result["bands"][key] = {"shape_mismatch": [left.shape, right.shape]}
                continue
            diff = np.abs(left - right)
            result["bands"][key] = {
                "median_abs_diff": float(np.median(diff)),
                "p99_abs_diff": float(np.percentile(diff, 99)),
                "max_abs_diff": float(diff.max()),
            }
    return result


def prepare(cache_dir: Path) -> Tuple[List[Dict[str, Any]], np.ndarray]:
    """Load the cache and attach the stricter, rock-free usable mask."""
    scenes = load_cache(cache_dir)
    if not scenes:
        raise SystemExit("cache is empty, run with --stage cache first")
    rock = summer_rock_mask(scenes)
    for scene in scenes:
        if rock.size and rock.shape == scene["usable"].shape:
            scene["usable_core"] = scene["usable"] & ~rock
        else:
            scene["usable_core"] = scene["usable"]
    return scenes, rock


def analyse(cache_dir: Path) -> Dict[str, Any]:
    scenes, rock = prepare(cache_dir)

    report: Dict[str, Any] = {
        "scenes": [
            {
                "day": s["day"],
                "role": s["role"],
                "label": s["label"],
                "why": s["why"],
                "item_id": s["meta"]["item_id"],
                "baseline": s["meta"]["baseline"],
                "sun_elevation": s["meta"]["sun_elevation"],
                "eo_cloud_cover": s["meta"]["eo_cloud_cover"],
                "shape": list(s["green"].shape),
                "usable_fraction": round(float(s["usable"].mean()), 4),
                "cloud_fraction": round(float(s["cloud"].mean()), 4),
                "land_fraction": round(float(s["land"].mean()), 4),
            }
            for s in scenes
        ],
        "literature": LITERATURE,
        "cross_baseline": cross_baseline_check(cache_dir),
    }

    # --- 1. the brightness floors -----------------------------------------
    #
    # Run twice: once over everything the shipped land mask leaves, and once
    # with sunlit rock additionally removed. The gap between the two is the part
    # of the apparent error that belongs to the land mask rather than to the
    # thresholds, and it should not be paid for by tightening the gate.
    def run_sweep(mask_key: str, exclude_roles: Sequence[str] = ()) -> Dict[str, Any]:
        ice_green = pooled(scenes, "ice", "green", mask_key, exclude_roles)
        ice_nir = pooled(scenes, "ice", "nir", mask_key, exclude_roles)
        water_green = pooled(scenes, "water", "green", mask_key, exclude_roles)
        water_nir = pooled(scenes, "water", "nir", mask_key, exclude_roles)
        sweep = sweep_brightness_floors(
            ice_green, ice_nir, water_green, water_nir, VIS_GRID, NIR_GRID
        )
        accuracy = sweep["balanced_accuracy"]
        best = np.unravel_index(int(np.argmax(accuracy)), accuracy.shape)
        good = accuracy >= accuracy.max() - 0.001
        return {
            "ice_px": int(ice_green.size),
            "water_px": int(water_green.size),
            "best_vis": VIS_GRID[best[0]],
            "best_nir": NIR_GRID[best[1]],
            "best_balanced_accuracy": round(float(accuracy.max()), 5),
            "recall_at_best": round(float(sweep["recall"][best]), 5),
            "false_ice_at_best": round(float(sweep["false_ice"][best]), 5),
            "plateau_vis": [
                float(np.asarray(VIS_GRID)[good.any(axis=1)].min()),
                float(np.asarray(VIS_GRID)[good.any(axis=1)].max()),
            ],
            "plateau_nir": [
                float(np.asarray(NIR_GRID)[good.any(axis=0)].min()),
                float(np.asarray(NIR_GRID)[good.any(axis=0)].max()),
            ],
            "at_shipped_0.08_0.17": {
                "recall": round(
                    float(sweep["recall"][VIS_GRID.index(0.08), NIR_GRID.index(0.17)]),
                    5,
                ),
                "false_ice": round(
                    float(
                        sweep["false_ice"][VIS_GRID.index(0.08), NIR_GRID.index(0.17)]
                    ),
                    5,
                ),
            },
            "at_modis_0.10_0.11": {
                "recall": round(
                    float(sweep["recall"][VIS_GRID.index(0.10), NIR_GRID.index(0.11)]),
                    5,
                ),
                "false_ice": round(
                    float(
                        sweep["false_ice"][VIS_GRID.index(0.10), NIR_GRID.index(0.11)]
                    ),
                    5,
                ),
            },
            "false_ice_by_nir_at_vis_0.10": {
                str(NIR_GRID[j]): round(
                    float(sweep["false_ice"][VIS_GRID.index(0.10), j]), 5
                )
                for j in range(0, len(NIR_GRID), 2)
            },
            "recall_by_nir_at_vis_0.10": {
                str(NIR_GRID[j]): round(
                    float(sweep["recall"][VIS_GRID.index(0.10), j]), 5
                )
                for j in range(0, len(NIR_GRID), 2)
            },
        }

    report["brightness_sweep"] = {
        "grid_vis": [VIS_GRID[0], VIS_GRID[-1], len(VIS_GRID)],
        "grid_nir": [NIR_GRID[0], NIR_GRID[-1], len(NIR_GRID)],
        "shipped_land_mask": run_sweep("usable"),
        "rock_also_removed": run_sweep("usable_core"),
        # The operating point is chosen from the high-sun anchors, where the
        # per-pixel truth follows from the scene-level truth without argument.
        # The low-sun February scene is then reported against that choice rather
        # than allowed to drag it, because a shadowed ice pixel is dark for a
        # reason no threshold can undo, and letting it pull the floors down
        # would buy February recall with summer water.
        "high_sun_only": run_sweep("usable_core", exclude_roles=("frozen_lowsun",)),
        "rock_mask_fraction": round(float(rock.mean()), 4) if rock.size else None,
    }
    core = report["brightness_sweep"]["high_sun_only"]
    vis_best, nir_best = core["best_vis"], core["best_nir"]

    # --- 2. how each individual scene behaves under the chosen floors ------
    per_scene: List[Dict[str, Any]] = []
    for s in scenes:
        usable = s["usable_core"]
        if not usable.any():
            continue
        green = s["green"][usable]
        nir = s["nir"][usable]
        swir = s["swir"][usable]
        gated = brightness_gate(green, nir, vis_best, nir_best)
        gated_current = brightness_gate(green, nir, 0.08, 0.17)
        ndsi_all = ndsi_of(green, swir)
        entry: Dict[str, Any] = {
            "day": s["day"],
            "role": s["role"],
            "label": s["label"],
            "sun_elevation": round(float(s["meta"]["sun_elevation"] or 0.0), 1),
            "usable_px": int(usable.sum()),
            "green_p05": round(float(np.percentile(green, 5)), 4),
            "green_p50": round(float(np.percentile(green, 50)), 4),
            "green_p95": round(float(np.percentile(green, 95)), 4),
            "nir_p05": round(float(np.percentile(nir, 5)), 4),
            "nir_p50": round(float(np.percentile(nir, 50)), 4),
            "nir_p95": round(float(np.percentile(nir, 95)), 4),
            "gated_fraction_best": round(float(gated.mean()), 4),
            "gated_fraction_current": round(float(gated_current.mean()), 4),
            "ndsi_all_p50": round(float(np.percentile(ndsi_all, 50)), 4),
        }
        if gated.any():
            ndsi_gated = ndsi_all[gated]
            otsu, eta = otsu_threshold(ndsi_gated)
            valley, modes = histogram_valley(ndsi_gated)
            entry.update(
                {
                    # On a water anchor these say what the gate caught. Values
                    # up around the fast-ice range are icebergs, which are real
                    # ice; values hugging the floor are marginal water, which is
                    # error. The two cost very different things.
                    "gated_green_p50": round(float(np.median(green[gated])), 4),
                    "gated_nir_p50": round(float(np.median(nir[gated])), 4),
                    "ndsi_gated_p01": round(float(np.percentile(ndsi_gated, 1)), 4),
                    "ndsi_gated_p05": round(float(np.percentile(ndsi_gated, 5)), 4),
                    "ndsi_gated_p25": round(float(np.percentile(ndsi_gated, 25)), 4),
                    "ndsi_gated_p50": round(float(np.percentile(ndsi_gated, 50)), 4),
                    "ndsi_gated_p75": round(float(np.percentile(ndsi_gated, 75)), 4),
                    "ndsi_gated_otsu": round(float(otsu), 4),
                    "ndsi_gated_otsu_eta": round(float(eta), 3),
                    "ndsi_gated_valley": round(float(valley), 4),
                    "ndsi_gated_modes": modes,
                }
            )
        per_scene.append(entry)
    report["per_scene"] = per_scene

    # --- 3. the NDSI cuts --------------------------------------------------
    #
    # ndsi_light is a floor: below it a bright pixel is not cryosphere at all,
    # it is missed cloud or sunlit rock. It is read off the low tail of the
    # gated NDSI on scenes that are entirely ice, where by construction almost
    # nothing below the cut should exist.
    #
    # ndsi_solid splits solid from thin or wet ice. There is no ground truth for
    # that split anywhere in this record, so it is read from the shape of the
    # distribution, and only quoted as an interval.
    frozen_gated = []
    for s in scenes:
        if s["label"] != "ice":
            continue
        usable = s["usable_core"]
        green, nir, swir = s["green"][usable], s["nir"][usable], s["swir"][usable]
        gated = brightness_gate(green, nir, vis_best, nir_best)
        if gated.any():
            frozen_gated.append(ndsi_of(green, swir)[gated])
    frozen_ndsi = (
        np.concatenate(frozen_gated) if frozen_gated else np.empty(0, dtype=np.float32)
    )

    breakup_gated = []
    for s in scenes:
        if s["role"] != "breakup":
            continue
        usable = s["usable_core"]
        green, nir, swir = s["green"][usable], s["nir"][usable], s["swir"][usable]
        gated = brightness_gate(green, nir, vis_best, nir_best)
        if gated.any():
            breakup_gated.append(ndsi_of(green, swir)[gated])
    breakup_ndsi = (
        np.concatenate(breakup_gated)
        if breakup_gated
        else np.empty(0, dtype=np.float32)
    )

    def describe(values: np.ndarray) -> Dict[str, Any]:
        if values.size == 0:
            return {"n": 0}
        otsu, eta = otsu_threshold(values)
        valley, modes = histogram_valley(values)
        return {
            "n": int(values.size),
            "p01": round(float(np.percentile(values, 1)), 4),
            "p02": round(float(np.percentile(values, 2)), 4),
            "p05": round(float(np.percentile(values, 5)), 4),
            "p10": round(float(np.percentile(values, 10)), 4),
            "p25": round(float(np.percentile(values, 25)), 4),
            "p50": round(float(np.percentile(values, 50)), 4),
            "p75": round(float(np.percentile(values, 75)), 4),
            "p95": round(float(np.percentile(values, 95)), 4),
            "otsu": round(float(otsu), 4),
            "otsu_eta": round(float(eta), 3),
            "valley": round(float(valley), 4),
            "modes": modes,
        }

    report["ndsi_gated"] = {
        "frozen_anchors": describe(frozen_ndsi),
        "breakup_scenes": describe(breakup_ndsi),
    }

    # --- 4. NDWI, which decides the water class ---------------------------
    water_ndwi = []
    for s in scenes:
        if s["label"] != "water":
            continue
        usable = s["usable_core"]
        water_ndwi.append(ndwi_of(s["green"][usable], s["nir"][usable]))
    ndwi_values = (
        np.concatenate(water_ndwi) if water_ndwi else np.empty(0, dtype=np.float32)
    )
    report["ndwi_open_water"] = describe(ndwi_values)

    # --- 4a. what NDSI actually measures here -------------------------------
    #
    # The single most consequential measurement in this file, and it needs no
    # threshold to make: on the one scene that holds bright fast ice, grey thin
    # ice and open water at the same time under the same sun, sort every usable
    # pixel by its near-infrared reflectance and walk up the deciles. Brightness
    # runs from 0.015 to 0.68 across that walk. NDSI does not move.
    #
    # At top of atmosphere over this fjord NDSI is about 0.94 for solid ice, for
    # thin ice and for open water alike, because all three are nearly black at
    # 1.6 um and the index only ever sees the green band divided by itself. It
    # carries almost no information about the surface. The old thresholds worked
    # only because adding 0.1 to both terms of a normalised difference destroys
    # its scale invariance and turns it into a brightness proxy: the bug was
    # doing the classification. That is why the brightness gate had to exist, and
    # it is why no NDSI cut can be asked to separate solid ice from thin ice.
    report["ndsi_versus_brightness"] = []
    for s in scenes:
        if s["role"] != "mixed":
            continue
        usable = s["usable_core"]
        green, nir, swir = s["green"][usable], s["nir"][usable], s["swir"][usable]
        order = np.argsort(nir)
        chunks = np.array_split(order, 10)
        report["ndsi_versus_brightness"].append(
            {
                "day": s["day"],
                "sun_elevation": round(float(s["meta"]["sun_elevation"] or 0.0), 1),
                "deciles": [
                    {
                        "nir": round(float(np.median(nir[idx])), 4),
                        "green": round(float(np.median(green[idx])), 4),
                        "swir": round(float(np.median(swir[idx])), 4),
                        "ndsi": round(
                            float(np.median(ndsi_of(green[idx], swir[idx]))), 4
                        ),
                        "ndwi": round(
                            float(np.median(ndwi_of(green[idx], nir[idx]))), 4
                        ),
                    }
                    for idx in chunks
                ],
            }
        )

    # --- 4b. the thin ice case ---------------------------------------------
    #
    # Reported separately because it is the one place where the classifier as
    # currently wired gets a whole scene wrong, and no choice of threshold fixes
    # it. Thin and wet ice is bright in the green, dark in the near infrared,
    # and near zero in the SWIR. The brightness gate leans on the near infrared,
    # so it rejects the surface; the water test then accepts it, because a
    # green-bright, infrared-dark pixel is exactly what a high NDWI means. The
    # numbers below are what a second, lower ice tier would have to be built on.
    report["thin_ice"] = []
    for s in scenes:
        if s["role"] != "thin_ice":
            continue
        usable = s["usable_core"]
        green, nir, swir = s["green"][usable], s["nir"][usable], s["swir"][usable]
        report["thin_ice"].append(
            {
                "day": s["day"],
                "sun_elevation": round(float(s["meta"]["sun_elevation"] or 0.0), 1),
                "green_p05_p50_p95": [
                    round(float(v), 4) for v in np.percentile(green, [5, 50, 95])
                ],
                "nir_p05_p50_p95": [
                    round(float(v), 4) for v in np.percentile(nir, [5, 50, 95])
                ],
                "swir_p50": round(float(np.median(swir)), 4),
                "ndsi_p50": round(float(np.median(ndsi_of(green, swir))), 4),
                "ndwi_p50": round(float(np.median(ndwi_of(green, nir))), 4),
                "passes_shipped_gate": round(
                    float(
                        brightness_gate(
                            green, nir, SHIPPED["vis_min"], SHIPPED["nir_min"]
                        ).mean()
                    ),
                    4,
                ),
                "would_be_called_water": round(
                    float(
                        (
                            (ndwi_of(green, nir) > SHIPPED["ndwi_min"])
                            & ~brightness_gate(
                                green, nir, SHIPPED["vis_min"], SHIPPED["nir_min"]
                            )
                        ).mean()
                    ),
                    4,
                ),
            }
        )

    # --- 5. the arithmetic that produces the shipped numbers ---------------
    report["recommendation"] = recommend(scenes, frozen_ndsi, breakup_ndsi, ndwi_values)
    report["candidates"] = [
        {**candidate, **score_candidate(scenes, mask_key="usable_core", **candidate)}
        for candidate in build_candidates(report["recommendation"])
    ]
    return report


def recommend(
    scenes: Sequence[Dict[str, Any]],
    frozen_ndsi: np.ndarray,
    breakup_ndsi: np.ndarray,
    water_ndwi: np.ndarray,
) -> Dict[str, Any]:
    """Turn the measured distributions into the numbers that go into the YAML.

    Every value here comes out of a stated rule rather than out of a search, so
    that re-running on a different scene set produces a different number by the
    same reasoning rather than the same number out of habit. The rules are:

      vis_bright_min  the smallest value on the grid that clears the 95th
                      percentile of the green band over open water on the
                      LOW SUN anchors. High sun is not the test: at a sun
                      elevation of 35 degrees open water sits at 0.06 in the
                      green and any floor works. The test is September and
                      October, where atmospheric path radiance lifts water.

      nir_bright_min  bounded below by the same rule applied to the near
                      infrared, bounded above by the requirement that recall on
                      unambiguous fast ice stay at or above 0.995. Reported as
                      an interval, because within it the data do not choose.

      ndsi_light      the Dozier/MODIS snow cut, 0.40. Nothing in this fjord
                      argues with it and the measured headroom to the bottom of
                      the ice distribution is reported so the reader can see how
                      much room there is.

      ndsi_solid      the 1st percentile of the gated NDSI on confirmed fast
                      ice, so that essentially all ice that is beyond doubt is
                      called solid. Whether this split means anything is a
                      separate question, answered by the mode count.

      ndwi            below the 1st percentile of the measured open-water NDWI,
                      so the cut sits under the population it is meant to accept
                      rather than inside it.
    """
    if frozen_ndsi.size == 0:
        return {"available": False}

    # --- the brightness floors, from the low sun open water anchors --------
    low_sun_water = [
        s for s in scenes if s["label"] == "water" and "lowsun" in s["role"]
    ]
    green_p95 = max(
        (float(np.percentile(s["green"][s["usable_core"]], 95)) for s in low_sun_water),
        default=float("nan"),
    )
    nir_p95 = max(
        (float(np.percentile(s["nir"][s["usable_core"]], 95)) for s in low_sun_water),
        default=float("nan"),
    )
    vis_cut = next((v for v in VIS_GRID if v > green_p95), VIS_GRID[-1])
    nir_lower = next((v for v in NIR_GRID if v > nir_p95), NIR_GRID[-1])

    # The darkest day in the record is not labelled, because at a sun elevation
    # of eight degrees over a fjord that may or may not have started freezing,
    # nobody can assert what each pixel is. It still bounds the problem: whatever
    # that surface is, a lot of it is water, and its near infrared reaches much
    # higher than anything the labelled anchors contain.
    darkest = min(
        (s for s in scenes if s["meta"].get("sun_elevation")),
        key=lambda s: s["meta"]["sun_elevation"],
        default=None,
    )
    darkest_nir_p95 = (
        float(np.percentile(darkest["nir"][darkest["usable_core"]], 95))
        if darkest is not None
        else float("nan")
    )

    # Upper bound: how far the near infrared floor can be pushed before it starts
    # costing measurable recall on ice that is beyond doubt.
    ice_green = pooled(scenes, "ice", "green", "usable_core", ("frozen_lowsun",))
    ice_nir = pooled(scenes, "ice", "nir", "usable_core", ("frozen_lowsun",))
    recall_curve = {
        v: float(brightness_gate(ice_green, ice_nir, vis_cut, v).mean())
        for v in NIR_GRID
    }
    nir_upper = max(
        (v for v, r in recall_curve.items() if r >= 0.995), default=nir_lower
    )

    # --- the NDSI cuts ------------------------------------------------------
    solid_cut = float(np.percentile(frozen_ndsi, 1))
    _, frozen_eta = otsu_threshold(frozen_ndsi)
    _, frozen_modes = histogram_valley(frozen_ndsi)
    ice_floor_observed = float(np.percentile(frozen_ndsi, 0.1))
    light_cut = LITERATURE["dozier_1989_ndsi_snow"]

    water_floor = (
        float(np.percentile(water_ndwi, 1)) if water_ndwi.size else float("nan")
    )

    return {
        "available": True,
        "low_sun_water_green_p95": round(green_p95, 4),
        "low_sun_water_nir_p95": round(nir_p95, 4),
        "darkest_day": darkest["day"] if darkest is not None else None,
        "darkest_day_sun_elevation": (
            round(float(darkest["meta"]["sun_elevation"]), 1)
            if darkest is not None
            else None
        ),
        "darkest_day_nir_p95": round(darkest_nir_p95, 4),
        "vis_bright_min": vis_cut,
        "nir_bright_min_interval": [nir_lower, nir_upper],
        "nir_bright_min_recall_at_lower": round(recall_curve[nir_lower], 5),
        "nir_bright_min_recall_at_upper": round(recall_curve[nir_upper], 5),
        "ndsi_light": light_cut,
        "ndsi_light_headroom": round(ice_floor_observed - light_cut, 3),
        "ndsi_light_ice_distribution_starts_at": round(ice_floor_observed, 3),
        "ndsi_solid": round(solid_cut, 2),
        "ndsi_solid_interval": [
            round(float(np.percentile(frozen_ndsi, 5)), 3),
            round(float(np.percentile(frozen_ndsi, 0.1)), 3),
        ],
        "ndsi_solid_is_a_real_boundary": bool(frozen_modes >= 2),
        "ndsi_solid_otsu_separability": round(float(frozen_eta), 3),
        "ndwi": round(np.floor(water_floor * 20) / 20, 2) if water_ndwi.size else None,
        "ndwi_open_water_p01": round(water_floor, 3),
        "breakup_median_ndsi": (
            round(float(np.median(breakup_ndsi)), 3) if breakup_ndsi.size else None
        ),
    }


def build_candidates(recommendation: Dict[str, Any]) -> List[Dict[str, float]]:
    """The threshold sets whose confusion is reported side by side."""
    if not recommendation.get("available"):
        return []
    derived = {
        "vis_min": recommendation["vis_bright_min"],
        "nir_min": recommendation["nir_bright_min_interval"][0],
        "ndsi_light": recommendation["ndsi_light"],
        "ndsi_solid": recommendation["ndsi_solid"],
        "ndwi_min": recommendation["ndwi"],
    }
    derived_top = {
        **derived,
        "nir_min": recommendation["nir_bright_min_interval"][1],
    }
    before = {
        "vis_min": 0.08,
        "nir_min": 0.17,
        "ndsi_light": 0.31,
        "ndsi_solid": 0.52,
        "ndwi_min": 0.25,
    }
    modis = {
        "vis_min": 0.10,
        "nir_min": 0.11,
        "ndsi_light": 0.40,
        "ndsi_solid": recommendation["ndsi_solid"],
        "ndwi_min": 0.25,
    }
    no_gate = {
        "vis_min": 0.0,
        "nir_min": 0.0,
        "ndsi_light": 0.31,
        "ndsi_solid": 0.52,
        "ndwi_min": 0.25,
    }
    return [before, modis, derived, derived_top, dict(SHIPPED), no_gate]


def candidate_table(
    cache_dir: Path,
    candidates: Sequence[Dict[str, float]],
    mask_key: str = "usable_core",
) -> List[Dict[str, Any]]:
    """Score a list of threshold sets against the labelled scenes."""
    scenes, _ = prepare(cache_dir)
    rows = []
    for candidate in candidates:
        row = dict(candidate)
        row.update(score_candidate(scenes, mask_key=mask_key, **candidate))
        rows.append(row)
    return rows


def format_summary(report: Dict[str, Any]) -> str:
    """The report as something a person can read and argue with."""
    lines: List[str] = []
    add = lines.append

    add("SCENES USED")
    add(
        f"  {'day':11} {'role':14} {'label':6} {'baseline':9} {'sun':>5} "
        f"{'cloud':>7} {'usable':>7}"
    )
    for scene in report["scenes"]:
        add(
            f"  {scene['day']:11} {scene['role']:14} {str(scene['label']):6} "
            f"{scene['baseline']:9} {float(scene['sun_elevation'] or 0):5.1f} "
            f"{scene['cloud_fraction']:7.4f} {scene['usable_fraction']:7.4f}"
        )

    cross = report.get("cross_baseline", {})
    add("")
    add("OFFSET CORRECTION, CHECKED AGAINST ITSELF")
    if cross.get("available"):
        add(f"  {cross['item_a']} (baseline {cross['baseline_a']})")
        add(f"  {cross['item_b']} (baseline {cross['baseline_b']})")
        add("  same acquisition, two encodings, median absolute difference per band:")
        for band, stats in cross["bands"].items():
            if "median_abs_diff" in stats:
                add(
                    f"    {band:6} median {stats['median_abs_diff']:.2e}  "
                    f"p99 {stats['p99_abs_diff']:.2e}"
                )
        add("  a wrong sign would put 0.1 here, in every band.")
    else:
        add("  not available: the paired encoding was not cached")

    sweep = report["brightness_sweep"]
    add("")
    add("BRIGHTNESS GATE, HIGH SUN ANCHORS ONLY")
    high = sweep["high_sun_only"]
    add(f"  ice pixels {high['ice_px']}, water pixels {high['water_px']}")
    add(
        f"  plateau within 0.001 of the best: vis {high['plateau_vis']}, "
        f"nir {high['plateau_nir']}"
    )
    add("  the arg-max is not the answer, the plateau is.")
    add("  recall on fast ice and false ice on open water, at vis 0.10:")
    for nir, recall in high["recall_by_nir_at_vis_0.10"].items():
        add(
            f"    nir {nir:>5}  recall {recall:.5f}  false ice {high['false_ice_by_nir_at_vis_0.10'][nir]:.5f}"
        )

    add("")
    add("PER SCENE, AT THE DERIVED FLOORS")
    add(
        f"  {'day':11} {'label':6} {'sun':>5} {'green p50':>10} {'nir p50':>8} "
        f"{'gated':>7} {'ndsi p50':>9} {'modes':>6}"
    )
    for scene in report["per_scene"]:
        add(
            f"  {scene['day']:11} {str(scene['label']):6} {scene['sun_elevation']:5.1f} "
            f"{scene['green_p50']:10.4f} {scene['nir_p50']:8.4f} "
            f"{scene['gated_fraction_best']:7.4f} "
            f"{scene.get('ndsi_gated_p50', float('nan')):9.4f} "
            f"{scene.get('ndsi_gated_modes', 0):6d}"
        )

    add("")
    add("NDSI ON GATED PIXELS")
    for name, stats in report["ndsi_gated"].items():
        if stats.get("n"):
            add(
                f"  {name:16} n={stats['n']:>8}  p01 {stats['p01']:.4f}  "
                f"p50 {stats['p50']:.4f}  p95 {stats['p95']:.4f}  "
                f"otsu {stats['otsu']:.4f} (eta {stats['otsu_eta']:.2f})  "
                f"modes {stats['modes']}"
            )

    add("")
    add("CANDIDATE THRESHOLD SETS")
    add(
        f"  {'vis':>5} {'nir':>5} {'light':>6} {'solid':>6} {'ndwi':>5}  "
        f"{'ice recall':>11} {'water recall':>13} {'balanced':>9}"
    )
    for row in report["candidates"]:
        add(
            f"  {row['vis_min']:5.2f} {row['nir_min']:5.2f} {row['ndsi_light']:6.2f} "
            f"{row['ndsi_solid']:6.2f} {row['ndwi_min']:5.2f}  "
            f"{row['ice_recall_lower_bound']:11.5f} {row['water_recall']:13.5f} "
            f"{row['balanced_accuracy']:9.5f}"
        )

    for entry in report.get("ndsi_versus_brightness", []):
        add("")
        add(
            f"WHAT NDSI MEASURES, {entry['day']} sun {entry['sun_elevation']}, "
            "pixels sorted into near-infrared deciles"
        )
        add(f"  {'nir':>7} {'green':>7} {'swir':>7} {'NDSI':>7} {'NDWI':>7}")
        for row in entry["deciles"]:
            add(
                f"  {row['nir']:7.4f} {row['green']:7.4f} {row['swir']:7.4f} "
                f"{row['ndsi']:7.4f} {row['ndwi']:7.4f}"
            )
        add("  brightness spans the whole scene. NDSI does not move.")

    if report.get("thin_ice"):
        add("")
        add("THIN OR WET ICE, WHICH THE CLASSIFIER CANNOT SEE")
        for entry in report["thin_ice"]:
            add(
                f"  {entry['day']} sun {entry['sun_elevation']}  "
                f"green {entry['green_p05_p50_p95']}  nir {entry['nir_p05_p50_p95']}  "
                f"swir {entry['swir_p50']}"
            )
            add(
                f"    ndsi {entry['ndsi_p50']}  ndwi {entry['ndwi_p50']}  "
                f"passes the gate {entry['passes_shipped_gate']}  "
                f"called water {entry['would_be_called_water']}"
            )

    add("")
    add("RECOMMENDATION")
    for key, value in report["recommendation"].items():
        add(f"  {key}: {value}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--stage", choices=("cache", "analyse", "all"), default="all")
    parser.add_argument("--force", action="store_true", help="re-download the cache")
    parser.add_argument("--report", type=Path, default=None, help="write JSON here")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.stage in ("cache", "all"):
        build_cache(args.cache_dir, force=args.force)
    if args.stage == "cache":
        return

    report = analyse(args.cache_dir)
    print(format_summary(report))
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, default=str))
        logging.info("full report written to %s", args.report)


if __name__ == "__main__":
    main()
