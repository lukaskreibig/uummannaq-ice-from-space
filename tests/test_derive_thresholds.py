"""Tests for scripts/derive_thresholds.py.

The derivation script is the audit trail for every threshold in baseline.yaml, so
the parts of it that are pure arithmetic are tested like library code. Three
things matter here:

1. the script's own copy of the class assignment must stay identical to the one
   in processing.classify_tile, otherwise the thresholds are derived against a
   classifier that is not the one that runs;
2. the mode-finding must actually find modes, and must say so when there are
   none, because an Otsu cut on a unimodal distribution is a number with no
   meaning and it would otherwise be quoted as if it had one;
3. the scene table must keep spanning the season and the baseline boundary,
   because a table that quietly drifted to one side of 25 January 2022 would
   re-introduce exactly the bias the whole exercise exists to remove.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from uummannaq_ice.config import Thresholds
from uummannaq_ice.config_loader import load_run_config
from uummannaq_ice.processing import BANDS, GREEN_IDX, NIR_IDX, SWIR_IDX

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "derive_thresholds.py"
BASELINE_YAML = REPO_ROOT / "config" / "baseline.yaml"

# The offset changed with baseline 04.00, operational from this date.
BASELINE_FOUR_START = date(2022, 1, 25)


def _load_script():
    """Import scripts/derive_thresholds.py, which is not on the package path.

    The module has to be registered in sys.modules before it is executed:
    @dataclass resolves annotations through sys.modules[cls.__module__] and
    raises if the entry is missing.
    """
    spec = importlib.util.spec_from_file_location("derive_thresholds", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


derive = _load_script()


# --- the script must classify exactly like the pipeline --------------------


def test_classify_matches_the_pipeline_classifier(monkeypatch):
    """The script's copy of the decision must agree with processing.classify_tile.

    If these two ever drift, the thresholds are tuned against a classifier that
    is not the one the pipeline runs, and nothing downstream would notice.
    """
    import torch

    from uummannaq_ice import processing

    rng = np.random.default_rng(20220125)
    cube = rng.uniform(-0.05, 0.9, size=(len(BANDS), 16, 16)).astype(np.float32)
    land = np.zeros((16, 16), dtype=bool)
    land[0, :] = True
    cloud = np.zeros((16, 16), dtype=bool)
    cloud[:, 0] = True
    monkeypatch.setattr(processing, "compute_cloud_mask", lambda *_a, **_k: cloud)

    thresholds = Thresholds()
    result = processing.classify_tile(
        torch.from_numpy(cube),
        land,
        thresholds,
        model=None,
        device=torch.device("cpu"),
        rgb_preview=Image.new("RGB", (8, 8)),
        baseline="05.11",
    )

    nodata = np.all(np.abs(cube - (-0.1)) < 1e-4, axis=0)
    usable = ~cloud & ~land & ~nodata
    mine = derive.classify(
        cube[GREEN_IDX],
        cube[NIR_IDX],
        cube[SWIR_IDX],
        usable,
        thresholds.vis_bright_min,
        thresholds.nir_bright_min,
        thresholds.ndsi_light,
        thresholds.ndsi_solid,
        thresholds.ndwi,
    )

    assert np.array_equal(mine["ice_solid"], result.masks["ice_solid"])
    assert np.array_equal(mine["ice_light"], result.masks["ice_light"])
    assert np.array_equal(mine["water"], result.masks["water"])


def test_indices_match_the_pipeline_expressions():
    rng = np.random.default_rng(7)
    green = rng.uniform(0.0, 1.0, 64).astype(np.float32)
    swir = rng.uniform(0.0, 1.0, 64).astype(np.float32)
    nir = rng.uniform(0.0, 1.0, 64).astype(np.float32)
    assert np.allclose(
        derive.ndsi_of(green, swir), (green - swir) / (green + swir + 1e-6)
    )
    assert np.allclose(derive.ndwi_of(green, nir), (green - nir) / (green + nir + 1e-6))


def test_brightness_gate_needs_both_bands():
    green = np.array([0.20, 0.20, 0.02, 0.02])
    nir = np.array([0.30, 0.02, 0.30, 0.02])
    assert derive.brightness_gate(green, nir, 0.08, 0.17).tolist() == [
        True,
        False,
        False,
        False,
    ]


# --- mode finding ---------------------------------------------------------


def test_otsu_recovers_a_clean_two_mode_boundary():
    rng = np.random.default_rng(1)
    values = np.concatenate(
        [rng.normal(0.20, 0.03, 40_000), rng.normal(0.80, 0.03, 40_000)]
    )
    cut, eta = derive.otsu_threshold(values)
    assert 0.45 < cut < 0.55
    assert eta > 0.9


def test_otsu_separability_is_low_on_one_mode():
    """Otsu always returns a number. eta is what says it means nothing."""
    rng = np.random.default_rng(2)
    values = rng.normal(0.7, 0.05, 80_000)
    _, eta = derive.otsu_threshold(values)
    assert eta < 0.8


def test_valley_finds_the_gap_between_two_modes():
    rng = np.random.default_rng(3)
    values = np.concatenate(
        [rng.normal(0.20, 0.03, 40_000), rng.normal(0.80, 0.03, 40_000)]
    )
    valley, modes = derive.histogram_valley(values)
    assert modes >= 2
    assert 0.4 < valley < 0.6


def test_valley_reports_a_single_mode_as_such():
    rng = np.random.default_rng(4)
    valley, modes = derive.histogram_valley(rng.normal(0.7, 0.05, 80_000))
    assert modes < 2
    assert np.isnan(valley)


def test_empty_input_does_not_raise():
    empty = np.empty(0, dtype=np.float32)
    assert np.isnan(derive.otsu_threshold(empty)[0])
    assert np.isnan(derive.histogram_valley(empty)[0])


# --- the sweep ------------------------------------------------------------


def test_raising_a_floor_can_never_admit_more_pixels():
    rng = np.random.default_rng(5)
    ice_green = rng.uniform(0.1, 0.9, 5_000)
    ice_nir = rng.uniform(0.1, 0.9, 5_000)
    water_green = rng.uniform(0.0, 0.2, 5_000)
    water_nir = rng.uniform(0.0, 0.1, 5_000)
    grid = [0.02, 0.06, 0.10, 0.20, 0.40]
    out = derive.sweep_brightness_floors(
        ice_green, ice_nir, water_green, water_nir, grid, grid
    )
    for name in ("recall", "false_ice"):
        surface = out[name]
        assert np.all(np.diff(surface, axis=0) <= 1e-12)
        assert np.all(np.diff(surface, axis=1) <= 1e-12)


def test_plateau_interval_reports_the_flat_region_not_the_argmax():
    grid = [0.05, 0.10, 0.15, 0.20, 0.25]
    scores = np.array([0.80, 0.9995, 1.0, 0.9996, 0.70])
    low, high = derive.plateau_interval(scores, grid, tolerance=0.001)
    assert (low, high) == (0.10, 0.20)


# --- scoring --------------------------------------------------------------


def _fake_scene(label, green, nir, swir, n=100):
    shape = (n,)
    return {
        "label": label,
        "green": np.full(shape, green, dtype=np.float32),
        "nir": np.full(shape, nir, dtype=np.float32),
        "swir": np.full(shape, swir, dtype=np.float32),
        "usable": np.ones(shape, dtype=bool),
    }


def test_score_candidate_separates_bright_ice_from_dark_water():
    scenes = [
        # bright in green and nir, dark in swir: unambiguous snow-covered ice
        _fake_scene("ice", green=0.70, nir=0.60, swir=0.05),
        # dark everywhere, and much darker in nir than green: open water
        _fake_scene("water", green=0.04, nir=0.01, swir=0.005),
    ]
    score = derive.score_candidate(
        scenes,
        vis_min=0.08,
        nir_min=0.17,
        ndsi_light=0.40,
        ndsi_solid=0.70,
        ndwi_min=0.25,
    )
    assert score["ice_recall_lower_bound"] == 1.0
    assert score["water_recall"] == 1.0
    assert score["balanced_accuracy"] == 1.0


def test_unlabelled_scenes_are_excluded_from_the_score():
    scenes = [
        _fake_scene("ice", 0.70, 0.60, 0.05),
        _fake_scene(None, 0.70, 0.60, 0.05),
    ]
    score = derive.score_candidate(scenes, 0.08, 0.17, 0.40, 0.70, 0.25)
    assert np.isnan(score["water_recall"])
    assert score["ice_recall_lower_bound"] == 1.0


# --- the scene table ------------------------------------------------------


def test_scene_table_spans_the_baseline_boundary():
    days = [s.day for s in derive.SCENES]
    assert any(d < BASELINE_FOUR_START for d in days), "no pre-04.00 scene"
    assert any(d >= BASELINE_FOUR_START for d in days), "no post-04.00 scene"


def test_scene_table_spans_the_observable_season():
    months = {s.day.month for s in derive.SCENES}
    # 70.7 N has no usable sun in November, December or January.
    assert months >= {2, 4, 5, 6, 8, 9, 10}


def test_every_anchor_is_labelled_on_both_sides_of_the_boundary():
    for label in ("ice", "water"):
        anchors = [s.day for s in derive.SCENES if s.label == label]
        assert len(anchors) >= 3, f"too few {label} anchors"
        assert any(
            d < BASELINE_FOUR_START for d in anchors
        ), f"{label} anchors are all post-04.00"
        assert any(
            d >= BASELINE_FOUR_START for d in anchors
        ), f"{label} anchors are all pre-04.00"


def test_labels_are_only_ever_ice_water_or_absent():
    assert {s.label for s in derive.SCENES} <= {"ice", "water", None}


def test_the_cross_baseline_day_is_in_the_table():
    assert derive.CROSS_BASELINE_DAY in {s.day for s in derive.SCENES}


# --- the config the derivation feeds --------------------------------------


def test_baseline_yaml_thresholds_are_real_fields():
    data = yaml.safe_load(BASELINE_YAML.read_text())
    fields = set(Thresholds.__dataclass_fields__)
    unknown = set(data["thresholds"]) - fields
    assert not unknown, f"baseline.yaml sets thresholds that do not exist: {unknown}"


def test_baseline_yaml_pins_every_threshold_the_classifier_reads():
    """A baseline run must never fall back to a dataclass default.

    config.Thresholds still carries the values that were tuned on the biased
    reflectance. Anything baseline.yaml does not set explicitly is filled in
    from there, silently, and a stale value would change every published number
    with nothing in the log to show for it. So the YAML has to name all of them.
    """
    data = yaml.safe_load(BASELINE_YAML.read_text())["thresholds"]
    required = {
        "ndsi_light",
        "ndsi_solid",
        "ndwi",
        "vis_bright_min",
        "nir_bright_min",
        "nodata_fraction",
    }
    missing = required - set(data)
    assert not missing, f"baseline.yaml leaves these to the stale defaults: {missing}"


def _load_baseline(tmp_path: Path):
    """Load config/baseline.yaml through the real loader, in a scratch directory.

    The YAML is copied first because build_config creates output_dir as a side
    effect of loading, and a test has no business making directories inside the
    repository.
    """
    copy = tmp_path / "baseline.yaml"
    copy.write_text(BASELINE_YAML.read_text())
    return load_run_config(copy)


def test_the_production_config_carries_the_derived_thresholds(tmp_path):
    """The end-to-end path, not just the file: what a baseline run actually uses.

    These are the numbers scripts/derive_thresholds.py produced on the eighteen
    cached scenes. They are locked here so a stray edit to either the YAML or
    the loader shows up as a failing test rather than as a quietly different
    time series.
    """
    thresholds = _load_baseline(tmp_path).thresholds
    assert thresholds.vis_bright_min == pytest.approx(0.10)
    assert thresholds.nir_bright_min == pytest.approx(0.17)
    assert thresholds.ndsi_light == pytest.approx(0.40)
    assert thresholds.ndwi == pytest.approx(0.20)

    # ndsi_solid is the one value that was overridden after the derivation, and
    # deliberately. The script put it at 0.83 because the gated ice distribution
    # it measured starts at 0.824. Checked directly against a completely frozen
    # fjord (2023-04-20, tile 22WDD, 151,150 bright usable cells after cloud,
    # land and stability masking) NDSI runs 0.687 at the 1st percentile to 0.755
    # at the 99th, median 0.720, SWIR median 0.112. At 0.83 not one cell of that
    # fjord is solid ice, so the class empties and mean_ndsi_solid is blank.
    #
    # It does not touch the published number: the story shows solid + light and
    # every one of those cells clears ndsi_light either way, so the ice fraction
    # is identical for any cut between the two. It decides only what the two
    # class names mean. 0.70 sits just under the measured median.
    #
    # The disagreement with the eighteen-scene derivation is unresolved and
    # should be settled before the solid/light split is presented as thick
    # against thin ice.
    assert thresholds.ndsi_solid == pytest.approx(0.70)


def test_the_script_scores_what_the_config_ships(tmp_path):
    """derive_thresholds.SHIPPED must mirror config/baseline.yaml.

    The script prints the confusion of the shipped threshold set alongside the
    alternatives it considered. If its copy of those numbers drifts from the
    YAML, the audit trail quietly starts describing a configuration nobody runs.
    """
    thresholds = _load_baseline(tmp_path).thresholds
    assert derive.SHIPPED == {
        "vis_min": pytest.approx(thresholds.vis_bright_min),
        "nir_min": pytest.approx(thresholds.nir_bright_min),
        "ndsi_light": pytest.approx(thresholds.ndsi_light),
        "ndsi_solid": pytest.approx(thresholds.ndsi_solid),
        "ndwi_min": pytest.approx(thresholds.ndwi),
    }


def test_brightness_floors_are_not_looser_than_the_modis_construction(tmp_path):
    """The gate is what separates ice from water now, so it must not be weakened.

    Hall, Riggs and Salomonson (1995) reject any pixel whose near-infrared
    planetary reflectance is under 0.11, precisely because water can otherwise
    reach a snow-like NDSI. The floors used here must stay at least that strict:
    the whole failure mode the gate exists to prevent is dark summer water being
    called ice.
    """
    thresholds = _load_baseline(tmp_path).thresholds
    assert thresholds.nir_bright_min >= derive.LITERATURE["modis_nir_brightness_floor"]
    assert thresholds.vis_bright_min >= 0.0


def test_ndsi_cuts_are_ordered_and_physically_plausible(tmp_path):
    thresholds = _load_baseline(tmp_path).thresholds
    assert thresholds.ndsi_light < thresholds.ndsi_solid
    # Ice with an NDSI below zero is brighter in the SWIR than in the green,
    # which no frozen surface is. Above 1.0 is not reachable at all.
    assert 0.0 < thresholds.ndsi_light < 1.0
    assert 0.0 < thresholds.ndsi_solid < 1.0
    # The Dozier/MODIS snow cut is the documented floor for calling a bright
    # pixel cryosphere at all. Sea ice is darker and less contrasted than alpine
    # snow, so the sea-ice cut may sit at that value but should never sit above
    # it, or genuine thin ice starts being thrown away.
    assert thresholds.ndsi_light <= derive.LITERATURE["dozier_1989_ndsi_snow"]
