import numpy as np

from uummannaq_ice.processing import summarise_masks


def test_summarise_masks_counts_and_percentages():
    shape = (4, 4)
    ice_solid = np.zeros(shape, dtype=bool)
    ice_light = np.zeros(shape, dtype=bool)
    water = np.zeros(shape, dtype=bool)
    cloud = np.zeros(shape, dtype=bool)
    land = np.zeros(shape, dtype=bool)
    nodata = np.zeros(shape, dtype=bool)

    ice_solid[:2, :2] = True
    ice_light[2:, :2] = True
    water[:2, 2:] = True
    cloud[2:, 2:] = True
    land[0, 0] = True
    nodata[3, 3] = True

    masks = {
        "ice_solid": ice_solid,
        "ice_light": ice_light,
        "water": water,
        "cloud": cloud,
        "land": land,
        "nodata": nodata,
    }

    ndsi = np.full(shape, 0.6)
    ndwi = np.full(shape, 0.1)

    stats = summarise_masks(masks, ndsi, ndwi, nodata_threshold=0.2)

    assert stats["solid_px"] == 4
    assert stats["light_px"] == 4
    assert stats["water_px"] == 4
    assert stats["cloud_px"] == 4
    assert stats["land_px"] == 1
    assert stats["nodata_px"] == 1
    assert stats["unknown_px"] == 2
    assert stats["solid_pct"] == 0.25
    assert stats["light_pct"] == 0.25
    assert stats["water_pct"] == 0.25
    assert stats["cloud_pct"] == 0.25
    assert stats["edge_gap"] == 0
