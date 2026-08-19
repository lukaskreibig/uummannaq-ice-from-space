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
