"""The figures on the results pages may not say more than the tables do.

Two pages draw from `scripts/build_site_data.py`, and both of them show several
instruments beside each other. That is exactly the shape in which a presentation
starts making claims the analysis never made: a merged series, a filled day
passed off as an observation, a verdict rounded to a side it never took.

So the guardrails are asserted here rather than trusted to the drawing code.
Every one of them is a thing the page must NOT be able to do.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "archive" / "reprocessed_2026"

spec = importlib.util.spec_from_file_location(
    "build_site_data", ROOT / "scripts" / "build_site_data.py"
)
assert spec and spec.loader
build_site_data = importlib.util.module_from_spec(spec)
sys.modules["build_site_data"] = build_site_data
spec.loader.exec_module(build_site_data)


@pytest.fixture(scope="module")
def sheet() -> dict:
    return build_site_data.contact_sheet()


@pytest.fixture(scope="module")
def curve() -> dict:
    return build_site_data.specification_curve()


class TestTheRecordStaysTheRecord:
    def test_no_day_merges_instruments(self, sheet: dict) -> None:
        """Sentinel-2 and Landsat are never averaged into one number.

        They agree well, 0.987 over 82 same-day pairs, and that is precisely the
        temptation: a merged series would look better and would be a quantity
        nobody validated. Each instrument keeps its own key and its own value.
        """
        for day in sheet["days"]:
            keys = set(day)
            assert "ice" not in keys and "combined" not in keys and "merged" not in keys
            if "landsat" in day and "s2" in day:
                assert day["landsat"] is not day["s2"]

    def test_a_filled_day_never_claims_a_measurement(self, sheet: dict) -> None:
        """`measured` is the satellite's number; `curve` is what the line plots.

        The published series is gap filled and smoothed, so most days carry a
        value no satellite produced. If those two ever collapsed into one field
        the sheet would show passes that never happened.
        """
        measured_days = {
            row["date"][:10]
            for row in csv.DictReader(
                (ARCHIVE / "daily_series.csv").open(encoding="utf-8")
            )
            if row["frac"]
        }
        for day in sheet["days"]:
            s2 = day.get("s2") or {}
            assert "measured" in s2 and "curve" in s2
            if s2["measured"] is not None:
                assert day["date"] in measured_days, (
                    f"{day['date']} claims a measurement it has not"
                )

    def test_the_counts_match_the_table(self, sheet: dict) -> None:
        counted = sum(
            1 for d in sheet["days"] if (d.get("s2") or {}).get("measured") is not None
        )
        assert counted == sheet["counts"]["s2"]


class TestTheDisagreementsKeepTheirShape:
    def test_a_contradiction_carries_its_condition(self, sheet: dict) -> None:
        """A thermal contradiction is only possible where the chain said open.

        Reporting the count without that condition is the classic way to make a
        bias sound larger than it is, so every contradicted day has to carry the
        flag that makes it one.
        """
        for day in sheet["days"]:
            thermal = day.get("thermal")
            if thermal and thermal["contradicted"]:
                assert thermal["chainSaysOpen"] is True

    def test_between_survives_as_an_answer(self, sheet: dict) -> None:
        """13 of 27 adjudicated days read as neither ice nor water.

        That is the majority verdict, and a page that rounded it to one side
        would turn the project's most careful finding into a false certainty.
        """
        verdicts = {d["sar"]["verdict"] for d in sheet["days"] if d.get("sar")}
        assert verdicts <= {"like fast ice", "like open water", "between"}
        assert "between" in verdicts

    def test_radar_position_is_not_clamped(self, sheet: dict) -> None:
        """The scale runs past both ends and the data has to keep saying so.

        0 is that season's open water and 1 its fast ice. Real days sit well
        outside, and clamping them into the interval would invent a certainty
        the backscatter does not carry.
        """
        positions = [d["sar"]["position"] for d in sheet["days"] if d.get("sar")]
        assert positions, "no adjudicated days survived into the sheet"
        assert any(p is not None and (p < 0 or p > 1) for p in positions)


class TestTheSpecificationCurveStaysAGrid:
    def test_every_level_appears_equally_often(self, curve: dict) -> None:
        """The 120 points are a full factorial, not a sample of opinions.

        This is why the page draws a curve with a choice matrix instead of
        reporting "116 of 120 show a decline": in a balanced grid that fraction
        is a property of the grid, not a vote among independent analyses.
        """
        points = curve["points"]
        for key, levels in curve["choices"].items():
            counts = {
                level: sum(1 for p in points if p[key] == level) for level in levels
            }
            assert len(set(counts.values())) == 1, f"{key} is unbalanced: {counts}"

    def test_the_published_choice_is_marked_exactly_once(self, curve: dict) -> None:
        assert sum(1 for p in curve["points"] if p["published"]) == 1
        assert curve["published"]["split"] == 2021
        assert curve["published"]["aggregate"] == "mean"

    def test_the_full_range_is_carried_including_the_negatives(
        self, curve: dict
    ) -> None:
        """Four combinations show no decline, and they stay in the figure.

        Dropping them would leave a curve that only ever points one way.
        """
        declines = [p["decline"] for p in curve["points"]]
        assert min(declines) < 0
        assert curve["summary"]["declining"] < curve["summary"]["n"]


class TestThePicturesMatchTheTable:
    """Every scene the record used has its picture, and no picture is an orphan.

    A thumbnail is committed rather than rendered in CI, which means it can
    outlive the row it belongs to. Both directions are checked, because a
    missing picture is a hole in the sheet and a stray one is a scene somebody
    dropped without noticing.
    """

    THUMBS = ROOT / "docs" / "assets" / "thumbs"

    def usable_ids(self) -> set[str]:
        with (ARCHIVE / "summary.csv").open(newline="", encoding="utf-8") as handle:
            return {
                row["tile_id"] for row in csv.DictReader(handle) if row["usable"] == "1"
            }

    def rendered_ids(self) -> set[str]:
        return {path.stem for path in self.THUMBS.glob("*.webp")}

    def test_every_usable_scene_has_a_thumbnail(self) -> None:
        missing = sorted(self.usable_ids() - self.rendered_ids())
        assert not missing, (
            f"{len(missing)} scenes without a picture, e.g. {missing[:3]}"
        )

    def test_no_thumbnail_outlives_its_scene(self) -> None:
        stray = sorted(self.rendered_ids() - self.usable_ids())
        assert not stray, f"{len(stray)} pictures with no row, e.g. {stray[:3]}"

    def test_the_day_panel_can_name_all_three_classes(self, sheet: dict) -> None:
        """Solid, light and water, not just the fraction that pools two of them.

        Added because the pictures demanded it: 17 April 2021 shows floes and
        open leads and still reports an ice fraction of 1.00, since the leads
        were classified as LIGHT ice and the fraction counts solid and light
        together. Water on that day is 0.0000. With only the fraction on screen
        that reads as a fault in the chain rather than as a class boundary.
        """
        with_scene = [d for d in sheet["days"] if d.get("scene")]
        assert with_scene
        for day in with_scene:
            scene = day["scene"]
            assert {"solid", "light", "water"} <= set(scene)
            total = scene["solid"] + scene["light"] + scene["water"]
            assert total <= 1.0001, f"{scene['id']} classes sum to {total}"


class TestAPictureIsAMeasurement:
    """The geometry of a quicklook is part of what it claims.

    Every thumbnail in the archive was once stretched sideways by a factor of
    1.54, because the AOI is 14.73 by 18.11 km, upright, and the renderer drew
    it into a landscape 320 by 256 box. Nothing in the picture announces that: a
    fjord has no straight lines to go crooked and an island has no shape a
    reader can check. It surfaced only when the classifier's own class rasters,
    on the pipeline's upright grid, were put beside the photographs.

    So the aspect ratio is asserted here rather than trusted to whoever next
    edits a constant.
    """

    THUMBS = {
        "sentinel-2": ROOT / "docs" / "assets" / "thumbs",
        "landsat": ROOT / "docs" / "assets" / "thumbs-landsat",
        "thermal": ROOT / "docs" / "assets" / "thumbs-thermal",
    }
    CLASSES = ROOT / "docs" / "assets" / "classes"

    # The fjord sits on a UTM zone boundary, and the same square of ground has a
    # different shape either side of it: 14.73 by 18.11 km in zone 22, aspect
    # 0.8136, and 15.79 by 18.94 km in zone 21, aspect 0.8334. 613 of the 617
    # scenes are 22WDD and four are 21WXU, and the pipeline's own class rasters
    # follow each scene's own zone.
    #
    # The quicklooks are all rendered to zone 22, the record's own projection,
    # so those four carry a 2.4 percent difference. That is a choice: a shape in
    # a projection is a property of the projection, and one reference geometry
    # across the whole sheet is worth more here than matching each scene's grid.
    # The tolerance is set to admit exactly that and nothing larger. The error
    # this test exists for was 54 percent.
    TOLERANCE = 0.03

    def aoi_aspect(self, epsg: int = 32622) -> float:
        import sys as _sys

        _sys.path.insert(0, str(ROOT / "src"))
        from rasterio.warp import transform_bounds

        from uummannaq_ice.config import DEFAULT_AOI

        ring = DEFAULT_AOI["coordinates"][0]
        xs = [point[0] for point in ring]
        ys = [point[1] for point in ring]
        left, bottom, right, top = transform_bounds(
            "EPSG:4326",
            f"EPSG:{epsg}",
            min(xs),
            min(ys),
            max(xs),
            max(ys),
            densify_pts=21,
        )
        return (right - left) / (top - bottom)

    @pytest.mark.parametrize("name", ["sentinel-2", "landsat", "thermal"])
    def test_the_quicklooks_are_not_stretched(self, name: str) -> None:
        from PIL import Image

        folder = self.THUMBS[name]
        pictures = sorted(folder.glob("*.webp"))
        if not pictures:
            pytest.skip(f"no {name} quicklooks rendered yet")
        want = self.aoi_aspect()
        for path in pictures[:40]:
            with Image.open(path) as image:
                got = image.width / image.height
            assert abs(got - want) < self.TOLERANCE, (
                f"{path.name} is {image.width}x{image.height}, aspect {got:.3f}, "
                f"but the AOI is {want:.3f}"
            )

    def test_the_class_raster_keeps_the_same_geometry(self) -> None:
        """The decision grid and the photograph have to describe one place."""
        from PIL import Image

        rasters = sorted(self.CLASSES.glob("*.png"))
        if not rasters:
            pytest.skip("no class rasters collected yet")
        # A class raster follows its own scene's zone, so either is correct here
        # and neither is a stretch.
        wanted = [self.aoi_aspect(32622), self.aoi_aspect(32621)]
        for path in rasters[:40]:
            with Image.open(path) as image:
                got = image.width / image.height
            assert any(abs(got - want) < self.TOLERANCE for want in wanted), (
                f"{path.name} aspect {got:.3f}, expected one of "
                + " or ".join(f"{w:.3f}" for w in wanted)
            )


class TestTheDecisionTravelsWithThePicture:
    CLASSES = ROOT / "docs" / "assets" / "classes"

    def usable_ids(self) -> set[str]:
        with (ARCHIVE / "summary.csv").open(newline="", encoding="utf-8") as handle:
            return {
                row["tile_id"] for row in csv.DictReader(handle) if row["usable"] == "1"
            }

    def test_every_usable_scene_carries_its_classification(self) -> None:
        """A photograph without the decision beside it is only half the method."""
        if not self.CLASSES.exists():
            pytest.skip("class rasters not collected yet")
        have = {path.stem for path in self.CLASSES.glob("*.png")}
        missing = sorted(self.usable_ids() - have)
        assert not missing, (
            f"{len(missing)} scenes without a class raster, {missing[:3]}"
        )

    def test_the_raster_counts_still_match_the_table(self) -> None:
        """The picture and the number have to come from the same run.

        A raster copied from a different archive run would be a picture of a
        different analysis shown beside numbers it did not produce. `land_px` is
        excluded on purpose: the table carries the static land mask, constant at
        8869 cells, while the export counts cells still labelled land after
        cloud and nodata took precedence. Two quantities, one name.
        """
        import json as _json

        index_path = self.CLASSES / "index.json"
        if not index_path.exists():
            pytest.skip("class rasters not collected yet")
        index = _json.loads(index_path.read_text())["scenes"]
        with (ARCHIVE / "summary.csv").open(newline="", encoding="utf-8") as handle:
            table = {
                r["tile_id"]: r for r in csv.DictReader(handle) if r["usable"] == "1"
            }
        pairs = {
            "solid_px": "ice_solid",
            "light_px": "ice_light",
            "water_px": "water",
            "cloud_px": "cloud",
        }
        assert set(table) == set(index), (
            "the class index and summary.csv disagree about which scenes exist"
        )
        for tile_id, row in table.items():
            counts = index[tile_id]["classes"]
            for column, name in pairs.items():
                assert int(row[column]) == counts.get(name, 0), (
                    f"{tile_id} {column}: table {row[column]}, "
                    f"raster {counts.get(name, 0)}"
                )

    def test_the_legend_is_one_palette_for_the_whole_record(self) -> None:
        """Seven colours, stated once, and the three the sheet talks about.

        The palette used to be repeated in 617 sidecar files. One copy is the
        legend; 617 copies were 3.3 MB of the same seven colours and a way for
        two of them to drift apart.
        """
        import json as _json

        index_path = self.CLASSES / "index.json"
        if not index_path.exists():
            pytest.skip("class rasters not collected yet")
        palette = _json.loads(index_path.read_text())["palette"]
        assert {"ice_solid", "ice_light", "water"} <= set(palette)
        assert palette["ice_solid"] != palette["ice_light"], (
            "solid and light ice share a colour, which is the one distinction "
            "the raster exists to make visible"
        )

    def test_no_instrument_borrows_another_ones_picture(self, sheet: dict) -> None:
        """Each layer addresses its own scene, and the thermal one says so.

        The thermal band is not a separate overpass. It is the infrared band of
        the very Landsat scene the optical row names, so a day can never have
        thermal imagery without Landsat imagery, and the page must not be able
        to imply otherwise by pointing the two rows at different scenes.
        """
        for day in sheet["days"]:
            thermal = day.get("thermal")
            if not thermal:
                continue
            assert thermal.get("scene"), f"{day['date']} thermal has no scene id"
            landsat = day.get("landsat")
            assert landsat, f"{day['date']} has thermal without Landsat"
            assert thermal["scene"] == landsat["scene"], (
                f"{day['date']} thermal names {thermal['scene']} "
                f"but Landsat names {landsat['scene']}"
            )


class TestEveryRowCanShowItsOwnPicture:
    """Each layer's imagery is complete, and none of it belongs to another layer.

    The gap this closes is the reason it needs guarding. 304 days carry a
    Landsat measurement and no Sentinel-2 scene, and the tempting fix was to let
    the Landsat picture fill the Sentinel-2 slot on those days. That is the
    merge `test_no_day_merges_instruments` forbids in the numbers, done in
    pictures instead, so the files are checked per layer and the page addresses
    them per layer.
    """

    LANDSAT = ROOT / "docs" / "assets" / "thumbs-landsat"
    THERMAL = ROOT / "docs" / "assets" / "thumbs-thermal"
    SAR = ROOT / "docs" / "assets" / "thumbs-sar"

    def test_every_landsat_day_has_its_own_quicklook(self, sheet: dict) -> None:
        if not self.LANDSAT.exists():
            pytest.skip("Landsat quicklooks not rendered yet")
        have = {path.stem for path in self.LANDSAT.glob("*.webp")}
        want = {d["landsat"]["scene"] for d in sheet["days"] if d.get("landsat")}
        missing = sorted(want - have)
        assert not missing, f"{len(missing)} Landsat days без picture, {missing[:3]}"

    def test_every_thermal_day_has_its_own_quicklook(self, sheet: dict) -> None:
        if not self.THERMAL.exists():
            pytest.skip("thermal quicklooks not rendered yet")
        have = {path.stem for path in self.THERMAL.glob("*.webp")}
        want = {d["thermal"]["scene"] for d in sheet["days"] if d.get("thermal")}
        missing = sorted(want - have)
        assert not missing, (
            f"{len(missing)} thermal days without picture, {missing[:3]}"
        )

    def test_radar_pictures_exist_exactly_where_one_pass_carries_the_verdict(
        self, sheet: dict
    ) -> None:
        """Both directions, because both failures are wrong in the same way.

        A missing file leaves a verdict the reader cannot look at. A file for a
        day whose verdict averaged several passes would show one overpass as
        though it were the measurement.
        """
        if not self.SAR.exists():
            pytest.skip("radar quicklooks not rendered yet")
        # The renderer works from the verdict table, which reaches four days
        # beyond the sheet's own window, so only the days the sheet can show are
        # this test's business.
        inside = {day["date"] for day in sheet["days"]}
        have = {path.stem for path in self.SAR.glob("*.webp")} & inside
        want = {d["date"] for d in sheet["days"] if (d.get("sar") or {}).get("scene")}
        assert not sorted(want - have), (
            f"verdicts without a picture: {sorted(want - have)[:3]}"
        )
        assert not sorted(have - want), (
            "radar pictures for days whose verdict came from more than one pass: "
            f"{sorted(have - want)[:3]}"
        )

    def test_the_page_addresses_each_picture_from_its_own_layer(self) -> None:
        """The folders appear in the file exactly once each, and in order.

        A cheap structural check, but it is the one that would catch somebody
        pointing the Landsat row at `thumbs/` during a hurried edit.
        """
        source = (ROOT / "docs" / "assets" / "js" / "contact-sheet.js").read_text()
        # Counted with the `../assets/` prefix that precedes them in the
        # template literals, because `thumbs/` is also a prefix of
        # `thumbs-landsat/` and a bare count would double up.
        for folder in (
            "thumbs/",
            "classes/",
            "thumbs-landsat/",
            "thumbs-thermal/",
            "thumbs-sar/",
        ):
            seen = source.count(f"../assets/{folder}")
            assert seen == 1, (
                f"{folder} is addressed {seen} times in the page, expected exactly once"
            )


class TestTheViewerIsTheReadingContainer:
    """The pictures live in a dialog, and there are reasons it cannot regress.

    The version this replaced put five upright quicklooks in the cursor-following
    card: 134 px each, 1917 px of scrolling inside a 930 px box, and the reader
    had to pin the card before seeing more than one of them. The container was
    wrong for the task, so the task moved to a container built for it.
    """

    SOURCE = ROOT / "docs" / "assets" / "js" / "contact-sheet.js"
    STYLES = ROOT / "docs" / "assets" / "css" / "results.css"

    def test_the_viewer_is_a_real_dialog(self) -> None:
        """A div would mean writing focus trapping and inertness by hand."""
        source = self.SOURCE.read_text()
        assert 'createElement("dialog")' in source
        assert "showModal" in source

    def test_pinning_is_gone(self) -> None:
        """No state, no attribute, no styling, and no instruction to pin.

        Pinning existed only to keep the wrong container open long enough to
        read. Leaving any of it behind would leave two ways to open a day and
        one of them worse.
        """
        source = self.SOURCE.read_text()
        styles = self.STYLES.read_text()
        page = (ROOT / "docs" / "contact-sheet.md").read_text()
        for needle in ("data-pinned", "dataset.pinned", "pin-hint"):
            assert needle not in source, f"{needle} survives in the page script"
            assert needle not in styles, f"{needle} survives in the stylesheet"
        assert "pins it" not in page

    def test_every_way_out_runs_the_same_teardown(self) -> None:
        """Escape, the backdrop and the button all call closeViewer().

        Measured on the real page: `viewer.close()` runs, `viewer.open` goes
        false, and no `close` event is raised. Cleanup hung on that event left
        the cell marked as open with the dialog already gone, so the teardown is
        called directly and the event listener is only a fallback.
        """
        source = self.SOURCE.read_text()
        assert source.count("function closeViewer()") == 1
        # once as the button handler, once from the backdrop, once from Escape,
        # once as the fallback listener, plus the definition
        assert source.count("closeViewer") >= 5

    def test_escape_is_caught_where_focus_cannot_move_it(self) -> None:
        """On the document, in capture, and only while the viewer is open.

        A listener on the dialog fires only while focus is inside it, which
        stops being true the moment a reader clicks a picture. The `viewer.open`
        guard is what leaves Escape to Material's search box the rest of the
        time.
        """
        source = self.SOURCE.read_text()
        start = source.index('document.addEventListener(\n      "keydown"')
        block = source[start : source.index("\n    );", start) + 7]
        assert "!viewer.open" in block, "Escape is not guarded on the viewer being open"
        assert 'event.key !== "Escape"' in block
        assert block.rstrip().endswith("true\n    );"), "the listener is not in capture"

    def test_the_viewer_can_be_walked_day_by_day(self) -> None:
        """Aim is not a requirement, because a cell is four pixels wide.

        Measured at 768 by 1024, a tablet in portrait: a sheet cell is 4.16 by
        17 pixels against a 44 pixel minimum target. Widening it would mean
        three thousand pixels of sideways scrolling through ten seasons, which
        costs the overview a contact sheet exists to give. So the viewer steps
        instead, by button and by arrow key, and a tap only has to land nearby.
        """
        source = self.SOURCE.read_text()
        assert "function stepTo(" in source
        assert "ArrowLeft" in source and "ArrowRight" in source
        assert "viewer-step" in source
        styles = self.STYLES.read_text()
        block = styles[styles.index(".md-typeset .viewer-step,") :][:400]
        assert "min-width: 44px" in block and "min-height: 44px" in block

    def test_nothing_a_tablet_needs_sits_behind_a_hover(self) -> None:
        """Both pages, because both were broken and in different ways.

        The sheet filled a docked panel from `pointerenter`, which a tablet does
        fire, one frame before the tap that covers it: 2153 pixels of duplicate
        page on the way to a dialog. And the specification curve offered
        `mouseenter` and nothing else, so a device with no hover could not read
        one specification on a page that promises hovering reads them out.
        """
        sheet = self.SOURCE.read_text()
        assert "(hover: none)" in sheet, "the sheet does not ask about hover at all"
        assert "if (coarse()) return;" in sheet

        curve = (ROOT / "docs" / "assets" / "js" / "specification-curve.js").read_text()
        assert 'hit.addEventListener("click"' in curve, "a column cannot be tapped"
        assert "function stepSpec(" in curve

        styles = self.STYLES.read_text()
        assert "@media (hover: none)" in styles
        touch = styles[styles.index("@media (hover: none)") :][:800]
        assert ".day-panel { display: none; }" in touch, (
            "the docked panel, which only hovering can fill, is still in the flow"
        )
