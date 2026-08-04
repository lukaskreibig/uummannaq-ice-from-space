#!/usr/bin/env python3
"""Validate a finished summary CSV without reading 1500 rows by hand.

Run this the moment a reprocess finishes. It answers one question: is this file
safe to publish? Every gate either passes, warns, or fails, and the script exits
non-zero if anything failed, so it can sit in a Makefile target or a shell `&&`
chain.

    python3 scripts/check_summary.py out/archive/summary.csv \
        --expect out/archive/preflight.json \
        --baseline archive/legacy_pipeline/ice-final/summary_test.csv

The gates, and why each one exists:

  header            The writer refuses to append to a CSV with a different
                    column layout, but a file assembled by hand can still be
                    wrong. Column drift is silent downstream.
  rows_intact       A run killed mid-flush leaves a half row. Appending to it
                    glues the next row on and pandas then refuses the file.
  no_duplicate_*    fetch_tiles promises one scene per day and the writer
                    promises no repeated (tile_id, timestamp). Both are load
                    bearing for the daily mean.
  tiles             The catalogue has returned scenes from West Africa and the
                    North Pacific for this AOI. Their bounding boxes span the
                    whole planet, so the AOI-coverage floor does not stop them.
  ranges            Percentages outside 0 to 1 mean the accounting broke.
  grid              Every percentage divides by the same grid. If the implied
                    grid size moves between rows, scenes were clipped
                    differently and the numbers are not comparable.
  season_shape      Uummannaq is frozen in February and open in late June. A
                    season that does not show that did not measure ice.
  scene_counts      Compares against what the STAC catalogue actually offered,
                    as recorded by scripts/preflight.py before the run.
  baseline          Lists the days that moved most against the published
                    series, so the copy that quotes numbers can be rechecked.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

# Kept as a literal so the checker runs against a CSV produced by any version of
# the package, including one that is not installed in the current interpreter.
EXPECTED_HEADER = [
    "tile_id",
    "timestamp",
    "solid_px",
    "light_px",
    "water_px",
    "cloud_px",
    "land_px",
    "nodata_px",
    "unknown_px",
    "solid_pct",
    "light_pct",
    "water_pct",
    "cloud_pct",
    "land_pct",
    "nodata_pct",
    "clear_px",
    "clear_pct",
    "solid_pct_clear",
    "light_pct_clear",
    "water_pct_clear",
    "mean_ndsi_solid",
    "mean_ndsi_light",
    "mean_ndwi_water",
    "eo_cloud_cover",
    "sun_elev",
    "sun_azim",
    "edge_gap",
]

# The layout the published archive was written with, before the clear-sky
# columns existed. Accepted with a warning so an old file can still be checked.
LEGACY_HEADER = [
    c
    for c in EXPECTED_HEADER
    if not c.startswith("clear_") and not c.endswith("_clear")
]

PCT_COLUMNS = [
    "solid_pct",
    "light_pct",
    "water_pct",
    "cloud_pct",
    "land_pct",
    "nodata_pct",
]
PX_COLUMNS = ["solid_px", "light_px", "water_px", "cloud_px", "land_px", "nodata_px"]

# Mirrors backend/main.py FJORD_SUN_START / FJORD_SUN_END.
SUN_START = 45
SUN_END = 180
# Two ends of the season that must differ in the right direction.
WINTER_DOY = (45, 90)
SUMMER_DOY = (160, 180)

# MGRS tiles that genuinely see Uummannaq Bay. 22WDD carries the published
# archive; 21WXU is the zone-21 neighbour whose footprint also covers the AOI.
KNOWN_TILES = {"22WDD", "21WXU"}


@dataclass
class Report:
    rows: list[tuple[str, str, str]] = field(default_factory=list)
    failed = 0
    warned = 0

    def add(self, status: str, gate: str, detail: str) -> None:
        self.rows.append((status, gate, detail))
        if status == "FAIL":
            self.failed += 1
        elif status == "WARN":
            self.warned += 1

    def ok(self, gate: str, detail: str) -> None:
        self.add("PASS", gate, detail)

    def warn(self, gate: str, detail: str) -> None:
        self.add("WARN", gate, detail)

    def fail(self, gate: str, detail: str) -> None:
        self.add("FAIL", gate, detail)

    def render(self) -> str:
        width = max((len(g) for _, g, _ in self.rows), default=0)
        lines = []
        for status, gate, detail in self.rows:
            lines.append(f"[{status:4}] {gate:<{width}}  {detail}")
        return "\n".join(lines)


def read_raw_lines(path: Path) -> list[str]:
    return path.read_text().splitlines()


def gate_header(path: Path, report: Report) -> list[str]:
    lines = read_raw_lines(path)
    if not lines:
        report.fail("header", f"{path} is empty")
        return []
    header = pd.read_csv(path, nrows=0).columns.tolist()
    if header == EXPECTED_HEADER:
        report.ok("header", f"{len(header)} columns, current layout")
    elif header == LEGACY_HEADER:
        report.warn(
            "header",
            f"{len(header)} columns, pre-clear-sky layout. The clear-sky columns "
            f"are missing, so cloud-corrected shares cannot be computed from this file.",
        )
    else:
        missing = [c for c in EXPECTED_HEADER if c not in header]
        extra = [c for c in header if c not in EXPECTED_HEADER]
        report.fail("header", f"unexpected layout. missing={missing} extra={extra}")
    return header


def gate_rows_intact(path: Path, header: list[str], report: Report) -> None:
    text = path.read_text()
    if not text.endswith("\n"):
        report.fail(
            "rows_intact",
            "file does not end with a newline: the last row is a fragment from a "
            "run that was killed mid-write. Re-open it with SummaryWriter, which "
            "trims the fragment, or delete the last line by hand.",
        )
        return
    width = len(header)
    over: list[tuple[int, int]] = []
    under: list[tuple[int, int]] = []
    with path.open(newline="") as handle:
        import csv as _csv

        for number, row in enumerate(_csv.reader(handle), start=1):
            if number == 1 or not row:
                continue
            if len(row) > width:
                over.append((number, len(row)))
            elif len(row) < width:
                under.append((number, len(row)))
    if over:
        sample = ", ".join(f"line {n} has {w} fields" for n, w in over[:5])
        report.fail(
            "rows_intact",
            f"{len(over)} row(s) hold more fields than the header, which is what a "
            f"row glued onto a torn fragment looks like: {sample}",
        )
    elif under:
        # pandas pads short rows with NaN, so these parse; they still mean some
        # trailing columns were never written.
        sample = ", ".join(f"line {n} has {w}" for n, w in under[:3])
        report.warn(
            "rows_intact",
            f"{len(under)} row(s) stop short of the {width} header columns "
            f"({sample}); the trailing columns will read as empty",
        )
    else:
        report.ok("rows_intact", f"every row has {width} fields")


def load(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["date"] = pd.to_datetime(frame["timestamp"], format="%Y%m%dT%H%M%S", utc=True)
    frame["day"] = frame["date"].dt.normalize()
    frame["year"] = frame["date"].dt.year
    frame["doy"] = frame["date"].dt.dayofyear
    frame["mgrs"] = frame["tile_id"].str.split("_").str[1]
    frame["frac"] = frame["solid_pct"] + frame["light_pct"]
    return frame


def gate_duplicates(frame: pd.DataFrame, report: Report) -> None:
    dup_scene = frame[frame.duplicated(["tile_id", "timestamp"], keep=False)]
    if len(dup_scene):
        ids = sorted(set(dup_scene["tile_id"]))[:5]
        report.fail(
            "no_duplicate_scenes", f"{len(dup_scene)} repeated rows, e.g. {ids}"
        )
    else:
        report.ok("no_duplicate_scenes", f"{len(frame)} rows, all distinct")

    dup_day = frame[frame.duplicated(["day"], keep=False)]
    if len(dup_day):
        days = sorted({d.date().isoformat() for d in dup_day["day"]})[:8]
        report.fail(
            "no_duplicate_dates",
            f"{dup_day['day'].nunique()} day(s) carry more than one scene, e.g. {days}. "
            f"The daily mean would weight those days twice.",
        )
    else:
        report.ok("no_duplicate_dates", f"{frame['day'].nunique()} distinct days")


def gate_tiles(frame: pd.DataFrame, report: Report, allowed: set[str]) -> None:
    counts = frame["mgrs"].value_counts().to_dict()
    foreign = {tile: n for tile, n in counts.items() if tile not in allowed}
    if foreign:
        report.fail(
            "tiles",
            f"scenes from tile(s) that do not see this fjord: {foreign}. "
            f"Their catalogue bounding boxes span the whole planet, so the AOI "
            f"coverage floor in stac.py lets them through.",
        )
    else:
        report.ok("tiles", f"{counts}")
    if len(counts) > 1:
        dominant, n = max(counts.items(), key=lambda kv: kv[1])
        share = n / len(frame)
        report.warn(
            "tiles_mixed",
            f"the record mixes {len(counts)} MGRS tiles ({dominant} is {share:.0%}). "
            f"The land mask is georeferenced, so it no longer stretches onto "
            f"whichever grid arrives, but the tiles still clip the AOI onto "
            f"different pixel grids. On the previous archive the two tiles "
            f"differed by 0.14 in the spring mean, a third of the headline, so "
            f"compare per-tile means before publishing.",
        )


def gate_ranges(frame: pd.DataFrame, report: Report) -> None:
    problems = []
    for column in PCT_COLUMNS:
        series = pd.to_numeric(frame[column], errors="coerce")
        out = frame[(series < 0) | (series > 1)]
        if len(out):
            problems.append(f"{column}: {len(out)} row(s) outside 0..1")
    frac = frame["frac"]
    out = frame[(frac < 0) | (frac > 1)]
    if len(out):
        problems.append(f"ice fraction: {len(out)} row(s) outside 0..1")
    for column in PX_COLUMNS + ["unknown_px"]:
        negative = frame[pd.to_numeric(frame[column], errors="coerce") < 0]
        if len(negative):
            problems.append(f"{column}: {len(negative)} negative count(s)")
    if problems:
        report.fail("ranges", "; ".join(problems))
    else:
        report.ok(
            "ranges",
            f"all shares within 0..1; ice fraction {frame['frac'].min():.4f} to "
            f"{frame['frac'].max():.4f}",
        )


def gate_indices(frame: pd.DataFrame, report: Report) -> None:
    """NDSI and NDWI live in -1 to 1 whenever the reflectances are physical.

    They leave that range only when the two bands sum to something at or below
    zero, which after the radiometric offset fix is exactly what a dark pixel
    does. A mean NDWI of 2.1 over the cells called water means those cells were
    selected by an unstable ratio, not by being wet. Ice is now protected by the
    brightness gate; water is still picked by NDWI alone.
    """
    offenders = {}
    for column in ["mean_ndsi_solid", "mean_ndsi_light", "mean_ndwi_water"]:
        if column not in frame.columns:
            continue
        series = pd.to_numeric(frame[column], errors="coerce")
        bad = frame[(series < -1) | (series > 1)]
        if len(bad):
            worst = series.reindex(bad.index).abs().max()
            offenders[column] = f"{len(bad)} row(s), worst magnitude {worst:.2f}"
    if offenders:
        report.warn(
            "indices",
            "index means outside -1..1, so those cells were classified on a ratio "
            f"with a vanishing denominator: {offenders}",
        )
    else:
        report.ok("indices", "every NDSI and NDWI mean inside -1..1")


def gate_zeroed_band(frame: pd.DataFrame, report: Report) -> None:
    """Catch a scene whose NIR band came back as pure fill.

    GDAL can fail a COG read inside curl and return the band as zeros without
    raising anything, so odc fills it, the row is written, and the scene reads as
    a perfectly plausible open-water day. The pipeline now rejects that at load
    time, but this file is the last line of defence and the signature is exact:
    with NIR zeroed, NDWI = (green - 0)/(green + 0) = 1 for every water cell, so
    mean_ndwi_water lands on 1.0 and water_pct_clear on 1.0. Both sit inside the
    ranges every other gate checks, which is precisely why this needs its own.
    """
    if "mean_ndwi_water" not in frame.columns:
        report.warn("zeroed-band", "no mean_ndwi_water column to check")
        return

    ndwi = pd.to_numeric(frame["mean_ndwi_water"], errors="coerce")
    suspect = frame[(ndwi - 1.0).abs() < 1e-6]

    if "water_pct_clear" in frame.columns:
        water = pd.to_numeric(frame["water_pct_clear"], errors="coerce")
        suspect = frame[((ndwi - 1.0).abs() < 1e-6) & ((water - 1.0).abs() < 1e-3)]

    if len(suspect):
        ids = ", ".join(str(v) for v in suspect.iloc[:5, 0].tolist())
        report.fail(
            "zeroed-band",
            f"{len(suspect)} scene(s) have mean_ndwi_water of exactly 1.0, which "
            f"is the signature of a band read that returned fill instead of "
            f"pixels. Re-run those days: {ids}",
        )
    else:
        report.ok("zeroed-band", "no scene shows the zeroed-band signature")


def gate_grid(frame: pd.DataFrame, report: Report) -> None:
    """Every percentage divides by the same grid; check that it really does.

    The grid size has to be inferred, because the CSV never states it. Each
    class gives one estimate, `count / share`. Shares are rounded to four
    decimals, so a class holding one percent of the grid carries about one
    percent of rounding error in its estimate and a class holding ninety
    percent carries almost none. Only the largest class is used, and the
    tolerances below are set by that residual rounding, not by taste.
    """
    estimates: dict[Any, float] = {}
    inconsistent = 0
    for index, row in frame.iterrows():
        candidates = []
        for px, pct in zip(PX_COLUMNS, PCT_COLUMNS, strict=True):
            share = row[pct]
            count = row[px]
            if pd.notna(share) and share > 0.01:
                candidates.append((share, count / share))
        if not candidates:
            continue
        # Cross-check only classes big enough for the estimate to mean anything.
        solid = [value for share, value in candidates if share >= 0.05]
        if len(solid) > 1 and (max(solid) - min(solid)) > 0.01 * max(solid):
            inconsistent += 1
        estimates[index] = max(candidates, key=lambda pair: pair[0])[1]
    if not estimates:
        report.warn("grid", "no row had a share large enough to imply a grid size")
        return
    series = pd.Series(estimates)
    spread = (series.max() - series.min()) / series.median()
    if inconsistent:
        report.fail(
            "grid",
            f"{inconsistent} row(s) imply two different grid sizes from their own "
            f"columns, so the percentages do not share a denominator",
        )
    elif spread > 0.02:
        report.warn(
            "grid",
            f"implied grid size varies by {spread:.1%} across the file "
            f"({series.min():.0f} to {series.max():.0f} cells). Expected when the "
            f"record mixes MGRS tiles; not expected within one tile.",
        )
    else:
        report.ok("grid", f"one grid of about {series.median():.0f} cells throughout")

    # Cells claimed by at least one class. unknown_px is the double-counted
    # overlap between classes, so subtracting it turns the sum of six possibly
    # overlapping counts back into a count of distinct cells.
    occupied = (frame[PX_COLUMNS].sum(axis=1) - frame["unknown_px"]).reindex(
        series.index
    )
    # 0.5 percent of headroom for the rounding described above. A genuine
    # accounting fault is not subtle: the published archive overshoots by up to
    # 17.9 percent.
    over = series.index[occupied > series * 1.005]
    if len(over):
        worst = (occupied / series).max()
        report.fail(
            "grid_accounting",
            f"{len(over)} row(s) claim more cells than the grid holds, up to "
            f"{worst:.1%} of it. Either unknown_px does not account for the "
            f"overlap between classes or the percentages divide by something else.",
        )
    else:
        unclassified = (1 - (occupied / series)).median()
        report.ok(
            "grid_accounting",
            f"ice + water + cloud + land + nodata never exceeds the grid; "
            f"median {unclassified:.1%} of cells fall in no class at all",
        )


def gate_season_shape(frame: pd.DataFrame, report: Report) -> None:
    lines = []
    broken = []
    thin = []
    for year, group in frame.groupby("year"):
        winter = group[
            (group["doy"] >= WINTER_DOY[0]) & (group["doy"] <= WINTER_DOY[1])
        ]["frac"]
        summer = group[
            (group["doy"] >= SUMMER_DOY[0]) & (group["doy"] <= SUMMER_DOY[1])
        ]["frac"]
        if len(winter) < 5 or len(summer) < 5:
            thin.append(f"{year} ({len(winter)} winter, {len(summer)} summer scenes)")
            continue
        w, s = winter.mean(), summer.mean()
        lines.append(f"{year}: {w:.2f} -> {s:.2f}")
        if not w > s:
            broken.append(f"{year} winter {w:.3f} is not above summer {s:.3f}")
    if broken:
        report.fail("season_shape", "; ".join(broken))
    elif lines:
        report.ok(
            "season_shape",
            "winter high, summer low in every season. " + "; ".join(lines),
        )
    else:
        report.warn("season_shape", "no season had enough scenes at both ends to judge")
    if thin:
        report.warn("season_shape_thin", "not judged: " + "; ".join(thin))


def gate_scene_counts(
    frame: pd.DataFrame, report: Report, expect_path: Path | None
) -> None:
    observed = frame[(frame["doy"] >= SUN_START) & (frame["doy"] <= SUN_END)]
    per_year = observed.groupby("year").size().to_dict()
    window_days = SUN_END - SUN_START + 1
    coverage = {
        y: f"{n}/{window_days} ({n / window_days:.0%})"
        for y, n in sorted(per_year.items())
    }

    if expect_path is None:
        report.warn(
            "scene_counts",
            f"no --expect file, so counts are only reported, not checked: {coverage}",
        )
        return

    expected = json.loads(expect_path.read_text())
    want = {int(y): n for y, n in expected["scenes_in_sun_window_per_year"].items()}
    missing = {}
    for year, target in sorted(want.items()):
        got = per_year.get(year, 0)
        if got < target:
            missing[year] = f"{got}/{target}"
    if missing:
        report.fail(
            "scene_counts",
            f"fewer scenes than the catalogue offered before the run: {missing}. "
            f"Those days failed to load or the run did not finish.",
        )
    else:
        report.ok(
            "scene_counts",
            f"every season complete against the preflight inventory: {coverage}",
        )


def gate_baseline(
    frame: pd.DataFrame, report: Report, baseline_path: Path | None, top: int
) -> None:
    if baseline_path is None:
        report.warn("baseline", "no --baseline given, nothing compared")
        return
    old = pd.read_csv(baseline_path)
    old["date"] = pd.to_datetime(old["timestamp"], format="%Y%m%dT%H%M%S", utc=True)
    old["day"] = old["date"].dt.normalize()
    old["frac_old"] = old["solid_pct"] + old["light_pct"]
    old["mgrs_old"] = old["tile_id"].str.split("_").str[1]

    new = frame[["day", "frac", "mgrs", "doy", "year"]].rename(
        columns={"frac": "frac_new", "mgrs": "mgrs_new"}
    )
    joined = new.merge(old[["day", "frac_old", "mgrs_old"]], on="day", how="inner")
    if joined.empty:
        report.warn("baseline", "no overlapping days with the published series")
        return
    joined["delta"] = joined["frac_new"] - joined["frac_old"]
    in_window = joined[(joined["doy"] >= SUN_START) & (joined["doy"] <= SUN_END)]

    only_new = set(new["day"]) - set(old["day"])
    only_old = set(old["day"]) - set(new["day"])

    detail = (
        f"{len(joined)} shared days, {len(only_new)} new, {len(only_old)} dropped. "
        f"mean shift {joined['delta'].mean():+.4f}, mean absolute shift "
        f"{joined['delta'].abs().mean():.4f}. "
        f"In the sun window: season mean {in_window['frac_old'].mean():.4f} -> "
        f"{in_window['frac_new'].mean():.4f}."
    )
    report.ok("baseline", detail)

    movers = joined.reindex(
        joined["delta"].abs().sort_values(ascending=False).index
    ).head(top)
    print("\nBiggest movers against the published series")
    print(f"{'day':<12} {'was':>8} {'now':>8} {'delta':>8}  tile was -> now")
    for row in movers.itertuples(index=False):
        print(
            f"{row.day.date().isoformat():<12} {row.frac_old:8.4f} {row.frac_new:8.4f} "
            f"{row.delta:+8.4f}  {row.mgrs_old} -> {row.mgrs_new}"
        )

    per_year = joined.groupby("year").agg(
        days=("delta", "size"),
        was=("frac_old", "mean"),
        now=("frac_new", "mean"),
    )
    per_year["delta"] = per_year["now"] - per_year["was"]
    print("\nSeason means, published vs new")
    print(per_year.round(4).to_string())


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("csv", type=Path, help="The summary CSV the run produced.")
    parser.add_argument(
        "--baseline", type=Path, help="Published summary CSV to compare against."
    )
    parser.add_argument(
        "--expect", type=Path, help="preflight.json written by scripts/preflight.py."
    )
    parser.add_argument(
        "--allow-tile", action="append", default=[], help="Extra MGRS tile to accept."
    )
    parser.add_argument("--top", type=int, default=15, help="How many movers to list.")
    parser.add_argument(
        "--json", type=Path, help="Write the gate results here as JSON."
    )
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"[FAIL] {args.csv} does not exist")
        return 2

    report = Report()
    header = gate_header(args.csv, report)
    if not header:
        print(report.render())
        return 2
    gate_rows_intact(args.csv, header, report)
    if report.failed:
        # A structurally broken file cannot be parsed into a frame at all.
        print(report.render())
        return 2

    frame = load(args.csv)
    gate_duplicates(frame, report)
    gate_tiles(frame, report, KNOWN_TILES | set(args.allow_tile))
    gate_ranges(frame, report)
    gate_indices(frame, report)
    gate_zeroed_band(frame, report)
    gate_grid(frame, report)
    gate_season_shape(frame, report)
    gate_scene_counts(frame, report, args.expect)
    gate_baseline(frame, report, args.baseline, args.top)

    print()
    print(report.render())
    print()
    verdict = "REJECT" if report.failed else ("REVIEW" if report.warned else "ACCEPT")
    print(
        f"{verdict}: {report.failed} failed, {report.warned} warned, {len(report.rows)} gates"
    )

    payload: dict[str, Any] = {
        "csv": str(args.csv),
        "verdict": verdict,
        "failed": report.failed,
        "warned": report.warned,
        "gates": [{"status": s, "gate": g, "detail": d} for s, g, d in report.rows],
    }
    if args.json:
        args.json.write_text(json.dumps(payload, indent=2) + "\n")

    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
