"""A silently failed band read must never reach the archive.

GDAL can fail a COG read inside curl (`curl_multi_poll() failed`), return the
band as pure fill, and raise nothing. odc fills it, the row is written, and the
scene is published as a plausible open-water day: with NIR zeroed,
NDWI = (green - 0)/(green + 0) = 1 exactly. Measured under concurrent loading,
the same ten scenes gave ice fractions of 0.8947, 0.0000, 0.8289 and 0.0084
across four runs.

The first version of this guard used a one percentage point spread rule, which
rejected real observations: the thirteen bands have three native resolutions
(10, 20 and 60 m) and resample with genuinely different fill fractions at a
swath edge.
"""

from __future__ import annotations

import numpy as np
import pytest

from uummannaq_ice.pipeline import (
    BLANK_BAND_SHARE,
    NOT_A_BLANK_SCENE,
    PARTIAL_READ_TOLERANCE,
    PartialReadError,
    _reject_partial_reads,
)
from uummannaq_ice.processing import BANDS


class FakeDataset:
    """Enough of an xarray Dataset for the guard."""

    def __init__(self, nodata_shares: dict[str, float], size: int = 1000):
        self.data_vars = {}
        for band, share in nodata_shares.items():
            arr = np.ones(size, dtype=np.float32)
            arr[: int(round(share * size))] = 0.0
            self.data_vars[band] = arr

    def __getitem__(self, band):
        return self.data_vars[band]


def uniform(share: float) -> FakeDataset:
    return FakeDataset(dict.fromkeys(BANDS, share))


# --- what must pass -------------------------------------------------------


def test_a_complete_scene_passes():
    _reject_partial_reads(uniform(0.0), "clean")


def test_a_real_swath_edge_passes():
    """Geometry hits every band at once. Measured cases: 5.6 and 7.9 percent."""
    for share in (0.056, 0.079, 0.20):
        _reject_partial_reads(uniform(share), f"edge-{share}")


def test_resampling_spread_between_resolutions_passes():
    """B11/B12 are 20 m and B01/B09/B10 are 60 m, so edges differ legitimately.

    This is the case the old one-point rule rejected, an estimated hundred or
    more real observations across the archive.
    """
    shares = dict.fromkeys(BANDS, 0.06)
    for coarse in ("swir16", "swir22"):
        shares[coarse] = 0.09
    for coarser in ("coastal", "nir09", "cirrus"):
        shares[coarser] = 0.14
    _reject_partial_reads(FakeDataset(shares), "resampled")


def test_a_scene_entirely_outside_the_swath_passes():
    """Everything is fill, so nothing disagrees. Emptiness is caught elsewhere."""
    _reject_partial_reads(uniform(1.0), "outside")


def test_too_few_bands_is_not_judged():
    _reject_partial_reads(FakeDataset({"green": 0.0, "nir": 1.0}), "partial-load")


# --- what must fail -------------------------------------------------------


def test_one_blank_band_in_a_good_scene_is_rejected():
    """The observed failure: green 100 percent fill, the other twelve at zero."""
    shares = dict.fromkeys(BANDS, 0.0)
    shares["green"] = 1.0
    with pytest.raises(PartialReadError, match="green"):
        _reject_partial_reads(FakeDataset(shares), "corrupt")


def test_the_message_names_the_downstream_symptom():
    shares = dict.fromkeys(BANDS, 0.0)
    shares["nir"] = 1.0
    with pytest.raises(PartialReadError, match="mean_ndwi_water"):
        _reject_partial_reads(FakeDataset(shares), "corrupt")


def test_a_nearly_blank_band_is_rejected():
    shares = dict.fromkeys(BANDS, 0.02)
    shares["swir16"] = BLANK_BAND_SHARE + 0.01
    with pytest.raises(PartialReadError):
        _reject_partial_reads(FakeDataset(shares), "corrupt")


def test_gross_disagreement_short_of_blank_is_rejected():
    """The +10.5 point case, well beyond any resampling difference."""
    shares = dict.fromkeys(BANDS, 0.05)
    shares["red"] = 0.05 + PARTIAL_READ_TOLERANCE + 0.05
    with pytest.raises(PartialReadError, match="red"):
        _reject_partial_reads(FakeDataset(shares), "corrupt")


def test_two_blank_bands_are_rejected():
    shares = dict.fromkeys(BANDS, 0.0)
    shares["green"] = 1.0
    shares["nir"] = 1.0
    with pytest.raises(PartialReadError):
        _reject_partial_reads(FakeDataset(shares), "corrupt")


# --- the constants themselves ---------------------------------------------


def test_the_blank_threshold_is_clear_of_real_swath_edges():
    """Measured real gaps were 5.6 and 7.9 percent, nowhere near the floor."""
    assert BLANK_BAND_SHARE > 0.9
    assert NOT_A_BLANK_SCENE >= 0.5


def test_the_spread_net_is_wide_enough_for_resampling():
    """The old 0.01 rejected legitimate 60 m band edges."""
    assert PARTIAL_READ_TOLERANCE >= 0.2


# --- Landmaske: georeferenziert statt gestreckt ---------------------------


def test_the_pooled_grid_scale_is_recovered_from_the_geobox():
    """The mask is derived at 10 m but applied on the 4x4 pooled 40 m grid.

    Getting this wrong is silent: the mask lands in the top-left corner, the
    land share reads 0.0001 instead of 0.05, and every number downstream still
    looks plausible.
    """
    from affine import Affine

    class Geobox:
        width = 1474
        height = 1812
        transform = Affine(10.0, 0.0, 500000.0, 0.0, -10.0, 7860000.0)

        class crs:  # noqa: N801 - mirrors the odc geobox attribute name
            @staticmethod
            def to_wkt():
                return "EPSG:32622"

    pooled_width = Geobox.width // 4
    pool = max(1, round(Geobox.width / pooled_width))
    assert pool == 4

    scaled = Geobox.transform * Affine.scale(pool, pool)
    assert scaled.a == pytest.approx(40.0)
    assert scaled.e == pytest.approx(-40.0)
    # the origin must not move
    assert scaled.c == pytest.approx(Geobox.transform.c)
    assert scaled.f == pytest.approx(Geobox.transform.f)
