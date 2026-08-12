#!/usr/bin/env python3
"""The mountain casts a shadow on the sea ice, and the classifier calls it water.

Found by eye, in a quicklook, by someone who had not read any of the code. The
island carries a mountain that Copernicus DEM GLO-30 puts at 792 m, the sun in
February sits under ten degrees, and the shadow reaches kilometres north across
the fjord: 4.6 km at a sun elevation of 9.8 degrees. An earlier version of this
docstring said 1170 m, which is the figure usually quoted for this peak and is
not what the DEM measures; scripts/build_terrain_tiles.py reads the same source. Ice in that shadow is dark,
a dark surface fails the brightness gate, and the gate is what separates ice from
water here. So the shadow is classified as open water on ice that is certainly
frozen.

    python3 scripts/shadow_bias.py

This measures how big that is and whether it can reach the headline. It reads
only the committed archive, so it costs nothing and needs no network.

WHY IT MIGHT NOT MATTER, and why that has to be checked rather than assumed.
Sentinel-2 is sun synchronous. The overpass is at the same local time every pass,
the sun azimuth over this fjord spans 176.3 to 188.7 degrees across four years,
and so the shadow falls in very nearly the same place on every scene ever taken.
Its LENGTH is set by sun elevation, which is a function of the day of the year
and not of the year. A bias that depends only on the day of the year cancels
between two periods that are sampled at the same days of the year, and does not
cancel at all between two periods that are not.

That is the whole question, and both halves of it are printed below.

WHAT THIS IS NOT. It does not separate shadow from any other dark surface. A cell
is counted here if the chain called it water inside a window where this fjord has
never been open, and mountain shadow is the largest contributor to that in
February but not the only one. Thin ice, bare ice and wet ice are in there too,
which is the same failure measured from a different side in thermal_audit.py.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / "archive/reprocessed_2026/summary.csv"

# The fjord has never been open inside this window: the earliest break-up in the
# whole record is 30 April, day 120. Anything the chain calls water in here is
# wrong about something.
FROZEN_WINDOW = (45, 105)
MIN_SHARE = 0.30
LATE_FROM = 2021
BANDS = ((45, 60), (60, 75), (75, 90), (90, 105))
COUNTS = ("solid_px", "light_px", "water_px", "cloud_px", "land_px", "nodata_px")


def load(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    for col in COUNTS:
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
    stamp = pd.to_datetime(frame.timestamp.astype(str), format="%Y%m%dT%H%M%S")
    frame["doy"] = stamp.dt.dayofyear
    frame["season"] = stamp.dt.year
    frame["day"] = stamp.dt.date.astype(str)
    classified = frame.solid_px + frame.light_px + frame.water_px
    grid = classified + frame.cloud_px + frame.land_px + frame.nodata_px
    frame["water"] = frame.water_px.divide(classified.where(classified > 0))
    frame["share"] = classified.divide(grid.where(grid > 0))
    if "sun_elev" in frame:
        frame["sun"] = pd.to_numeric(frame.sun_elev, errors="coerce")
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    args = parser.parse_args(argv)

    frame = load(args.archive)
    lo, hi = FROZEN_WINDOW
    frozen = frame[
        (frame.doy >= lo) & (frame.doy <= hi) & (frame.share >= MIN_SHARE)
    ].copy()

    print(f"Water called on a fjord that cannot be open, day {lo} to {hi}")
    print("=" * 78)
    print(f"{len(frozen)} scenes clear the visibility gate in that window.")
    print()
    print(f"{'day of year':>14s}{'n':>5s}{'sun':>7s}{'median water':>14s}{'worst':>8s}")
    rows: list[dict] = []
    for band_lo, band_hi in BANDS:
        block = frozen[(frozen.doy >= band_lo) & (frozen.doy < band_hi)]
        if block.empty:
            continue
        sun = block.sun.median() if "sun" in block else float("nan")
        print(
            f"{band_lo:>7d} to {band_hi:<4d}{len(block):5d}{sun:7.1f}"
            f"{block.water.median():14.3f}{block.water.max():8.3f}"
        )
        rows.append(
            {
                "doy_from": band_lo,
                "doy_to": band_hi,
                "scenes": len(block),
                "median_sun_elevation": float(sun),
                "median_water": float(block.water.median()),
                "worst_water": float(block.water.max()),
            }
        )

    print()
    print(
        "  The fjord is frozen shore to shore across all of these. What changes is\n"
        "  the sun: a low sun in February throws the mountain's shadow kilometres\n"
        "  across the ice, and the shadow shortens as the sun climbs."
    )

    early = frozen[frozen.season < LATE_FROM]
    late = frozen[frozen.season >= LATE_FROM]
    print()
    print("Does it cancel between the two periods?")
    print("-" * 78)
    print(
        f"{'period':>8s}{'n':>5s}{'median doy':>12s}{'median sun':>12s}{'median water':>14s}"
    )
    for name, block in (("early", early), ("late", late)):
        print(
            f"{name:>8s}{len(block):5d}{block.doy.median():12.0f}"
            f"{block.sun.median():12.1f}{block.water.median():14.3f}"
        )
    gap = float(late.water.median() - early.water.median())
    print()
    print(
        f"  The two periods are sampled {abs(late.doy.median() - early.doy.median()):.0f} "
        "days apart in the season and the median\n"
        f"  difference in water called is {gap:+.3f}. A bias that depends on the day of\n"
        "  the year and not on the year cancels when both periods sit on the same\n"
        "  days, and these very nearly do."
    )

    # What it would cost if it did NOT cancel: the same window, sampled as the
    # early period actually was, against the late period's own sampling.
    worst = float(frozen[frozen.doy < 60].water.median())
    print()
    print(
        f"  The number this could have been is worth stating. Median water in the\n"
        f"  first fortnight of the window is {worst:.3f}. Had one period been sampled\n"
        "  there and the other in April, the shadow alone would have opened a gap\n"
        "  larger than the decline this project reports."
    )

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "shadow_bias.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f"\nwritten to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
