"""Tests for the STAC search guards.

These cover two defects that reached the published record: scenes from entirely
different parts of the world were accepted, and the winner among overlapping
scenes on one day depended on catalogue response order.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from uummannaq_ice import stac

# The real AOI: a rectangle over Uummannaq Bay, about 14.3 by 17.8 km.
UUMMANNAQ_AOI = {
    "type": "Polygon",
    "coordinates": [
        [
            [-52.336121, 70.788206],
            [-51.945564, 70.788206],
            [-51.945564, 70.628226],
            [-52.336121, 70.628226],
            [-52.336121, 70.788206],
        ]
    ],
}
AOI_BBOX = (-52.336121, 70.628226, -51.945564, 70.788206)


class FakeItem:
    """Minimal stand-in for a pystac Item."""

    def __init__(self, item_id, bbox, when="2026-03-01T14:00:00+00:00"):
        self.id = item_id
        self.bbox = bbox
        self.datetime = datetime.fromisoformat(when).astimezone(timezone.utc)
        self.assets = {}


def test_bbox_of_reads_the_polygon():
    assert stac.bbox_of(UUMMANNAQ_AOI) == pytest.approx(AOI_BBOX)


def test_bbox_of_returns_none_without_coordinates():
    assert stac.bbox_of({"type": "Polygon", "coordinates": []}) is None


def test_full_overlap_scores_one():
    covering = (-53.0, 70.0, -51.0, 71.5)
    assert stac.aoi_coverage(covering, AOI_BBOX) == pytest.approx(1.0)


def test_west_africa_tile_scores_zero():
    """30QUL reached the published record and reported an ice fraction of 0.0."""
    assert stac.aoi_coverage((-9.5, 17.0, -8.4, 18.0), AOI_BBOX) == 0.0


def test_north_pacific_tile_scores_zero():
    """60UXB, the second contaminating scene."""
    assert stac.aoi_coverage((176.0, 55.0, 178.0, 56.0), AOI_BBOX) == 0.0


def test_missing_bbox_scores_zero():
    assert stac.aoi_coverage(None, AOI_BBOX) == 0.0
    assert stac.aoi_coverage((), AOI_BBOX) == 0.0


def test_partial_overlap_is_proportional():
    """Half the AOI in longitude, all of it in latitude."""
    half = (-52.336121, 70.0, -52.140843, 71.0)
    assert stac.aoi_coverage(half, AOI_BBOX) == pytest.approx(0.5, abs=0.01)


def test_sort_key_prefers_better_coverage():
    good = FakeItem("S2B_22WDD_20260301_0_L1C", (-53.0, 70.0, -51.0, 71.5))
    edge = FakeItem("S2A_21WXU_20260301_0_L1C", (-52.40, 70.0, -52.30, 71.0))
    assert stac._sort_key(good, AOI_BBOX) < stac._sort_key(edge, AOI_BBOX)


def test_sort_key_is_stable_when_coverage_ties():
    """Equal coverage must not leave the winner to response order."""
    box = (-53.0, 70.0, -51.0, 71.5)
    a = FakeItem("S2A_22WDD_20260301_0_L1C", box)
    b = FakeItem("S2B_22WDD_20260301_0_L1C", box)
    assert stac._sort_key(a, AOI_BBOX) < stac._sort_key(b, AOI_BBOX)
    # and the order of the inputs does not change the winner
    assert min([a, b], key=lambda i: stac._sort_key(i, AOI_BBOX)).id == a.id
    assert min([b, a], key=lambda i: stac._sort_key(i, AOI_BBOX)).id == a.id


def test_sort_key_without_aoi_falls_back_to_id():
    a = FakeItem("aaa", None)
    b = FakeItem("bbb", None)
    assert stac._sort_key(a, None) < stac._sort_key(b, None)


def _run_fetch(monkeypatch, items):
    class FakeSearch:
        def items(self):
            return iter(items)

    class FakeClient:
        @staticmethod
        def open(url):
            return FakeClient()

        def search(self, **kwargs):
            return FakeSearch()

    monkeypatch.setattr(stac, "Client", FakeClient)

    class Cfg:
        stac_url = "https://example.invalid"
        collection = "sentinel-2-l1c"
        start_date = datetime(2026, 3, 1).date()
        end_date = datetime(2026, 3, 2).date()
        date_range = "2026-03-01/2026-03-02"
        search_aoi = UUMMANNAQ_AOI
        max_tiles = None

    return stac.fetch_tiles(Cfg())


def test_fetch_tiles_drops_foreign_scenes(monkeypatch):
    good = FakeItem("S2B_22WDD_20260301_0_L1C", (-53.0, 70.0, -51.0, 71.5))
    africa = FakeItem("S2B_30QUL_20260301_1_L1C", (-9.5, 17.0, -8.4, 18.0))
    result = _run_fetch(monkeypatch, [good, africa])
    assert [i.id for i in result] == [good.id]


def test_fetch_tiles_is_order_independent(monkeypatch):
    """The same day with two overlapping tiles must yield the same winner."""
    wide = FakeItem("S2B_22WDD_20260301_0_L1C", (-53.0, 70.0, -51.0, 71.5))
    narrow = FakeItem("S2A_21WXU_20260301_0_L1C", (-52.40, 70.5, -52.20, 70.9))
    first = _run_fetch(monkeypatch, [wide, narrow])
    second = _run_fetch(monkeypatch, [narrow, wide])
    assert [i.id for i in first] == [i.id for i in second] == [wide.id]


def test_fetch_tiles_keeps_one_scene_per_day(monkeypatch):
    day_one = FakeItem("A", (-53.0, 70.0, -51.0, 71.5), "2026-03-01T14:00:00+00:00")
    day_two = FakeItem("B", (-53.0, 70.0, -51.0, 71.5), "2026-03-02T14:00:00+00:00")
    result = _run_fetch(monkeypatch, [day_one, day_two])
    assert len(result) == 2


def test_fetch_tiles_returns_empty_when_all_rejected(monkeypatch):
    africa = FakeItem("S2B_30QUL_20260301_1_L1C", (-9.5, 17.0, -8.4, 18.0))
    assert _run_fetch(monkeypatch, [africa]) == []


# --- Fehler, die erst der Probelauf gegen den echten Katalog zeigte ---------


def test_a_global_bounding_box_is_not_a_footprint():
    """60UXB crosses the antimeridian, so its bbox is [-180, .., 180, ..].

    That covers every AOI on the planet perfectly, so the coverage floor scored
    it 1.0 and waved it through. Measured against the live catalogue: lon span
    360.0 degrees, lat span 38.9.
    """
    assert not stac.is_plausible_footprint((-180, 51.06, 180, 90))
    assert stac.aoi_coverage((-180, 51.06, 180, 90), AOI_BBOX) == pytest.approx(1.0)


def test_real_granule_footprints_are_accepted():
    """Both live neighbours, measured: about 3.2 by 1.0 degrees."""
    assert stac.is_plausible_footprint((-54.354, 70.133, -51.185, 71.133))
    assert stac.is_plausible_footprint((-53.780, 70.199, -50.729, 71.199))


def test_a_missing_bbox_is_not_plausible():
    assert not stac.is_plausible_footprint(None)
    assert not stac.is_plausible_footprint(())


def test_fetch_tiles_drops_the_antimeridian_tile(monkeypatch):
    good = FakeItem("S2B_22WDD_20260301_0_L1C", (-53.0, 70.0, -51.0, 71.5))
    pacific = FakeItem("S2A_60UXB_20260301_0_L1C", (-180, 51.06, 180, 90))
    assert [i.id for i in _run_fetch(monkeypatch, [good, pacific])] == [good.id]


# --- Kachelwahl ------------------------------------------------------------


def test_utm_zone_for_uummannaq_is_22():
    """52.1 degrees west. 22WDD is in its own zone, 21WXU is not."""
    assert stac.utm_zone_for((AOI_BBOX[0] + AOI_BBOX[2]) / 2) == 22


def test_utm_zone_edges():
    assert stac.utm_zone_for(-180.0) == 1
    assert stac.utm_zone_for(0.0) == 31
    assert stac.utm_zone_for(179.9) == 60


def test_mgrs_zone_is_read_off_the_item_id():
    assert stac.mgrs_zone_of("S2B_22WDD_20230818_0_L1C") == 22
    assert stac.mgrs_zone_of("S2A_21WXU_20190416_0_L1C") == 21
    assert stac.mgrs_zone_of("nonsense") is None
    assert stac.mgrs_zone_of("") is None


def test_the_home_zone_wins_when_coverage_ties():
    """Both neighbours cover the AOI fully, so coverage alone cannot decide.

    Without this the alphabet decided and 21WXU won almost every day, while the
    published archive is 81 percent 22WDD.
    """
    box = (-53.0, 70.0, -51.0, 71.5)
    home = FakeItem("S2B_22WDD_20260301_0_L1C", box)
    away = FakeItem("S2A_21WXU_20260301_0_L1C", box)
    assert stac._sort_key(home, AOI_BBOX, 22) < stac._sort_key(away, AOI_BBOX, 22)
    # and the alphabet would have chosen the other way round
    assert stac._sort_key(away, AOI_BBOX, None) < stac._sort_key(home, AOI_BBOX, None)


def test_coverage_still_outranks_the_home_zone():
    """A home-zone tile that barely clips the AOI must not beat a full one."""
    full_away = FakeItem("S2A_21WXU_20260301_0_L1C", (-53.0, 70.0, -51.0, 71.5))
    sliver_home = FakeItem("S2B_22WDD_20260301_0_L1C", (-52.34, 70.7, -52.30, 70.75))
    assert stac._sort_key(full_away, AOI_BBOX, 22) < stac._sort_key(
        sliver_home, AOI_BBOX, 22
    )


def test_fetch_tiles_picks_the_home_zone_tile(monkeypatch):
    box = (-53.0, 70.0, -51.0, 71.5)
    home = FakeItem("S2B_22WDD_20260301_0_L1C", box)
    away = FakeItem("S2A_21WXU_20260301_0_L1C", box)
    for order in ([home, away], [away, home]):
        assert [i.id for i in _run_fetch(monkeypatch, order)] == [home.id]
