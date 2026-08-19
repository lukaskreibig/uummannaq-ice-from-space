#!/usr/bin/env python3
"""Turns the committed archive tables into the JSON the results pages read.

    python3 scripts/build_site_data.py

WHAT THIS IS FOR. The documentation states results; these pages let a reader
check them. Two of them:

  * the specification curve, every combination of the five analysis choices with
    the decline it produces, drawn the way Simonsohn et al. draw one: estimates
    sorted, and underneath a matrix of which choice is active where. A grid, not
    a vote.
  * the contact sheet, one cell per day of every season, carrying what each
    instrument saw and whether they agreed.

WHY IT IS GENERATED RATHER THAN COMMITTED. Everything here is derived from files
already in archive/reprocessed_2026, and a second copy in the repository is a
second thing that can go stale. The Pages workflow runs this before mkdocs, and
`make docs` runs it before serving.

WHAT IT REFUSES TO DO. It never merges instruments into one series. Sentinel-2
is the record; Landsat is a second optical opinion measured to agree with it
(82 same-day pairs, correlation 0.987, RMSE 0.078, see landsat-crosscheck.md);
the thermal band answers a different question entirely, and the radar answers a
third. Each day carries them separately, and the page draws them separately.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "archive" / "reprocessed_2026"
OUT = ROOT / "docs" / "assets" / "data"

# The window the analysis measures over. Day 53 is 22 February, day 180 is
# 29 June. The charts in the story draw a slightly wider window; this is the one
# every published figure is computed over.
SEASON_START = 53
SEASON_END = 180

# Seasons the Sentinel-2 record covers. Landsat reaches further back, and the
# contact sheet says so, but it is not the same record: see the note on
# `reach_note` below.
FIRST_SEASON = 2017
LAST_SEASON = 2026


def rows(name: str) -> list[dict[str, str]]:
    with (ARCHIVE / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def truthy(value: Optional[str]) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def doy_of(iso: str) -> int:
    y, m, d = (int(part) for part in iso[:10].split("-"))
    return (date(y, m, d) - date(y, 1, 1)).days + 1


def iso_of(season: int, doy: int) -> str:
    return (date(season, 1, 1) + timedelta(days=doy - 1)).isoformat()


# --------------------------------------------------------------- specification


def specification_curve() -> dict[str, Any]:
    """Every combination of the five analysis choices, with its answer.

    The four negative estimates all sit in one corner of the grid, and both
    extremes are driven by the median aggregate. That is a fact about the grid's
    shape and it is the reason this is drawn as a curve with a choice matrix
    rather than reported as "116 of 120 show a decline": the latter reads as a
    vote among independent analyses, and these are not independent.
    """
    table = rows("specification_curve.csv")
    points: list[dict[str, Any]] = []
    for row in table:
        decline = number(row["decline_percent"])
        p = number(row["permutation_p"])
        if decline is None or p is None:
            continue
        points.append(
            {
                "series": row["series"],
                "window": row["window"],
                "split": int(row["split"]),
                "aggregate": row["aggregate"],
                "weighting": row["weighting"],
                "early": int(row["seasons_early"]),
                "late": int(row["seasons_late"]),
                "decline": round(decline, 2),
                "p": round(p, 4),
                "published": truthy(row["is_published"]),
            }
        )
    points.sort(key=lambda point: float(point["decline"]))

    published = next((p for p in points if p["published"]), None)
    declines: list[float] = [float(p["decline"]) for p in points]
    return {
        "points": points,
        "choices": {
            "series": sorted({p["series"] for p in points}),
            "window": sorted(
                {p["window"] for p in points}, key=lambda w: int(w.split("-")[0])
            ),
            "split": sorted({p["split"] for p in points}),
            "aggregate": sorted({p["aggregate"] for p in points}),
            "weighting": sorted({p["weighting"] for p in points}),
        },
        "published": published,
        "summary": {
            "n": len(points),
            "min": min(declines),
            "max": max(declines),
            "median": sorted(declines)[len(declines) // 2],
            "declining": sum(1 for d in declines if d > 0),
            "publishedRank": sorted(declines).index(float(published["decline"])) + 1
            if published
            else None,
        },
    }


# ---------------------------------------------------------------- contact sheet


def contact_sheet() -> dict[str, Any]:
    """One entry per day that any instrument measured, inside the season window.

    Four independent layers, deliberately not merged:

      s2       the record. frac is the measured value, filled and smooth are not
               measurements and are labelled as such.
      landsat  a second optical instrument, same mask, same indices, same
               thresholds. Corroboration, never part of the series.
      thermal  did the fjord radiate below the freezing point of seawater.
               Only meaningful where the chain claimed open water.
      sar      backscatter placed between that season's own fast ice and its own
               open water. "between" is a real answer and stays one.
    """
    days: dict[str, dict[str, Any]] = {}

    def cell(iso: str) -> dict[str, Any]:
        if iso not in days:
            days[iso] = {"date": iso, "season": int(iso[:4]), "doy": doy_of(iso)}
        return days[iso]

    # --- layer one: the record ------------------------------------------------
    for row in rows("daily_series.csv"):
        iso = row["date"][:10]
        doy = int(row["doy"])
        if not SEASON_START <= doy <= SEASON_END:
            continue
        measured = number(row["frac"])
        smooth = number(row["frac_smooth"])
        entry = cell(iso)
        entry["s2"] = {
            "measured": None if measured is None else round(measured, 4),
            # What the published curve plots. Kept apart from `measured` so a
            # cell can never claim a satellite saw something it did not.
            "curve": None if smooth is None else round(smooth, 4),
        }

    # per-scene diagnostics, so a day can explain its own decision
    for row in rows("summary.csv"):
        stamp = row["tile_id"].split("_")[2]
        iso = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
        if iso not in days:
            continue
        days[iso]["scene"] = {
            "id": row["tile_id"],
            "usable": truthy(row["usable"]),
            "clearPct": round(number(row["clear_pct"]) or 0, 3),
            "cloudPct": round(number(row["cloud_pct"]) or 0, 3),
            "sunElev": round(number(row["sun_elev"]) or 0, 1),
            "ndsiSolid": number(row["mean_ndsi_solid"]),
            "ndwiWater": number(row["mean_ndwi_water"]),
        }

    # --- layer two: a second optical instrument -------------------------------
    for row in rows("landsat_season_series.csv"):
        iso = row["day"][:10]
        doy = int(row["doy"])
        if not SEASON_START <= doy <= SEASON_END:
            continue
        ice = number(row["landsat_ice"])
        entry = cell(iso)
        entry["landsat"] = {
            "ice": None if ice is None else round(ice, 4),
            "share": round(number(row["landsat_share"]) or 0, 3),
            "sunElev": round(number(row["sun_elevation"]) or 0, 1),
            "scene": row["scene"],
        }

    # --- layer three: the thermal check ---------------------------------------
    for row in rows("thermal_audit.csv"):
        iso = row["day"][:10]
        if iso not in days:
            continue
        celsius = number(row["celsius"])
        days[iso]["thermal"] = {
            "kelvin": number(row["kelvin"]),
            "celsius": None if celsius is None else round(celsius, 1),
            # share of the fjord radiating below the freezing point of seawater
            "frozenShare": round(number(row["frozen_share"]) or 0, 3),
            "chainSaysOpen": truthy(row["chain_says_open"]),
            "contradicted": truthy(row["contradicted"]),
        }

    # --- layer four: the adjudicator ------------------------------------------
    verdicts = {row["day"][:10]: row for row in rows("sar_thermal_verdicts.csv")}
    for iso, row in verdicts.items():
        if iso not in days:
            continue
        position = number(row["pos"])
        days[iso]["sar"] = {
            "verdict": row["verdict"],
            # where the day sits between this season's own fast ice (1) and its
            # own open water (0); outside that span the value runs past the ends
            "position": None if position is None else round(position, 3),
            "valueDb": number(row["value_db"]),
            "iceRefDb": number(row["ice_ref_db"]),
            "waterRefDb": number(row["water_ref_db"]),
        }

    inside = [
        day
        for day in days.values()
        if FIRST_SEASON <= day["season"] <= LAST_SEASON
        and SEASON_START <= day["doy"] <= SEASON_END
    ]
    inside.sort(key=lambda day: day["date"])

    counts = {
        "days": len(inside),
        "s2": sum(1 for d in inside if d.get("s2", {}).get("measured") is not None),
        "landsat": sum(1 for d in inside if d.get("landsat")),
        "thermal": sum(1 for d in inside if d.get("thermal")),
        "sar": sum(1 for d in inside if d.get("sar")),
        "contradicted": sum(
            1 for d in inside if d.get("thermal", {}).get("contradicted")
        ),
        "chainSaysOpen": sum(
            1 for d in inside if d.get("thermal", {}).get("chainSaysOpen")
        ),
    }

    return {
        "window": {"start": SEASON_START, "end": SEASON_END},
        "seasons": list(range(FIRST_SEASON, LAST_SEASON + 1)),
        "days": inside,
        "counts": counts,
        "reachNote": reach_note(),
    }


def reach_note() -> dict[str, Any]:
    """What the archive holds before Sentinel-2, and why it is not a record.

    Counted rather than asserted, because the contact sheet has to show the
    difference between a scene existing and a day being measured. The reason the
    older instruments cannot simply be run is in landsat-crosscheck.md: MSS
    carries no shortwave infrared, so NDSI cannot be formed on it at all, and
    there is no same-overpass pair anywhere in this archive to carry a threshold
    across the TM boundary.
    """
    reach = rows("landsat_reach.csv")
    by_instrument: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"scenes": 0, "first": "9999", "last": "0000", "swir": False}
    )
    for row in reach:
        entry = by_instrument[row["instrument"]]
        entry["scenes"] += 1
        entry["swir"] = truthy(row["has_swir"])
        day = row["day"][:10]
        entry["first"] = min(entry["first"], day)
        entry["last"] = max(entry["last"], day)

    return {
        "instruments": [
            {"name": name, **values}
            for name, values in sorted(
                by_instrument.items(), key=lambda kv: kv[1]["first"]
            )
            if name != "?"
        ],
        # The two joins that do not exist, which is what stops the record from
        # reaching back rather than any shortage of scenes.
        "missingCalibration": ["TM to ETM+", "TM to OLI"],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for name, payload in (
        ("specification_curve.json", specification_curve()),
        ("contact_sheet.json", contact_sheet()),
    ):
        path = OUT / name
        path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        written.append((name, path.stat().st_size))

    sheet = contact_sheet()["counts"]
    print(f"wrote {len(written)} files to {OUT.relative_to(ROOT)}")
    for name, size in written:
        print(f"  {name:28} {size / 1024:8.1f} KB")
    print(
        f"  contact sheet: {sheet['days']} days, "
        f"{sheet['s2']} Sentinel-2, {sheet['landsat']} Landsat, {sheet['sar']} radar"
    )


if __name__ == "__main__":
    main()
