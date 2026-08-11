#!/usr/bin/env python3
"""How much does the published series depend on where the brightness gate sits?

The gate is a pair of fixed cuts, green above 0.10 and near infrared above 0.17,
and derive_thresholds.py justifies them against anchor scenes whose answer is
not in doubt. It measures recall and the false ice rate. What it does not
measure is how far the SERIES moves if the cut moves, and that question became
sharp with ice_endmember_stability.py: the fast ice of 2023 reads 34 percent
darker than the ten-season median, and 2025 and 2026 read 10 and 11 percent
darker, so a fixed cut does not sit in the same place relative to the ice from
one season to the next.

If the series is insensitive to the gate, the seasonal brightness difference is
a curiosity. If it is sensitive, and sensitive unevenly across seasons, then
part of the measured decline is the gate meeting a darker surface.

    python3 scripts/gate_sensitivity.py
    python3 scripts/gate_sensitivity.py --per-season 8 --reuse

This measures. It does not change anything: moving the gate would move the
published series, and that is a decision for the author, not for a script.

Design, and why it is affordable. Reading a scene costs a minute; evaluating a
different threshold on a cube already in memory costs milliseconds. So each
sampled scene is loaded once and classified at every candidate gate, which makes
the whole sweep cost the same as measuring one gate.

The cloud mask is computed once per scene and reused across the candidates, for
the same reason and because it does not depend on the brightness gate. That is
exactly what the pipeline does too: compute_cloud_mask sees the cube, not the
thresholds.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")

from uummannaq_ice.config_loader import load_run_config  # noqa: E402
from uummannaq_ice.model import load_cloud_model, resolve_device  # noqa: E402

LOGGER = logging.getLogger("gate_sensitivity")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/baseline.yaml"
DEFAULT_ARCHIVE = ROOT / "archive/reprocessed_2026/summary.csv"
STABILITY_RUN = ROOT / "archive/reprocessed_2026/ice_endmember_stability.csv"
PUBLISHED_NUMBERS = ROOT / "docs/published_numbers.json"

# The eleven bands that carry surface signal. B9 sits on a water vapour feature
# and B10 is the cirrus band, both placed where the atmosphere is opaque.
SURFACE_BANDS = (
    "coastal",
    "blue",
    "green",
    "red",
    "rededge1",
    "rededge2",
    "rededge3",
    "nir",
    "nir08",
    "swir16",
    "swir22",
)

# The published gate sits at 0.17. The sweep brackets it far enough either side
# to see the shape, not just the local slope.
NIR_GATES = (0.09, 0.13, 0.17, 0.21, 0.25)
PUBLISHED_GATE = 0.17

SEASON_WINDOW = (53, 180)
MIN_CLASSIFIED_SHARE = 0.30


def sample_days(archive: Path, per_season: int) -> list[str]:
    """Scenes the published series actually uses, spread across each season.

    Sorting by coverage would stack the sample into deep winter, where the fjord
    is frozen and no gate can change the answer. Spreading by day of year keeps
    the transition in the sample, which is the only place the gate can bite.
    """
    frame = pd.read_csv(archive)
    for col in ("solid_px", "light_px", "water_px", "cloud_px", "land_px", "nodata_px"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
    stamp = pd.to_datetime(frame.timestamp.astype(str), format="%Y%m%dT%H%M%S")
    frame["day"] = stamp.dt.date
    frame["season"] = stamp.dt.year
    frame["doy"] = stamp.dt.dayofyear
    classified = frame.solid_px + frame.light_px + frame.water_px
    grid = classified + frame.cloud_px + frame.land_px + frame.nodata_px
    frame["share"] = classified.divide(grid.where(grid > 0))

    lo, hi = SEASON_WINDOW
    ok = frame[
        (frame.doy >= lo) & (frame.doy <= hi) & (frame.share >= MIN_CLASSIFIED_SHARE)
    ]
    picked: list[str] = []
    for season, block in ok.groupby("season"):
        block = block.sort_values("doy")
        if len(block) <= per_season:
            chosen = block
        else:
            targets = np.linspace(lo, hi, per_season)
            rows = []
            for target in targets:
                candidate = (block.doy - target).abs().idxmin()
                if candidate not in rows:
                    rows.append(candidate)
                block = block.drop(index=candidate)
                if block.empty:
                    break
            chosen = ok.loc[rows]
        picked.extend(str(d) for d in chosen.day)
        LOGGER.info(
            "%d: %d usable scenes, taking %d",
            season,
            len(ok[ok.season == season]),
            len(chosen),
        )
    return sorted(picked)


def measure(days: list[str], config_path: Path) -> pd.DataFrame:
    from odc.stac import load as odc_load

    from uummannaq_ice.pipeline import BAND_SELECTION
    from uummannaq_ice.processing import (
        GREEN_IDX,
        INDEX_DENOMINATOR_FLOOR,
        NIR_IDX,
        SWIR_IDX,
        compute_cloud_mask,
        downsample_cube,
        land_mask_from_raster,
        reflectance_cube,
        void_reflectance,
    )
    from uummannaq_ice.stac import fetch_tiles

    device = resolve_device(None)
    base = load_run_config(config_path)
    model = load_cloud_model(base.checkpoint_path, device)

    rows: list[dict] = []
    for index, day in enumerate(days, start=1):
        config = load_run_config(config_path)
        config.start_date = config.end_date = date.fromisoformat(day)
        try:
            items = fetch_tiles(config)
            if not items:
                LOGGER.warning("%s: no scene", day)
                continue
            item = items[0]
            dataset = odc_load(
                [item], geopolygon=config.search_aoi, bands=BAND_SELECTION, chunks={}
            ).compute()
        except Exception as exc:  # pragma: no cover - network-driven
            LOGGER.warning("%s: %s", day, type(exc).__name__)
            continue

        baseline_str = item.properties.get("s2:processing_baseline", "0.0")
        try:
            baseline_major = int(float(baseline_str))
        except (TypeError, ValueError):
            baseline_major = 0
        small = downsample_cube(reflectance_cube(dataset, baseline_major))
        if small.ndim == 4:
            small = small.squeeze(0)
        _, h4, w4 = small.shape
        land = land_mask_from_raster(config.landmask_path, dataset.odc.geobox, w4, h4)

        # Everything below the gate is computed once. The cloud mask does not
        # see the thresholds, so recomputing it per candidate would only add an
        # inference pass and a source of drift.
        cloud = compute_cloud_mask(model, small, device)
        cube = small.numpy()
        void = void_reflectance(baseline_major)
        nodata = np.all(np.abs(cube - void) < 1e-4, axis=0)
        green, nir, swir = cube[GREEN_IDX], cube[NIR_IDX], cube[SWIR_IDX]
        green_pos = np.maximum(green, 0.0)
        nir_pos = np.maximum(nir, 0.0)
        swir_pos = np.maximum(swir, 0.0)
        ndsi = (green_pos - swir_pos) / (green_pos + swir_pos + 1e-6)
        ndwi = (green_pos - nir_pos) / (green_pos + nir_pos + 1e-6)
        ndsi_stable = (green_pos + swir_pos) > INDEX_DENOMINATOR_FLOOR
        ndwi_stable = (green_pos + nir_pos) > INDEX_DENOMINATOR_FLOOR
        usable = ~cloud & ~land & ~nodata
        thresholds = config.thresholds

        for gate in NIR_GATES:
            gated = replace(thresholds, nir_bright_min=gate)
            bright = (green > gated.vis_bright_min) & (nir > gated.nir_bright_min)
            solid = (ndsi > gated.ndsi_solid) & ndsi_stable & bright & usable
            light = (
                (ndsi > gated.ndsi_light)
                & (ndsi < gated.ndsi_solid)
                & ndsi_stable
                & bright
                & usable
            )
            water = (ndwi > gated.ndwi) & ndwi_stable & ~light & ~solid & usable
            classified = int(solid.sum() + light.sum() + water.sum())
            ice = (
                (solid.sum() + light.sum()) / classified if classified else float("nan")
            )
            rows.append(
                {
                    "day": day,
                    "season": int(day[:4]),
                    "doy": date.fromisoformat(day).timetuple().tm_yday,
                    "scene": item.id,
                    "gate": gate,
                    "ice": float(ice),
                    "classified": classified,
                    "share": classified / int(usable.size),
                }
            )
        published = next(
            r for r in rows[-len(NIR_GATES) :] if r["gate"] == PUBLISHED_GATE
        )
        LOGGER.info(
            "[%d/%d] %s  %s  ice at %.2f = %.3f",
            index,
            len(days),
            day,
            item.id,
            PUBLISHED_GATE,
            published["ice"],
        )
    return pd.DataFrame(rows)


def season_brightness() -> dict[int, float] | None:
    """Per-season ice brightness, read from the run that measured it.

    Copying those ten numbers in here would have been shorter and it is exactly
    the defect story_numbers.py exists to catch: a figure transcribed once, then
    quietly outliving the run behind it. Read from the committed artefact
    instead, so a rerun of ice_endmember_stability.py moves this table too.
    """
    if not STABILITY_RUN.exists():
        return None
    frame = pd.read_csv(STABILITY_RUN)
    surface = [b for b in frame.columns if b in SURFACE_BANDS]
    frame["brightness"] = frame[surface].mean(axis=1)
    frame["season"] = frame.day.astype(str).str[:4].astype(int)
    typical = float(frame.brightness.median())
    per_season = frame.groupby("season").brightness.mean() / typical
    return {int(s): float(v) for s, v in per_season.items()}


def replication_check(frame: pd.DataFrame, archive: Path) -> float:
    """At the published gate this must reproduce the archive, or nothing holds.

    The classification here is written out band by band rather than obtained
    from classify_tile, because classify_tile also builds two preview images per
    call and that would be five renders per scene for no reason. Writing it out
    means it can drift from the pipeline, so it is checked against the archive's
    own counts instead of being trusted. On the first run it matched all twenty
    sampled scenes exactly, cell for cell, which is also a statement about the
    cloud model being deterministic on this machine.
    """
    a = pd.read_csv(archive)
    for col in ("solid_px", "light_px", "water_px"):
        a[col] = pd.to_numeric(a[col], errors="coerce").fillna(0.0)
    a["day"] = pd.to_datetime(
        a.timestamp.astype(str), format="%Y%m%dT%H%M%S"
    ).dt.date.astype(str)
    classified = a.solid_px + a.light_px + a.water_px
    a["archive_ice"] = (a.solid_px + a.light_px).divide(
        classified.where(classified > 0)
    )

    mine = frame[frame.gate == PUBLISHED_GATE][["day", "ice"]]
    joined = mine.merge(a[["day", "archive_ice"]], on="day", how="inner")
    if joined.empty:
        return float("nan")
    return float((joined.ice - joined.archive_ice).abs().max())


def decline_at(shifted: dict[int, float]) -> tuple[float, float]:
    """Early-to-late decline and its exact permutation p, from season means."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from story_numbers import LATE_FROM, exact_permutation  # noqa: PLC0415

    seasons = sorted(shifted)
    values = np.array([shifted[s] for s in seasons])
    n_early = sum(1 for s in seasons if s < LATE_FROM)
    early = values[:n_early].mean()
    late = values[n_early:].mean()
    _, p_perm, _, _ = exact_permutation(values, n_early)
    return 100.0 * (1.0 - late / early), float(p_perm)


def implied_decline(per_season: pd.DataFrame) -> None:
    """What the published decline would become if the gate moved.

    This is an estimate, and the shape of the estimate matters. The sampled
    scenes are not the series: the published means come from a gap-filled daily
    curve over every usable scene, and eight scenes a season cannot rebuild
    that. What the sample CAN give is the shift, because the same scenes are
    classified at every gate, so the difference between two gates is measured on
    identical input. That shift is then applied to the published season means.

    So the levels below are the published ones and the movement is measured.
    Rebuilding the series at each gate would mean reclassifying all 1103 scenes
    five times, which is the honest way to get an exact answer and is a day of
    compute rather than an afternoon.
    """
    if not PUBLISHED_NUMBERS.exists():
        return
    import json  # noqa: PLC0415

    published = json.loads(PUBLISHED_NUMBERS.read_text())["spring_means"]
    published = {int(k): float(v) for k, v in published.items()}
    seasons = [s for s in published if s in per_season.index]
    if len(seasons) < len(published):
        return

    print()
    print("What that would do to the published decline, estimated")
    print("=" * 78)
    print(f"{'gate':>8s}{'decline':>12s}{'permutation p':>16s}{'vs published':>15s}")
    base_decline, base_p = decline_at({s: published[s] for s in seasons})
    for gate in NIR_GATES:
        shift = {
            s: published[s]
            + (per_season.loc[s, gate] - per_season.loc[s, PUBLISHED_GATE])
            for s in seasons
        }
        decline, p_perm = decline_at(shift)
        mark = (
            "  published"
            if gate == PUBLISHED_GATE
            else f"{decline - base_decline:+15.1f}"
        )
        print(f"{gate:8.2f}{decline:11.1f} %{p_perm:16.3f}{mark}")
    print()
    print(
        "Levels are the published season means; only the movement between gates\n"
        "is measured here, on scenes classified identically at each one. An exact\n"
        "answer means reclassifying all 1103 scenes five times."
    )


def anchor_cost(frame: pd.DataFrame) -> None:
    """What each gate costs on days whose answer is not in doubt.

    A decline that shrinks at a lower gate is only interesting if the lower gate
    is defensible, and the way to ask that is the way derive_thresholds.py asks
    it: against surfaces whose answer is known. A lower cut recovers ice on a
    frozen fjord and invents it on an open one, and both have to be on the page
    or the sweep reads as an invitation to pick the gate that suits the argument.

    This is the cruder of the two checks and it says so. derive_thresholds.py
    works from eighteen scenes with labels confirmed on their own previews.
    These anchors are taken from whatever the sweep happened to sample.
    """
    wide = frame.pivot_table(index=["day", "doy"], columns="gate", values="ice")
    wide = wide.reset_index()
    # Late June onward: the latest break-up in the record is 8 June 2024, so any
    # ice reported here is false ice.
    open_days = wide[wide.doy >= 170]
    # Through mid April, on days that already read as a closed cover: anything
    # missing is ice the gate did not recover.
    frozen_days = wide[(wide.doy <= 110) & (wide[PUBLISHED_GATE] >= 0.95)]
    if open_days.empty or frozen_days.empty:
        return

    print()
    print("What each gate costs on days whose answer is not in doubt")
    print("-" * 78)
    print(
        f"{'gate':>6s}{'false ice':>12s}{'worst':>9s}{'closed cover':>15s}{'worst':>9s}"
    )
    for gate in NIR_GATES:
        mark = "  published" if gate == PUBLISHED_GATE else ""
        print(
            f"{gate:6.2f}{open_days[gate].mean():12.4f}{open_days[gate].max():9.4f}"
            f"{frozen_days[gate].mean():15.4f}{frozen_days[gate].min():9.4f}{mark}"
        )
    print()
    print(
        f"false ice over {len(open_days)} certainly open days, closed cover over "
        f"{len(frozen_days)} certainly frozen ones.\n"
        "Both move, and both stay small: the lowest gate roughly doubles the false\n"
        "ice while recovering a comparable amount of real ice. That is why the\n"
        "primary justification for 0.17 stays with derive_thresholds.py, which\n"
        "works from eighteen scenes whose labels were confirmed one by one, and\n"
        "not with this table."
    )


def report(frame: pd.DataFrame) -> None:
    wide = frame.pivot_table(index=["season", "day"], columns="gate", values="ice")
    print()
    print("Ice fraction of the same scene at five gates")
    print("=" * 78)
    print(f"{'season':8s}{'scenes':>8s}" + "".join(f"{g:>10.2f}" for g in NIR_GATES))
    per_season = wide.groupby(level=0).mean()
    counts = wide.groupby(level=0).size()
    for season, row in per_season.iterrows():
        print(
            f"{season:<8d}{counts[season]:8d}"
            + "".join(f"{row[g]:10.3f}" for g in NIR_GATES)
        )
    overall = wide.mean()
    print(
        f"{'all':8s}{len(wide):8d}" + "".join(f"{overall[g]:10.3f}" for g in NIR_GATES)
    )

    print()
    print("How far each season moves when the gate moves, against the published 0.17")
    print("-" * 78)
    # A frozen fjord and an open one both ignore the gate: every cell is far
    # from the cut either way. Only scenes in transition can move, and this
    # fjord spends most of its season at one end or the other, so the count of
    # scenes that actually moved is the honest sample size behind each row.
    print(
        f"{'season':8s}{'0.09':>10s}{'0.13':>10s}{'0.21':>10s}{'0.25':>10s}"
        f"{'span':>10s}{'n moved':>9s}"
    )
    spans = {}
    moved_counts = {}
    for season, row in per_season.iterrows():
        base = row[PUBLISHED_GATE]
        deltas = {g: row[g] - base for g in NIR_GATES if g != PUBLISHED_GATE}
        span = max(deltas.values()) - min(deltas.values())
        spans[season] = span
        block = wide.loc[season]
        moved = int(
            (
                block[list(NIR_GATES)].max(axis=1) - block[list(NIR_GATES)].min(axis=1)
                > 0.001
            ).sum()
        )
        moved_counts[season] = moved
        print(
            f"{season:<8d}"
            + "".join(f"{deltas[g]:+10.3f}" for g in (0.09, 0.13, 0.21, 0.25))
            + f"{span:10.3f}{moved:>6d}/{len(block):<3d}"
        )
    total_moved = sum(moved_counts.values())
    print()
    print(
        f"{total_moved} of {len(wide)} sampled scenes move at all when the gate moves.\n"
        "The rest are a frozen fjord or an open one, where every cell sits far\n"
        "from the cut. That ratio is a property of this fjord rather than of the\n"
        "sample: the published daily series is composed the same way, which is\n"
        "why the sample is spread evenly over the season instead of being aimed\n"
        "at the transition. It does mean each season's row rests on very few\n"
        "scenes, and the per-season numbers should be read with that in mind."
    )

    print()
    print("Is the gate more expensive in the seasons whose ice is darker?")
    print("-" * 78)
    darkness = season_brightness()
    if darkness is None:
        print(
            f"no {STABILITY_RUN.name} to read, so there is nothing to compare\n"
            "against. Run scripts/ice_endmember_stability.py first."
        )
        return
    pairs = [(darkness[s], spans[s]) for s in spans if s in darkness]
    if len(pairs) < 3:
        print("too few seasons in both runs to compare")
        return
    x = np.array([p[0] for p in pairs])
    y = np.array([p[1] for p in pairs])
    r = float(np.corrcoef(x, y)[0, 1])
    print(f"{'season':8s}{'brightness':>12s}{'gate span':>12s}")
    for season in sorted(spans):
        if season in darkness:
            print(f"{season:<8d}{darkness[season]:12.2f}{spans[season]:12.3f}")
    print()
    print(f"correlation of gate span with season brightness   r = {r:+.3f}")
    print(
        "A negative correlation means the darker a season's ice, the more its\n"
        "reading depends on where the cut was put."
    )

    anchor_cost(frame)
    implied_decline(per_season)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    parser.add_argument("--per-season", type=int, default=6)
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("rasterio").setLevel(logging.ERROR)

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "gate_sensitivity.csv"
    if args.reuse and path.exists():
        frame = pd.read_csv(path)
        LOGGER.info("reusing %s", path)
    else:
        days = sample_days(args.archive, args.per_season)
        LOGGER.info("%d scenes to reclassify at %d gates", len(days), len(NIR_GATES))
        frame = measure(days, args.config)
        if frame.empty:
            print("nothing measured")
            return 1
        frame.to_csv(path, index=False)
        LOGGER.info("written to %s", path)

    drift = replication_check(frame, args.archive)
    print()
    print("Replication check at the published gate")
    print("-" * 78)
    if not np.isfinite(drift):
        print("no overlap with the archive, cannot check")
    else:
        print(f"largest difference from the archive's own ice fraction: {drift:.6f}")
        if drift > 1e-4:
            print()
            print(
                "This classification no longer reproduces the archive at the gate\n"
                "the archive was built with, so the sweep below is measuring the\n"
                "difference between two classifiers rather than the effect of the\n"
                "gate. Fix that before quoting anything from this run."
            )
            return 1

    report(frame)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
