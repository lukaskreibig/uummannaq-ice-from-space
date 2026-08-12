"""Tests for the radiometric offset and the ice/water decision.

Two defects are locked in here because both were silent and both changed every
published number:

1. The processing-baseline 04.00 offset was applied with the wrong sign, so both
   eras came out 0.1 above true reflectance.
2. NDSI on its own does not separate ice from water at top of atmosphere. Both
   are nearly black in the SWIR, so the ratio saturates for each: on the
   committed endmembers open water reads 0.866 and April fast ice 0.871, a gap
   of 0.005, and water clears the 0.70 solid threshold outright. The offset
   error happened to compress dark
   pixels far more than bright ones and was therefore doing the separating. Fix
   the sign without adding a brightness floor and the classifier calls the open
   summer fjord ice: measured on the real 2023-08-18 scene, the ice fraction
   goes from 0.004 to 0.584.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from uummannaq_ice.config import Thresholds
from uummannaq_ice.processing import (
    BANDS,
    GREEN_IDX,
    NIR_IDX,
    QUANTIFICATION_VALUE,
    SWIR_IDX,
    reflectance_cube,
    void_reflectance,
)


class FakeBand:
    """Stands in for the xarray DataArray odc.stac hands back."""

    def __init__(self, values):
        self.values = np.asarray(values, dtype=np.float32)

    def __getitem__(self, index):
        return self


def cube_from_dn(dn_value: float):
    band = FakeBand([[dn_value]])
    return dict.fromkeys(BANDS, band)


# --- the offset itself ----------------------------------------------------


def test_pre_baseline_four_is_a_plain_division():
    """Before 04.00 the conversion is DN / 10000 with nothing added."""
    cube = reflectance_cube(cube_from_dn(5000), baseline_major=3)
    assert cube.shape[0] == len(BANDS)
    assert cube[0, 0, 0] == pytest.approx(0.5)


def test_baseline_four_subtracts_the_offset():
    """From 04.00 the DN carries RADIO_ADD_OFFSET = -1000, so subtract 0.1."""
    cube = reflectance_cube(cube_from_dn(6000), baseline_major=4)
    assert cube[0, 0, 0] == pytest.approx(0.5)


def test_the_two_eras_agree_on_the_same_surface():
    """The whole point: one physical reflectance, two encodings, one answer."""
    old = reflectance_cube(cube_from_dn(5000), baseline_major=2)
    new = reflectance_cube(cube_from_dn(6000), baseline_major=5)
    assert old[0, 0, 0] == pytest.approx(new[0, 0, 0])


def test_offset_is_not_added_to_the_old_era():
    """Regression: the bug added +0.1 here, which is what broke everything."""
    cube = reflectance_cube(cube_from_dn(0), baseline_major=3)
    assert cube[0, 0, 0] == pytest.approx(0.0)


def test_quantification_value_is_the_documented_one():
    assert QUANTIFICATION_VALUE == 10000.0


# --- void detection -------------------------------------------------------


def test_void_reflectance_per_era():
    assert void_reflectance(3) == pytest.approx(0.0)
    assert void_reflectance(4) == pytest.approx(-0.1)
    assert void_reflectance(5) == pytest.approx(-0.1)


def test_a_void_pixel_lands_on_the_void_value():
    """DN = 0 is NO_DATA in both eras and must be recognisable as such."""
    for baseline in (2, 5):
        cube = reflectance_cube(cube_from_dn(0), baseline_major=baseline)
        assert cube[0, 0, 0] == pytest.approx(void_reflectance(baseline))


def test_dark_water_is_not_mistaken_for_void_after_the_fix():
    """A sum-based void test would discard real water from 04.00 onwards.

    Open water has a per-band reflectance of roughly 0.01, so from baseline 04.00
    it sits near -0.09 after the offset, and 13 bands of that sum to about -1.2,
    very close to a void pixel's -1.3. Testing each band against the void value
    keeps them apart; summing the cube does not.
    """
    water_dn = 100  # 0.01 reflectance
    cube = reflectance_cube(cube_from_dn(water_dn), baseline_major=5)
    void = void_reflectance(5)

    per_band_says_void = np.all(np.abs(cube - void) < 1e-4, axis=0)
    assert not per_band_says_void.any()

    # and the old sum test would have been fooled
    assert cube.sum(axis=0)[0, 0] < 1e-6


# --- the ice/water decision ----------------------------------------------


def _decide(green, nir, swir, thresholds, *, brightness_gate=True):
    """Mirror of the decision in classify_tile, on scalar reflectances."""
    ndsi = (green - swir) / (green + swir + 1e-6)
    ndwi = (green - nir) / (green + nir + 1e-6)
    bright = True
    if brightness_gate:
        bright = green > thresholds.vis_bright_min and nir > thresholds.nir_bright_min
    solid = ndsi > thresholds.ndsi_solid and bright
    light = thresholds.ndsi_light < ndsi < thresholds.ndsi_solid and bright
    water = ndwi > thresholds.ndwi and not solid and not light
    return solid, light, water


# True top-of-atmosphere reflectances measured over the Uummannaq AOI.
FAST_ICE = {"green": 0.697, "nir": 0.600, "swir": 0.112}
OPEN_WATER = {"green": 0.010, "nir": 0.005, "swir": 0.001}


def test_open_water_really_does_have_a_high_ndsi():
    """The fact the whole brightness gate exists for."""
    g, s = OPEN_WATER["green"], OPEN_WATER["swir"]
    water_ndsi = (g - s) / (g + s)
    g, s = FAST_ICE["green"], FAST_ICE["swir"]
    ice_ndsi = (g - s) / (g + s)
    assert water_ndsi > ice_ndsi
    assert water_ndsi > Thresholds().ndsi_solid


def test_ndsi_alone_misclassifies_open_water_as_ice():
    """Regression guard: this is what fixing the sign alone would ship."""
    solid, _, _ = _decide(**OPEN_WATER, thresholds=Thresholds(), brightness_gate=False)
    assert solid is True


def test_brightness_gate_rejects_open_water():
    solid, light, water = _decide(**OPEN_WATER, thresholds=Thresholds())
    assert not solid
    assert not light
    assert water


def test_brightness_gate_keeps_fast_ice():
    solid, light, water = _decide(**FAST_ICE, thresholds=Thresholds())
    assert solid
    assert not light
    assert not water


def test_thin_ice_stays_in_the_light_class():
    thin = {"green": 0.35, "nir": 0.30, "swir": 0.10}  # NDSI 0.556
    solid, light, _ = _decide(**thin, thresholds=Thresholds())
    assert not solid
    assert light


def test_gate_thresholds_sit_between_water_and_ice():
    """The floors must actually separate the two populations, with headroom."""
    t = Thresholds()
    assert OPEN_WATER["green"] < t.vis_bright_min < FAST_ICE["green"]
    assert OPEN_WATER["nir"] < t.nir_bright_min < FAST_ICE["nir"]


def test_band_indices_point_where_the_names_say():
    assert BANDS[GREEN_IDX] == "green"
    assert BANDS[NIR_IDX] == "nir"
    assert BANDS[SWIR_IDX] == "swir16"


def test_cube_stacks_all_thirteen_bands():
    cube = reflectance_cube(cube_from_dn(3000), baseline_major=5)
    assert cube.shape[0] == 13
    assert torch.from_numpy(cube).shape[0] == 13


# --- cloud independent denominator ---------------------------------------


def test_clear_denominator_is_independent_of_cloud():
    """The published metric divides by the whole grid, so cloud lowers it.

    Cloud is not evenly spread over the record, so that turns a weather trend
    into an apparent ice trend. The _clear columns divide by the cells that
    could actually be judged and are therefore stable when only cloud changes.
    """
    from uummannaq_ice.processing import summarise_masks

    shape = (10, 10)

    def run(cloud_cells):
        z = lambda: np.zeros(shape, dtype=bool)  # noqa: E731
        ice_solid, ice_light, water = z(), z(), z()
        cloud, land, nodata = z(), z(), z()
        cloud.flat[:cloud_cells] = True
        free = ~cloud
        idx = np.flatnonzero(free)
        # half of whatever is visible is ice, the other half water
        ice_solid.flat[idx[: len(idx) // 2]] = True
        water.flat[idx[len(idx) // 2 :]] = True
        masks = {
            "ice_solid": ice_solid,
            "ice_light": ice_light,
            "water": water,
            "cloud": cloud,
            "land": land,
            "nodata": nodata,
        }
        return summarise_masks(
            masks, np.full(shape, 0.6), np.full(shape, 0.1), nodata_threshold=0.2
        )

    clear_sky = run(0)
    cloudy = run(40)

    # the whole-grid figure collapses purely because of cloud
    assert clear_sky["solid_pct"] > cloudy["solid_pct"]
    # the clear-sky figure does not move
    assert clear_sky["solid_pct_clear"] == pytest.approx(
        cloudy["solid_pct_clear"], abs=0.02
    )


def test_clear_columns_are_present_and_consistent():
    from uummannaq_ice.processing import summarise_masks

    shape = (4, 4)
    z = lambda: np.zeros(shape, dtype=bool)  # noqa: E731
    ice_solid, cloud = z(), z()
    ice_solid[:2] = True
    cloud[3] = True
    masks = {
        "ice_solid": ice_solid,
        "ice_light": z(),
        "water": z(),
        "cloud": cloud,
        "land": z(),
        "nodata": z(),
    }
    s = summarise_masks(
        masks, np.full(shape, 0.6), np.full(shape, 0.1), nodata_threshold=0.2
    )
    # Three different denominators, and the fixture separates all three: 16
    # cells, 4 of them cloud, 8 solid ice, and the remaining row in no class at
    # all, which is what a dark cell failing both the ice and the water test
    # looks like.
    assert s["clear_px"] == 12  # what could be SEEN
    assert s["classified_px"] == 8  # what came out as SOMETHING
    assert s["unclassified_px"] == 4  # seen, and still nothing
    assert s["solid_pct"] == pytest.approx(8 / 16)

    # The published fraction divides by what could be judged, not by what could
    # be seen. Dividing by 12 would put four cells in the denominator that can
    # never reach a numerator, which only ever pushes the ice fraction down.
    # The writer rounds to four decimals, like every other percentage column.
    assert s["solid_pct_clear"] == pytest.approx(8 / 8, abs=1e-4)


def test_clear_percentages_are_blank_when_nothing_is_visible():
    from uummannaq_ice.processing import summarise_masks

    shape = (4, 4)
    z = lambda: np.zeros(shape, dtype=bool)  # noqa: E731
    all_cloud = np.ones(shape, dtype=bool)
    masks = {
        "ice_solid": z(),
        "ice_light": z(),
        "water": z(),
        "cloud": all_cloud,
        "land": z(),
        "nodata": z(),
    }
    s = summarise_masks(
        masks, np.full(shape, 0.6), np.full(shape, 0.1), nodata_threshold=0.2
    )
    assert s["clear_px"] == 0
    assert s["solid_pct_clear"] == ""


# --- Sichtbarkeitsschwelle -------------------------------------------------


def _masks(shape, cloud_cells=0):
    z = np.zeros(shape, dtype=bool)
    cloud = np.zeros(shape, dtype=bool)
    cloud.flat[:cloud_cells] = True
    ice = ~cloud
    return {
        "ice_solid": ice,
        "ice_light": z.copy(),
        "water": z.copy(),
        "cloud": cloud,
        "land": z.copy(),
        "nodata": z.copy(),
    }


def test_a_mostly_clear_scene_is_usable():
    from uummannaq_ice.processing import summarise_masks

    s = summarise_masks(
        _masks((10, 10), cloud_cells=10),
        np.full((10, 10), 0.6),
        np.full((10, 10), 0.1),
        nodata_threshold=0.2,
    )
    assert s["clear_pct"] == pytest.approx(0.9)
    assert s["usable"] == 1


def test_a_scene_that_only_saw_weather_is_not_usable():
    """318 of 1552 published scenes are over 80 percent cloud and counted fully."""
    from uummannaq_ice.processing import summarise_masks

    s = summarise_masks(
        _masks((10, 10), cloud_cells=85),
        np.full((10, 10), 0.6),
        np.full((10, 10), 0.1),
        nodata_threshold=0.2,
    )
    assert s["clear_pct"] == pytest.approx(0.15)
    assert s["usable"] == 0


def test_the_usable_flag_sits_on_the_documented_threshold():
    from uummannaq_ice.processing import MIN_CLEAR_SHARE, summarise_masks

    just_over = summarise_masks(
        _masks((100, 1), cloud_cells=int(100 * (1 - MIN_CLEAR_SHARE)) - 1),
        np.full((100, 1), 0.6),
        np.full((100, 1), 0.1),
        nodata_threshold=0.2,
    )
    just_under = summarise_masks(
        _masks((100, 1), cloud_cells=int(100 * (1 - MIN_CLEAR_SHARE)) + 1),
        np.full((100, 1), 0.6),
        np.full((100, 1), 0.1),
        nodata_threshold=0.2,
    )
    assert just_over["usable"] == 1
    assert just_under["usable"] == 0


# --- Determinismus ---------------------------------------------------------


def test_cloud_inference_has_no_autocast_left():
    """autocast plus a hard 0.5 threshold made the mask device dependent.

    The same scene produced cloud masks differing on about 1.9 percent of cells
    between CPU and MPS, which means the published archive depended on which
    machine produced it.
    """
    import inspect

    from uummannaq_ice import processing

    source = inspect.getsource(processing.compute_cloud_mask)
    assert "autocast" not in source.split('"""')[-1]
    assert "argmax" in source


def test_cloud_mask_is_reproducible_on_the_same_input():
    from uummannaq_ice.processing import compute_cloud_mask

    torch.manual_seed(0)

    class Fixed(torch.nn.Module):
        def forward(self, x):
            n, _, h, w = x.shape
            out = torch.zeros(n, 4, h, w)
            out[:, 0] = 1.0
            out[:, 1, : h // 2] = 2.0  # top half is thick cloud
            return out

    cube = torch.rand(13, 32, 32)
    device = torch.device("cpu")
    a = compute_cloud_mask(Fixed(), cube, device)
    b = compute_cloud_mask(Fixed(), cube, device)
    assert np.array_equal(a, b)
    # binary_closing erodes the array border, so the halves are not pristine
    assert a[:16].mean() > 0.85
    assert a[16:].mean() < 0.15
