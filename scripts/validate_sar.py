#!/usr/bin/env python3
"""Ask Sentinel-1 whether the fjord was frozen on the days the optical series says it was not.

    python3 scripts/validate_sar.py --dry-run          # show the sample, touch no network
    python3 scripts/validate_sar.py                    # measure and analyse
    python3 scripts/validate_sar.py --analyse-only     # re-analyse an existing result file

## The question, and why it is this question

An earlier framing of this check aimed at cloudy days, on the grounds that the
reported ice fraction correlates with detected cloud at r = -0.42. That
correlation turned out to be an artefact of the whole-grid denominator, where a
cell classified as cloud can never also be counted as ice, so the negative sign
is forced by construction. On the reprocessed archive the whole-grid correlation
is -0.609 across all 1103 scenes, while on the clear-sky denominator over the
scenes that clear the visibility gate it is -0.157. See `docs/limitations.md`.

What survives is sharper. Of the February and March scenes that pass the 30
percent visibility gate, a couple of dozen report almost no ice on the clear-sky
denominator **while the sky was nearly clear**. No change of denominator explains
those, and this fjord is frozen in February and March with near certainty. Those
are the days this script tests.

## The design, and the two ways it could have produced a clean but worthless answer

**Roles must not share a scene.** Radar passes here every two to four days, so a
suspect day and a nearby control day can easily resolve to the same acquisition.
The test would then have the same measurement in both arms, run without error and
produce a tidy p value that means nothing. Every scene is therefore assigned to
at most one role, and any scene wanted by two roles is dropped from both.

**A misaligned land mask is invisible in the answer.** Shifting the mask 1000 m
against a real scene moves the fjord median by 0.17 dB while the land contrast
collapses from 5.75 dB to 1.99. The number stays plausible and nothing raises.
Every scene therefore carries its land contrast, and the geometry check below
reads it across the whole set. Not per scene: a correctly aligned February
anchor came in at 2.64 dB because dry snow on rock is radar dark in midwinter,
so the innocent winter range and the misalignment range overlap and no
per-scene threshold can tell them apart.

## What has to be true before the result means anything

The instrument test runs first and can end the whole thing. If confirmed ice
anchors and confirmed open-water anchors do not separate in gamma0, then radar
does not answer this question at this fjord, and the honest output is that null
result rather than a comparison against a scale that does not exist.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from uummannaq_ice.sar import (  # noqa: E402
    SAR_CSV_HEADER,
    SasToken,
    SceneStats,
    load_landmask,
    measure_scene,
    scenes_by_date,
    search_scenes,
)

LOGGER = logging.getLogger("validate_sar")

DEFAULT_ARCHIVE = Path("archive/reprocessed_2026/summary.csv")
DEFAULT_OUTPUT = Path("out/archive/sar_validation.csv")

# Uummannaq sits on the boundary of two MGRS tiles and the archive also contains
# a handful of scenes from entirely different parts of the planet, which the
# catalogue returned because their footprints span most of a hemisphere. Those
# say nothing about this fjord and must not enter any arm of the test.
GREENLAND_TILES = frozenset({"21WXU", "22WDD"})

# February and March. The physical claim the whole test rests on is that this
# fjord is frozen then, and it is much safer for these two months than for the
# shoulder of the analysis window.
FROZEN_MONTHS = (2, 3)
# June and July. This used to be August and September, which was right for the
# published archive because that covered the whole calendar. The reprocess runs
# 1 February to 15 July, so those months no longer exist in it and the water
# anchor pool came out empty.
#
# The replacement is better rather than merely available. June and July are
# unambiguous here: over the reprocessed archive the June median clear-sky ice
# fraction is 0.001 and July 0.002, with 113 scenes across all ten seasons
# clearing the anchor thresholds. And they sit four months from the February
# suspects rather than six, which narrows the seasonal confounder in sea state
# and wind climate that docs/sar-validation.md has to declare either way.
OPEN_MONTHS = (6, 7)

# The optical pipeline's own usability gate.
MIN_CLEAR_SHARE = 0.30
# Anchors have to be beyond argument, so they are held to more than the gate.
ANCHOR_MIN_CLEAR = 0.70
SUSPECT_MAX_ICE = 0.15
ICE_ANCHOR_MIN = 0.85
WATER_ANCHOR_MAX = 0.05

# How far a radar acquisition may sit from the optical one and still be called
# the same observation. Ice cover on a fjord does not change overnight in
# February, but it is not nothing either, so the offset is recorded per pair.
MATCH_WINDOW_DAYS = 1

# Anchors are plentiful and scenes cost time, so the pools are capped. The cap
# is applied per year so no single winter dominates either arm.
MAX_ANCHORS_PER_ROLE = 36

# The global alignment floor. Per-scene contrast cannot separate a shifted mask
# from radar dark winter land, so this is checked once over the whole set, where
# a georeferencing error would drag every scene down together. The 1000 m shift
# test produced 1.99 dB; correct alignment produced 5.75 dB in March.
MIN_GLOBAL_CONTRAST_DB = 3.0

ROLE_SUSPECT = "suspect"
ROLE_ICE = "ice_anchor"
ROLE_WATER = "water_anchor"

PAIR_HEADER = (
    "role",
    "optical_date",
    "optical_tile",
    "optical_ice_clear",
    "optical_cloud",
    "optical_clear",
    "scene_id",
    "offset_days",
)


@dataclass(frozen=True, slots=True)
class Candidate:
    """One optical observation put forward for a role in the test."""

    role: str
    day: date
    tile: str
    ice_clear: float
    cloud: float
    clear: float


def read_archive(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["day"] = pd.to_datetime(
        frame["timestamp"].astype(str).str[:8], format="%Y%m%d"
    ).dt.date
    frame["month"] = pd.to_datetime(frame["day"]).dt.month
    frame["year"] = pd.to_datetime(frame["day"]).dt.year
    frame["tile"] = frame["tile_id"].str.extract(r"_(\d{2}[A-Z]{3})_")

    # The clear-sky denominator, which is the one this project publishes.
    #
    # Read it from the archive where the archive carries it. Rebuilding it by
    # subtraction was necessary for the legacy run, which had no such columns,
    # and it is wrong for the reprocessed one: across its 1103 rows the rebuilt
    # denominator disagrees with the written `clear_pct` by up to 0.59, 220 rows
    # move by more than 0.01 in ice fraction, and the rebuild alone produces 162
    # rows above a fraction of 1 and 215 with a denominator at or below zero.
    # The written columns produce none of either.
    has_clear_columns = {"clear_pct", "solid_pct_clear", "light_pct_clear"} <= set(
        frame.columns
    )
    if has_clear_columns:
        frame["clear"] = frame["clear_pct"]
        frame["ice_clear"] = frame["solid_pct_clear"] + frame["light_pct_clear"]
    else:
        frame["clear"] = (
            1.0 - frame["cloud_pct"] - frame["land_pct"] - frame["nodata_pct"]
        )
        frame["ice_clear"] = np.where(
            frame["clear"] > 0,
            (frame["solid_pct"] + frame["light_pct"]) / frame["clear"],
            np.nan,
        )
    return frame


def _cap_per_year(rows: pd.DataFrame, cap: int) -> pd.DataFrame:
    """Thin a pool to `cap` rows, spreading the loss evenly over the years.

    Deterministic on purpose. Sampling would make the result depend on a seed,
    and a reviewer re-running this has to get the same scenes.
    """

    if len(rows) <= cap:
        return rows

    years = sorted(rows["year"].unique())
    per_year = max(1, cap // len(years))
    kept: list[pd.DataFrame] = []
    for year in years:
        block = rows[rows["year"] == year].sort_values("day")
        if len(block) <= per_year:
            kept.append(block)
            continue
        # Even spacing through the season rather than the first N, so a year is
        # not represented only by its Februaries.
        index = np.linspace(0, len(block) - 1, per_year).round().astype(int)
        kept.append(block.iloc[sorted(set(index))])
    return pd.concat(kept).sort_values("day")


def build_candidates(frame: pd.DataFrame) -> list[Candidate]:
    greenland = frame[frame["tile"].isin(GREENLAND_TILES)]
    dropped = len(frame) - len(greenland)
    if dropped:
        LOGGER.info("dropped %d scenes from tiles outside Greenland", dropped)

    frozen = greenland[greenland["month"].isin(FROZEN_MONTHS)]

    suspects = frozen[
        (frozen["clear"] > MIN_CLEAR_SHARE) & (frozen["ice_clear"] < SUSPECT_MAX_ICE)
    ]
    ice_anchors = frozen[
        (frozen["clear"] > ANCHOR_MIN_CLEAR)
        & (frozen["ice_clear"] > ICE_ANCHOR_MIN)
        & (frozen["ice_clear"] <= 1.0)
    ]
    water_anchors = greenland[
        greenland["month"].isin(OPEN_MONTHS)
        & (greenland["clear"] > ANCHOR_MIN_CLEAR)
        & (greenland["ice_clear"] < WATER_ANCHOR_MAX)
    ]

    ice_anchors = _cap_per_year(ice_anchors, MAX_ANCHORS_PER_ROLE)
    water_anchors = _cap_per_year(water_anchors, MAX_ANCHORS_PER_ROLE)

    candidates: list[Candidate] = []
    for role, rows in (
        (ROLE_SUSPECT, suspects),
        (ROLE_ICE, ice_anchors),
        (ROLE_WATER, water_anchors),
    ):
        for _, row in rows.sort_values("day").iterrows():
            candidates.append(
                Candidate(
                    role=role,
                    day=row["day"],
                    tile=str(row["tile"]),
                    ice_clear=float(row["ice_clear"]),
                    cloud=float(row["cloud_pct"]),
                    clear=float(row["clear"]),
                )
            )
    return candidates


def assign_scenes(
    candidates: Sequence[Candidate],
    available: Mapping[date, list[Mapping[str, Any]]],
) -> tuple[list[tuple[Candidate, Mapping[str, Any], int]], list[tuple[Candidate, str]]]:
    """Give each candidate its own radar scene, or none at all.

    Returns the accepted pairs and the rejected candidates with a reason. A scene
    claimed by two candidates is withdrawn from both, because keeping it for one
    would let the choice of which one silently decide the result.
    """

    wanted: dict[str, list[tuple[Candidate, Mapping[str, Any], int]]] = {}
    unmatched: list[tuple[Candidate, str]] = []

    for candidate in candidates:
        best: Optional[tuple[int, Mapping[str, Any]]] = None
        for offset in range(0, MATCH_WINDOW_DAYS + 1):
            for signed in {0} if offset == 0 else {-offset, offset}:
                day = candidate.day + timedelta(days=signed)
                for feature in available.get(day, []):
                    if best is None or abs(signed) < abs(best[0]):
                        best = (signed, feature)
            if best is not None:
                break
        if best is None:
            unmatched.append(
                (candidate, f"no RTC scene within {MATCH_WINDOW_DAYS} day(s)")
            )
            continue
        offset, feature = best
        wanted.setdefault(str(feature["id"]), []).append((candidate, feature, offset))

    accepted: list[tuple[Candidate, Mapping[str, Any], int]] = []
    for scene_id, claims in wanted.items():
        roles = {claim[0].role for claim in claims}
        if len(claims) > 1 and len(roles) > 1:
            for candidate, _, _ in claims:
                other = sorted(r for r in roles if r != candidate.role)
                unmatched.append(
                    (candidate, f"scene {scene_id} also claimed by {', '.join(other)}")
                )
            continue
        # Several candidates of the SAME role on one scene is only a duplicate,
        # not a collision. Keep the closest in time and drop the rest.
        claims.sort(key=lambda claim: abs(claim[2]))
        accepted.append(claims[0])
        for candidate, _, _ in claims[1:]:
            unmatched.append(
                (candidate, f"scene {scene_id} already used by the same role")
            )

    accepted.sort(key=lambda claim: (claim[0].role, claim[0].day))
    return accepted, unmatched


def load_measured(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open(newline="") as handle:
        return {row["scene_id"]: row for row in csv.DictReader(handle)}


def write_measurements(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SAR_CSV_HEADER))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_pairs(
    path: Path, pairs: Sequence[tuple[Candidate, Mapping[str, Any], int]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(PAIR_HEADER)
        for candidate, feature, offset in pairs:
            writer.writerow(
                [
                    candidate.role,
                    candidate.day.isoformat(),
                    candidate.tile,
                    round(candidate.ice_clear, 4),
                    round(candidate.cloud, 4),
                    round(candidate.clear, 4),
                    feature["id"],
                    offset,
                ]
            )


def permutation_p(left: np.ndarray, right: np.ndarray, draws: int = 20000) -> float:
    """Two sided permutation test on the difference of medians.

    Exact enumeration is out of reach at these group sizes, so this is a Monte
    Carlo approximation with a fixed seed. The seed is fixed so a reviewer gets
    the same p value, not to make any particular p value come out.
    """

    observed = abs(float(np.median(left) - np.median(right)))
    pool = np.concatenate([left, right])
    cut = len(left)
    generator = np.random.default_rng(seed=20260804)
    hits = 0
    for _ in range(draws):
        generator.shuffle(pool)
        if abs(float(np.median(pool[:cut]) - np.median(pool[cut:]))) >= observed:
            hits += 1
    # Add one to numerator and denominator so a p of exactly zero is never
    # reported from a finite number of draws.
    return (hits + 1) / (draws + 1)


def auc(positive: np.ndarray, negative: np.ndarray) -> float:
    """Probability that a random positive scores above a random negative."""

    if positive.size == 0 or negative.size == 0:
        return float("nan")
    ranks = pd.Series(np.concatenate([positive, negative])).rank().to_numpy()
    positive_ranks = ranks[: positive.size].sum()
    return float(
        (positive_ranks - positive.size * (positive.size + 1) / 2)
        / (positive.size * negative.size)
    )


def bootstrap_ci(values: np.ndarray, draws: int = 5000) -> tuple[float, float]:
    if values.size == 0:
        return (float("nan"), float("nan"))
    generator = np.random.default_rng(seed=20260804)
    medians = [
        float(np.median(generator.choice(values, size=values.size, replace=True)))
        for _ in range(draws)
    ]
    return (float(np.percentile(medians, 2.5)), float(np.percentile(medians, 97.5)))


def analyse(measurements: pd.DataFrame, pairs: pd.DataFrame) -> int:
    """Instrument test first, hypothesis second. Returns a process exit code."""

    joined = pairs.merge(measurements, on="scene_id", how="inner")
    usable = joined[joined["passes_gates"].astype(int) == 1]

    print("\n" + "=" * 74)
    print("SENTINEL-1 CROSS-CHECK")
    print("=" * 74)

    rejected = joined[joined["passes_gates"].astype(int) != 1]
    print(f"\nScenes measured: {len(joined)}, passing the gates: {len(usable)}")
    if len(rejected):
        print("Rejected:")
        for reason, count in rejected["reject_reason"].value_counts().items():
            print(f"    {count:3d}  {reason}")

    print("\n" + "-" * 74)
    print("GEOMETRY CHECK: is the land mask actually on top of the land?")
    print("-" * 74)
    contrast = usable["land_contrast_db"].astype(float)
    if not len(contrast):
        print("  no accepted scenes, nothing to check")
        return 2
    print(
        f"  land minus fjord backscatter over {len(contrast)} scenes: "
        f"median {contrast.median():.2f} dB, "
        f"range {contrast.min():.2f} to {contrast.max():.2f}"
    )
    print(
        "  Reference: with the mask aligned this was 5.75 dB on 2021-03-10, and\n"
        "  shifting the mask 1000 m dropped it to 1.99 dB while the fjord median\n"
        "  moved 0.17 dB. A misalignment hides in the answer and shows up here."
    )
    if contrast.median() < MIN_GLOBAL_CONTRAST_DB:
        print(
            f"\n  FAILED. A median of {contrast.median():.2f} dB is in the range a shifted\n"
            "  mask produces. Fix the geometry before reading anything below."
        )
        return 2
    print("\n  Passed.")

    groups = {
        role: usable[usable["role"] == role]["water_median_db"].astype(float).to_numpy()
        for role in (ROLE_ICE, ROLE_WATER, ROLE_SUSPECT)
    }
    for role, values in groups.items():
        if values.size == 0:
            print(f"\n{role}: no usable scenes, cannot continue")
            return 2
        low, high = bootstrap_ci(values)
        print(
            f"\n{role:12s} n={values.size:3d}  median {np.median(values):7.2f} dB"
            f"  95% CI [{low:.2f}, {high:.2f}]  range {values.min():.2f} to {values.max():.2f}"
        )

    print("\n" + "-" * 74)
    print("INSTRUMENT TEST: can radar tell ice from open water at this fjord?")
    print("-" * 74)
    ice, water = groups[ROLE_ICE], groups[ROLE_WATER]
    separation = float(np.median(ice) - np.median(water))
    p_instrument = permutation_p(ice, water)
    area = auc(ice, water)
    overlap = max(0.0, float(min(ice.max(), water.max()) - max(ice.min(), water.min())))
    print(f"  median difference   {separation:+.2f} dB")
    print(f"  permutation p       {p_instrument:.4f}")
    print(f"  AUC                 {area:.3f}")
    print(f"  overlapping range   {overlap:.2f} dB")

    if p_instrument > 0.05 or abs(area - 0.5) < 0.15:
        print(
            "\n  FAILED. Ice and open water do not separate here, so there is no scale\n"
            "  to compare the suspect days against. The honest result is this null,\n"
            "  not a comparison against a scale that does not exist."
        )
        return 1
    print("\n  Passed. A scale exists, with the overlap above as its resolution.")

    print("\n" + "-" * 74)
    print("HYPOTHESIS: the suspect days were frozen, and the optical series is wrong")
    print("-" * 74)
    suspects = groups[ROLE_SUSPECT]
    p_water = permutation_p(suspects, water)
    p_ice = permutation_p(suspects, ice)
    print(f"  suspects against open water   p = {p_water:.4f}  (should separate)")
    print(f"  suspects against ice anchors  p = {p_ice:.4f}  (should NOT separate)")

    # Which side each suspect falls on, using the midpoint between the anchor
    # medians. The midpoint is a convention, so the sweep below shows how much
    # the conclusion depends on it.
    midpoint = (float(np.median(ice)) + float(np.median(water))) / 2.0
    ice_side = (
        int((suspects > midpoint).sum())
        if np.median(ice) > np.median(water)
        else int((suspects < midpoint).sum())
    )
    print(
        f"\n  Midpoint {midpoint:.2f} dB: {ice_side} of {suspects.size} suspect days "
        f"fall on the ice side ({100 * ice_side / suspects.size:.0f} percent)"
    )

    print(
        "\n  Threshold sweep, because the number above depends on where the cut sits:"
    )
    print(f"    {'cut dB':>8s} {'suspects on ice side':>22s} {'anchors misfiled':>18s}")
    for cut in np.arange(-22.0, -16.9, 0.5):
        if np.median(ice) > np.median(water):
            on_ice = int((suspects > cut).sum())
            wrong = int((water > cut).sum()) + int((ice <= cut).sum())
        else:
            on_ice = int((suspects < cut).sum())
            wrong = int((water < cut).sum()) + int((ice >= cut).sum())
        print(f"    {cut:8.1f} {on_ice:22d} {wrong:18d}")

    print("\n  Read the anchors column before the suspects column. A cut that files")
    print("  many anchors wrongly cannot be used to judge anything.")

    print("\n" + "-" * 74)
    print("STRATIFIED BY RELATIVE ORBIT: is the result just viewing geometry?")
    print("-" * 74)
    print(
        "  The same surface backscatters differently from different incidence\n"
        "  angles, so a result could be produced by which orbits happen to sit in\n"
        "  which arm. Inside one orbit that cannot happen."
    )
    print(f"\n    {'orbit':>6s} {'ice':>16s} {'suspects':>16s} {'water':>16s}")
    for orbit in sorted(usable["relative_orbit"].dropna().unique()):
        block = usable[usable["relative_orbit"] == orbit]
        cells = []
        for role in (ROLE_ICE, ROLE_SUSPECT, ROLE_WATER):
            values = block[block["role"] == role]["water_median_db"].astype(float)
            cells.append(
                f"{values.median():7.2f} (n={len(values)})"
                if len(values)
                else "        (n=0)"
            )
        print(f"    {int(orbit):6d} {cells[0]:>16s} {cells[1]:>16s} {cells[2]:>16s}")
    print(
        "\n  An orbit where the suspects sit with the water rather than with the ice\n"
        "  would undercut the conclusion, and that is what to look for here."
    )

    print("\n" + "-" * 74)
    print("STRATIFIED BY MONTH: does melt season drive it?")
    print("-" * 74)
    months = pd.to_datetime(usable["optical_date"]).dt.month
    for month in sorted(months.unique()):
        block = usable[months == month]
        cells = []
        for role in (ROLE_ICE, ROLE_SUSPECT, ROLE_WATER):
            values = block[block["role"] == role]["water_median_db"].astype(float)
            cells.append(
                f"{values.median():7.2f} (n={len(values)})"
                if len(values)
                else "        (n=0)"
            )
        print(
            f"    month {int(month):2d}  ice {cells[0]}   suspects {cells[1]}   water {cells[2]}"
        )
    print(
        "\n  Wet snow lowers backscatter, so a suspect day late in March can read as\n"
        "  water while still carrying ice. That error runs against the hypothesis,\n"
        "  which makes any surviving result conservative rather than inflated."
    )
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--dry-run", action="store_true", help="show the sample, no network"
    )
    parser.add_argument("--analyse-only", action="store_true", help="skip measuring")
    parser.add_argument(
        "--limit", type=int, default=0, help="measure at most N new scenes"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    frame = read_archive(args.archive)
    candidates = build_candidates(frame)
    counts: dict[str, int] = {}
    for candidate in candidates:
        counts[candidate.role] = counts.get(candidate.role, 0) + 1
    LOGGER.info(
        "candidates: %s", ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    )

    pairs_path = args.output.with_name(args.output.stem + "_pairs.csv")

    if args.analyse_only:
        measurements = pd.read_csv(args.output)
        pairs = pd.read_csv(pairs_path)
        return analyse(measurements, pairs)

    days = sorted({candidate.day for candidate in candidates})
    LOGGER.info(
        "searching RTC scenes for %d optical days, %s to %s",
        len(days),
        days[0],
        days[-1],
    )
    features: list[Mapping[str, Any]] = []
    if not args.dry_run:
        # Year by year, because one search over nine years exceeds the page size.
        for year in sorted({day.year for day in days}):
            found = search_scenes(date(year, 1, 1), date(year, 12, 31))
            LOGGER.info("  %d: %d RTC scenes over the AOI", year, len(found))
            features.extend(found)
    available = scenes_by_date(features)

    accepted, unmatched = assign_scenes(candidates, available)

    print(f"\nPaired: {len(accepted)}, unpaired: {len(unmatched)}")
    by_role: dict[str, int] = {}
    for candidate, _, _ in accepted:
        by_role[candidate.role] = by_role.get(candidate.role, 0) + 1
    for role in (ROLE_SUSPECT, ROLE_ICE, ROLE_WATER):
        print(f"    {role:12s} {by_role.get(role, 0)}")
    collisions = [entry for entry in unmatched if "also claimed by" in entry[1]]
    if collisions:
        print(f"\nWithdrawn for role collision ({len(collisions)}):")
        for candidate, reason in collisions:
            print(f"    {candidate.day}  {candidate.role:12s}  {reason}")

    if args.dry_run:
        for role in (ROLE_SUSPECT, ROLE_ICE, ROLE_WATER):
            rows = [c for c in candidates if c.role == role]
            print(f"\n{role} ({len(rows)}):")
            for candidate in rows:
                print(
                    f"    {candidate.day}  {candidate.tile}  ice/clear {candidate.ice_clear:.3f}"
                    f"  cloud {candidate.cloud:.3f}  clear {candidate.clear:.3f}"
                )
        return 0

    write_pairs(pairs_path, accepted)
    measured = load_measured(args.output)
    token = SasToken()
    land, bounds, mask_crs, mask_transform = load_landmask()

    todo = [claim for claim in accepted if str(claim[1]["id"]) not in measured]
    if args.limit:
        todo = todo[: args.limit]
    LOGGER.info("%d scenes already measured, %d to read", len(measured), len(todo))

    for index, (candidate, feature, offset) in enumerate(todo, start=1):
        scene_id = str(feature["id"])
        LOGGER.info(
            "  [%d/%d] %s  %s  offset %+d d",
            index,
            len(todo),
            candidate.role,
            scene_id,
            offset,
        )
        try:
            stats: SceneStats = measure_scene(
                feature, land, bounds, mask_crs, mask_transform, token
            )
        except Exception as error:  # noqa: BLE001 - one bad scene must not kill the run
            LOGGER.warning("    failed: %s", error)
            continue
        measured[scene_id] = stats.as_row()
        write_measurements(args.output, measured.values())
        LOGGER.info(
            "    median %.2f dB, contrast %.2f dB, valid %.3f%s",
            stats.water_median_db,
            stats.land_contrast_db,
            stats.valid_share,
            "" if stats.passes_gates else f", REJECTED: {stats.reject_reason}",
        )

    if not measured:
        LOGGER.error("nothing measured")
        return 2

    return analyse(pd.read_csv(args.output), pd.read_csv(pairs_path))


if __name__ == "__main__":
    raise SystemExit(main())
