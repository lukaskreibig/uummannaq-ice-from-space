#!/usr/bin/env python3
"""Ask the catalogue what a reprocess would actually do, before it does it.

The classifier spends about 75 seconds per scene, so a full archive run is an
overnight job. Everything that can be known cheaply should be known before that
job starts: how many scenes there are, which MGRS tiles they come from, whether
any of them are the whole-planet-bounding-box scenes from other continents, and
how long the whole thing will take.

    AWS_NO_SIGN_REQUEST=YES python3 scripts/preflight.py \
        --start 2017-01-01 --end 2026-12-31 \
        --out out/archive/preflight.json

It writes a JSON inventory that scripts/check_summary.py later checks the
finished CSV against, so "did every scene make it" is a question with an
answer rather than a feeling.

Nothing here downloads pixels. It is a metadata query and it finishes in a few
minutes for the full archive, a few seconds for one season.
"""

from __future__ import annotations

import argparse
import collections
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

from uummannaq_ice.config import build_config
from uummannaq_ice.stac import aoi_coverage, bbox_of, fetch_tiles

# Mirrors backend/main.py FJORD_SUN_START / FJORD_SUN_END: outside this window
# the sun is too low over Uummannaq for a usable optical scene, and the story
# discards the days anyway.
SUN_START = 45
SUN_END = 180

KNOWN_TILES = {"22WDD", "21WXU"}

# Measured 2026-08-04: a clean ten-scene run took 61 s of wall clock and pulled
# 785 953 344 bytes, so 6.1 s and 78.6 MB per scene at 12.9 MB/s. The run is
# bound by bandwidth, so this number is really a property of the connection, not
# of the machine. Re-measure with one short window and pass the result in.
DEFAULT_SECONDS_PER_SCENE = 6.1
DEFAULT_MB_PER_SCENE = 78.6


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, help="Where to write the inventory JSON.")
    parser.add_argument(
        "--seconds-per-scene", type=float, default=DEFAULT_SECONDS_PER_SCENE
    )
    parser.add_argument(
        "--sun-window-only",
        action="store_true",
        help="Count only the days the story keeps (day of year 45 to 180).",
    )
    args = parser.parse_args()

    logging.basicConfig(format="%(levelname)-7s %(message)s", level=logging.WARNING)

    config = build_config(
        start_date=args.start,
        end_date=args.end,
        output_dir=(args.out.parent if args.out else Path("out")),
        log_level="WARNING",
    )
    aoi_bbox = bbox_of(dict(config.search_aoi))

    started = time.time()
    tiles = fetch_tiles(config)
    query_seconds = time.time() - started

    rows = []
    for item in tiles:
        assert item.datetime is not None
        rows.append(
            {
                "id": item.id,
                "mgrs": item.id.split("_")[1],
                "datetime": item.datetime.isoformat(),
                "year": item.datetime.year,
                "doy": item.datetime.timetuple().tm_yday,
                "baseline": str(item.properties.get("s2:processing_baseline")),
                "eo_cloud_cover": item.properties.get("eo:cloud_cover"),
                "bbox": list(item.bbox) if item.bbox else None,
                "aoi_coverage": (
                    round(aoi_coverage(item.bbox, aoi_bbox), 4) if aoi_bbox else None
                ),
            }
        )

    in_window = [r for r in rows if SUN_START <= r["doy"] <= SUN_END]
    selected = in_window if args.sun_window_only else rows

    per_year_all = collections.Counter(r["year"] for r in rows)
    per_year_window = collections.Counter(r["year"] for r in in_window)
    tile_mix = collections.Counter(r["mgrs"] for r in rows)
    baselines = collections.Counter(r["baseline"] for r in rows)

    foreign = [r for r in rows if r["mgrs"] not in KNOWN_TILES]
    # A bounding box wider than 90 degrees of longitude is not a Sentinel-2
    # footprint, it is a catalogue record that wraps the antimeridian. Those are
    # the scenes that reach a Greenland AOI from the North Pacific.
    wraparound = [r for r in rows if r["bbox"] and (r["bbox"][2] - r["bbox"][0]) > 90]

    seconds = len(selected) * args.seconds_per_scene
    gigabytes = len(selected) * DEFAULT_MB_PER_SCENE / 1000
    payload = {
        "estimated_download_gb": round(gigabytes, 1),
        "start_date": args.start.isoformat(),
        "end_date": args.end.isoformat(),
        "stac_query_seconds": round(query_seconds, 1),
        "scenes_total": len(rows),
        "scenes_in_sun_window": len(in_window),
        "scenes_to_process": len(selected),
        "scenes_per_year": {str(y): n for y, n in sorted(per_year_all.items())},
        "scenes_in_sun_window_per_year": {
            str(y): n for y, n in sorted(per_year_window.items())
        },
        "tile_mix": dict(tile_mix.most_common()),
        "processing_baselines": dict(sorted(baselines.items())),
        "foreign_tiles": [
            {
                "id": r["id"],
                "mgrs": r["mgrs"],
                "datetime": r["datetime"],
                "bbox": r["bbox"],
            }
            for r in foreign
        ],
        "wraparound_bboxes": [r["id"] for r in wraparound],
        "seconds_per_scene": args.seconds_per_scene,
        "estimated_seconds": round(seconds),
        "estimated_hours": round(seconds / 3600, 1),
        "scenes": rows,
    }

    print(f"STAC query took {query_seconds:.1f}s")
    print(f"scenes offered          {len(rows)}")
    print(
        f"scenes in the sun window {len(in_window)}  (day of year {SUN_START} to {SUN_END})"
    )
    print(f"scenes this run would do {len(selected)}")
    print(f"tile mix                 {dict(tile_mix.most_common())}")
    print(f"per year (sun window)    {dict(sorted(per_year_window.items()))}")
    print(
        f"estimated wall clock     {seconds / 3600:.1f} h at "
        f"{args.seconds_per_scene:.1f} s per scene"
    )
    print(
        f"estimated download       {gigabytes:.0f} GB at "
        f"{DEFAULT_MB_PER_SCENE:.0f} MB per scene"
    )

    if foreign:
        print(
            f"\n!! {len(foreign)} scene(s) from an MGRS tile that does not see this fjord:"
        )
        for r in foreign:
            print(
                f"   {r['id']}  {r['datetime']}  bbox={r['bbox']}  coverage={r['aoi_coverage']}"
            )
        print(
            "   These pass the AOI coverage floor because their catalogue bounding "
            "box spans the planet. They will land in the record as ice-free days."
        )
    if len(tile_mix) > 1:
        dominant, n = tile_mix.most_common(1)[0]
        print(
            f"\n!! the run would mix {len(tile_mix)} MGRS tiles, {dominant} on "
            f"{n / len(rows):.0%} of days. The land mask is georeferenced now, "
            f"so it lands on the right geography either way, but the two tiles "
            f"still clip the AOI onto different pixel grids and different "
            f"incidence geometry. Compare per-tile season means before "
            f"publishing: on the previous archive the two tiles differed by "
            f"0.14 in the spring mean, which was a third of the headline."
        )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"\nwrote {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
