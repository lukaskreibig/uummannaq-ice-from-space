"""A cube with a known ice fraction, through the classifier, out the other side.

Every documented failure in docs/investigation-log.md is a bug rather than a
misjudgement of physics: a sign error on the offset, a land mask reprojected
without scaling its transform, a denominator that counted cells which could
never reach the numerator, a bin one calendar day wide. None of them raised an
exception, and none of them would have survived a test that put a surface with a
known answer through the chain and read the number back.

That test did not exist. The suite covered configuration loading, threshold
derivation, partial reads, STAC handling and mask aggregation, so the pieces
were tested and the decision they exist to make was not.

Each case below builds a reflectance cube whose answer is fixed by construction
and asserts the fraction the pipeline reports. The cloud model is stubbed to
return clear everywhere, because what is under test is the ice and water rule
and not the checkpoint; the one case that does exercise the mask stubs it to
return cloud instead.

The reflectance values are not invented. They are the measured endmembers this
project derives elsewhere: fast ice sits at green 0.44 to 0.74 and near infrared
0.44 to 0.79, and open water at green 0.0745 and near infrared 0.024, from
scripts/endmember_separability.py and the July control scenes.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch
from PIL import Image

from uummannaq_ice.config import Thresholds
from uummannaq_ice.processing import (
    BANDS,
    CLOUD_CLASS_CLEAR,
    classify_tile,
    summarise_masks,
)

GREEN, NIR, SWIR = BANDS.index("green"), BANDS.index("nir"), BANDS.index("swir16")
SIZE = 64

# Measured endmembers, not invented ones.
FAST_ICE = {GREEN: 0.60, NIR: 0.62, SWIR: 0.06}
OPEN_WATER = {GREEN: 0.0745, NIR: 0.024, SWIR: 0.012}
# Ice in the mountain's shadow, and the spectral shape matters more than the
# dimming. A shadow is not switched off, it is lit by skylight, and skylight is
# Rayleigh scattered and therefore blue and green rich and near infrared poor.
# Green falls to about a third and the near infrared to about a tenth, which
# leaves NDSI intact, fails the absolute brightness gate, and lifts NDWI to
# roughly 0.49. That last part is the whole mechanism: it is what turns shadow
# into WATER rather than into nothing.
SHADOWED_ICE = {
    GREEN: FAST_ICE[GREEN] * 0.30,
    NIR: FAST_ICE[NIR] * 0.10,
    SWIR: FAST_ICE[SWIR] * 0.10,
}
# The same ice dimmed uniformly, which is what an unphysical shadow model gives.
# A ratio survives a uniform dimming, so NDWI does not move and the cell reaches
# no class at all. Kept as a case because it is the difference between a cell
# leaving the denominator and a cell being counted as open water.
UNIFORMLY_DIMMED_ICE = {band: value * 0.18 for band, value in FAST_ICE.items()}


class _AlwaysClear(torch.nn.Module):
    """A cloud head that calls every pixel clear."""

    def __init__(self, cls: int = CLOUD_CLASS_CLEAR) -> None:
        super().__init__()
        self.cls = cls

    def forward(self, batch: torch.Tensor) -> torch.Tensor:  # noqa: D102
        n, _, h, w = batch.shape
        logits = torch.zeros(n, 4, h, w)
        logits[:, self.cls] = 1.0
        return logits


def _cube(surfaces: list[tuple[dict[int, float], slice]]) -> torch.Tensor:
    """A 13 band cube, painted with one surface per row range."""
    cube = torch.zeros(len(BANDS), SIZE, SIZE, dtype=torch.float32)
    for surface, rows in surfaces:
        for band, value in surface.items():
            cube[band, rows, :] = value
    return cube


def _run(cube: torch.Tensor, model: torch.nn.Module | None = None) -> dict:
    land = np.zeros((SIZE, SIZE), dtype=bool)
    preview = Image.new("RGB", (512, 512))
    result = classify_tile(
        cube_small=cube,
        land_mask=land,
        thresholds=Thresholds(),
        model=model or _AlwaysClear(),
        device=torch.device("cpu"),
        rgb_preview=preview,
        baseline="04.00",
    )
    stats = summarise_masks(result.masks, result.ndsi, result.ndwi, 0.9)
    classified = stats["solid_px"] + stats["light_px"] + stats["water_px"]
    stats["ice_fraction"] = (
        (stats["solid_px"] + stats["light_px"]) / classified
        if classified
        else float("nan")
    )
    return stats


def test_a_frozen_fjord_reads_as_entirely_ice() -> None:
    stats = _run(_cube([(FAST_ICE, slice(None))]))
    assert stats["ice_fraction"] == pytest.approx(1.0)
    assert stats["water_px"] == 0


def test_open_water_reads_as_entirely_water() -> None:
    stats = _run(_cube([(OPEN_WATER, slice(None))]))
    assert stats["ice_fraction"] == pytest.approx(0.0)
    assert stats["solid_px"] == 0 and stats["light_px"] == 0


@pytest.mark.parametrize("share", [0.25, 0.5, 0.75])
def test_a_known_mixture_comes_back_as_that_mixture(share: float) -> None:
    """Half ice and half water must read one half, and so on.

    This is the assertion the pipeline never had. A sign error, a swapped
    threshold or a denominator counting the wrong cells all break it, and none
    of them raise.
    """
    cut = int(SIZE * share)
    stats = _run(_cube([(FAST_ICE, slice(0, cut)), (OPEN_WATER, slice(cut, SIZE))]))
    assert stats["ice_fraction"] == pytest.approx(share, abs=1e-6)


def test_cloud_removes_cells_from_both_numerator_and_denominator() -> None:
    """A clouded frozen fjord is not a fjord with less ice.

    The denominator defect in the investigation log was exactly this: cloud
    cells sat in the denominator and could never be in the numerator, so cloud
    read as ice loss. The published quantity divides by the classified cells, so
    a fully clouded frozen scene classifies almost nothing rather than reporting
    zero ice.

    Almost, and the remainder is the next test.
    """
    stats = _run(_cube([(FAST_ICE, slice(None))]), model=_AlwaysClear(cls=1))
    classified = stats["solid_px"] + stats["light_px"] + stats["water_px"]
    assert classified / (SIZE * SIZE) < 0.07
    assert stats["water_px"] == 0


def test_the_cloud_closing_erodes_exactly_one_cell_of_the_frame_edge() -> None:
    """A found edge effect, pinned rather than left to be rediscovered.

    compute_cloud_mask closes the mask with a 3 by 3 element, and binary_closing
    treats everything outside the array as not-cloud, so a mask that covers the
    whole frame comes back one cell short on every side. On a 64 square that is
    4 * 64 - 4 = 252 cells. It is small and it is not zero, and on the production
    grid it is the AOI boundary, which the land mask covers for most of its
    length. Worth knowing before someone reads a one-cell rim of ice on a fully
    overcast scene and calls it a classifier bug.
    """
    stats = _run(_cube([(FAST_ICE, slice(None))]), model=_AlwaysClear(cls=1))
    assert stats["cloud_px"] == SIZE * SIZE - (4 * SIZE - 4)
    assert stats["solid_px"] == 4 * SIZE - 4


def test_shadowed_ice_reads_as_water_and_the_reason_is_the_skylight() -> None:
    """The bug this project measures rather than fixes, pinned by a test.

    Shadowed ice keeps its NDSI, because a ratio survives a change of
    illumination, and fails the absolute brightness gate. That alone would put
    it in no class. What puts it in the WATER class is the colour of the light:
    a shadow is lit by Rayleigh scattered skylight, so the near infrared falls
    further than the green and NDWI rises to about 0.49, far above the 0.20
    threshold.

    That is wrong about the surface and correct about the code, and it is
    asserted here so a future change to the gate cannot alter it silently. If
    this starts failing, the dark-ice bias measured in docs/limitations.md has
    moved and every number derived from it needs recomputing.
    """
    stats = _run(_cube([(SHADOWED_ICE, slice(None))]))
    assert stats["ice_fraction"] == pytest.approx(0.0)
    assert stats["water_px"] == SIZE * SIZE


def test_uniformly_dimmed_ice_reaches_no_class_at_all() -> None:
    """The same surface, dimmed without changing colour, behaves differently.

    A uniform dimming leaves every ratio untouched, so NDWI stays where fast ice
    puts it, near zero, and the cell fails the brightness gate without passing
    the water test. It leaves the denominator instead of being counted as water.
    The difference between this case and the one above is the entire mechanism
    by which a mountain shadow becomes reported open water.
    """
    stats = _run(_cube([(UNIFORMLY_DIMMED_ICE, slice(None))]))
    assert stats["solid_px"] + stats["light_px"] + stats["water_px"] == 0


def test_the_index_denominator_floor_holds_off_near_zero_cells() -> None:
    """Two near-zero bands are noise, not a ratio, and must reach no class."""
    dark = {GREEN: 0.004, NIR: 0.004, SWIR: 0.004}
    stats = _run(_cube([(dark, slice(None))]))
    assert stats["solid_px"] + stats["light_px"] + stats["water_px"] == 0
