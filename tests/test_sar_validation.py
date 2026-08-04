"""Tests for the Sentinel-1 cross-check.

These cover the parts that decide whether the answer means anything, rather than
the parts that fetch bytes. Two of them exist because the analysis would have
produced a clean, publishable and worthless number without them.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location(
    "validate_sar", ROOT / "scripts" / "validate_sar.py"
)
assert _spec and _spec.loader
validate_sar = importlib.util.module_from_spec(_spec)
# Register before executing: @dataclass resolves its annotations through
# sys.modules[cls.__module__], which does not exist yet for a module loaded
# straight from a path.
sys.modules["validate_sar"] = validate_sar
_spec.loader.exec_module(validate_sar)

ROLE_ICE = validate_sar.ROLE_ICE
ROLE_SUSPECT = validate_sar.ROLE_SUSPECT
ROLE_WATER = validate_sar.ROLE_WATER


def _candidate(role: str, day: date) -> Any:
    return validate_sar.Candidate(
        role=role, day=day, tile="22WDD", ice_clear=0.0, cloud=0.0, clear=0.9
    )


def _feature(scene_id: str) -> dict[str, object]:
    return {"id": scene_id, "properties": {}, "assets": {}}


class TestRoleCollisions:
    """A scene may serve one role. This is the difference between a test and a coincidence."""

    def test_scene_claimed_by_two_roles_is_withdrawn_from_both(self) -> None:
        # Radar passes here every two to four days, so a suspect day and a
        # neighbouring anchor routinely resolve to the same acquisition. Keeping
        # it for either arm would put the identical measurement on both sides of
        # the comparison, and the permutation test would still return a p value.
        shared = _feature("S1_SHARED")
        available = {date(2021, 3, 5): [shared]}
        candidates = [
            _candidate(ROLE_SUSPECT, date(2021, 3, 5)),
            _candidate(ROLE_ICE, date(2021, 3, 5)),
        ]

        accepted, unmatched = validate_sar.assign_scenes(candidates, available)

        assert accepted == []
        assert len(unmatched) == 2
        assert all("also claimed by" in reason for _, reason in unmatched)

    def test_two_candidates_of_the_same_role_keep_the_closer_one(self) -> None:
        # Same role on one scene is a duplicate, not a collision: it cannot put
        # the measurement on both sides. Keep the closest in time, drop the rest.
        shared = _feature("S1_SHARED")
        available = {date(2021, 3, 5): [shared]}
        candidates = [
            _candidate(ROLE_ICE, date(2021, 3, 5)),  # offset 0
            _candidate(ROLE_ICE, date(2021, 3, 6)),  # offset -1
        ]

        accepted, unmatched = validate_sar.assign_scenes(candidates, available)

        assert len(accepted) == 1
        assert accepted[0][0].day == date(2021, 3, 5)
        assert len(unmatched) == 1
        assert "already used by the same role" in unmatched[0][1]

    def test_a_candidate_without_a_nearby_scene_is_reported_not_dropped(self) -> None:
        accepted, unmatched = validate_sar.assign_scenes(
            [_candidate(ROLE_SUSPECT, date(2021, 3, 5))],
            {date(2021, 3, 20): [_feature("S1_FAR")]},
        )

        assert accepted == []
        assert "no RTC scene within" in unmatched[0][1]

    def test_the_nearest_scene_wins_over_a_further_one(self) -> None:
        available = {
            date(2021, 3, 4): [_feature("S1_DAY_BEFORE")],
            date(2021, 3, 5): [_feature("S1_SAME_DAY")],
        }
        accepted, _ = validate_sar.assign_scenes(
            [_candidate(ROLE_SUSPECT, date(2021, 3, 5))], available
        )

        assert accepted[0][1]["id"] == "S1_SAME_DAY"
        assert accepted[0][2] == 0


class TestCandidateSelection:
    def _archive(self) -> pd.DataFrame:
        rows = [
            # a suspect: February, clear, almost no ice
            ("S2B_22WDD_x", "20210220T150000", 0.01, 0.0, 0.0, 0.004, 0.09, 0.0),
            # an ice anchor: February, clear, full ice
            ("S2B_22WDD_y", "20210225T150000", 0.90, 0.01, 0.0, 0.0, 0.09, 0.0),
            # a water anchor: September, clear, no ice
            ("S2B_22WDD_z", "20210915T150000", 0.0, 0.0, 0.90, 0.0, 0.09, 0.0),
            # the same shape as the suspect but from a tile on another continent
            ("S2B_30QUL_q", "20210221T150000", 0.01, 0.0, 0.0, 0.004, 0.09, 0.0),
        ]
        return pd.DataFrame(
            rows,
            columns=[
                "tile_id",
                "timestamp",
                "solid_pct",
                "light_pct",
                "water_pct",
                "cloud_pct",
                "land_pct",
                "nodata_pct",
            ],
        )

    def test_scenes_from_other_continents_never_enter_any_arm(self) -> None:
        # The catalogue has returned scenes from West Africa and the North
        # Pacific for this AOI, because their footprints span most of a
        # hemisphere. One of them sits in the published archive looking exactly
        # like a suspect day. It says nothing about Uummannaq.
        candidates = validate_sar.build_candidates(_prepare(self._archive()))

        assert all(
            candidate.tile in validate_sar.GREENLAND_TILES for candidate in candidates
        )
        assert {candidate.role for candidate in candidates} == {
            ROLE_SUSPECT,
            ROLE_ICE,
            ROLE_WATER,
        }

    def test_each_role_picks_the_row_it_is_meant_to(self) -> None:
        candidates = validate_sar.build_candidates(_prepare(self._archive()))
        by_role = {candidate.role: candidate for candidate in candidates}

        assert by_role[ROLE_SUSPECT].day == date(2021, 2, 20)
        assert by_role[ROLE_ICE].day == date(2021, 2, 25)
        assert by_role[ROLE_WATER].day == date(2021, 9, 15)


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    """read_archive's derivations, applied to an in-memory frame."""

    frame = frame.copy()
    frame["day"] = pd.to_datetime(
        frame["timestamp"].astype(str).str[:8], format="%Y%m%d"
    ).dt.date
    frame["month"] = pd.to_datetime(frame["day"]).dt.month
    frame["year"] = pd.to_datetime(frame["day"]).dt.year
    frame["tile"] = frame["tile_id"].str.extract(r"_(\d{2}[A-Z]{3})_")
    frame["clear"] = 1.0 - frame["cloud_pct"] - frame["land_pct"] - frame["nodata_pct"]
    frame["ice_clear"] = np.where(
        frame["clear"] > 0,
        (frame["solid_pct"] + frame["light_pct"]) / frame["clear"],
        np.nan,
    )
    return frame


class TestStatistics:
    def test_identical_groups_do_not_separate(self) -> None:
        values = np.array([-18.0, -17.5, -19.0, -18.2, -17.8])
        assert validate_sar.permutation_p(values, values.copy()) > 0.5

    def test_well_separated_groups_do(self) -> None:
        ice = np.array([-17.0, -16.5, -17.5, -16.8, -17.2])
        water = np.array([-23.0, -22.5, -23.5, -22.8, -23.2])
        assert validate_sar.permutation_p(ice, water) < 0.05

    def test_the_p_value_is_reproducible(self) -> None:
        # Fixed seed, so a reviewer re-running this gets the same number.
        left = np.array([-17.0, -16.0, -18.0, -19.0])
        right = np.array([-22.0, -23.0, -21.0, -24.0])
        assert validate_sar.permutation_p(left, right) == validate_sar.permutation_p(
            left, right
        )

    def test_a_finite_run_never_reports_p_equal_to_zero(self) -> None:
        left = np.array([100.0, 101.0, 102.0, 103.0])
        right = np.array([-100.0, -101.0, -102.0, -103.0])
        assert validate_sar.permutation_p(left, right, draws=200) > 0.0

    def test_auc_is_one_when_every_positive_outranks_every_negative(self) -> None:
        assert (
            validate_sar.auc(np.array([1.0, 2.0, 3.0]), np.array([-1.0, -2.0])) == 1.0
        )

    def test_auc_is_a_half_for_identical_distributions(self) -> None:
        values = np.array([1.0, 2.0, 3.0])
        assert validate_sar.auc(values, values.copy()) == pytest.approx(0.5)

    def test_the_bootstrap_interval_brackets_the_median(self) -> None:
        values = np.array([-18.0, -17.0, -19.0, -18.5, -17.5, -18.2])
        low, high = validate_sar.bootstrap_ci(values, draws=500)
        assert low <= float(np.median(values)) <= high


class TestAnchorThinning:
    def test_capping_keeps_every_year_represented(self) -> None:
        frame = pd.DataFrame(
            {
                "year": [2020] * 20 + [2021] * 20,
                "day": [date(2020, 3, 1)] * 20 + [date(2021, 3, 1)] * 20,
            }
        )
        capped = validate_sar._cap_per_year(frame, cap=6)

        assert set(capped["year"]) == {2020, 2021}
        assert len(capped) <= 8

    def test_capping_is_deterministic(self) -> None:
        # A seeded sample would make the chosen scenes depend on a random state,
        # and a reviewer re-running this has to read the same acquisitions.
        frame = pd.DataFrame(
            {"year": [2020] * 10, "day": [date(2020, 3, day) for day in range(1, 11)]}
        )
        first = validate_sar._cap_per_year(frame, cap=4)
        second = validate_sar._cap_per_year(frame, cap=4)
        assert list(first["day"]) == list(second["day"])

    def test_a_pool_below_the_cap_is_untouched(self) -> None:
        frame = pd.DataFrame(
            {"year": [2020, 2020], "day": [date(2020, 3, 1), date(2020, 3, 2)]}
        )
        assert len(validate_sar._cap_per_year(frame, cap=10)) == 2
