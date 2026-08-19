#!/usr/bin/env python3
"""Bring the classifier's own decisions into the repository, one raster per scene.

    python3 scripts/collect_class_rasters.py "/Volumes/Crucial X9/uummannaq-archive"

WHAT IT IS FOR. The contact sheet shows every scene the record used, and the
Sentinel-2 row shows the photograph. This adds the other half of that row: the
classification itself, on the grid the decision was actually made on.

WHERE IT COMES FROM. pipeline.py already writes these, through scene_export.py,
as a by-product of a full archive run. The 2026 reprocess wrote them to an
external drive and only one scene ever came back into the repository. This
copies the 617 that belong to usable scenes and leaves the other 486 behind.

WHAT IS NOT COPIED, and why. The same run wrote three other pictures per scene:
a six-axis matplotlib panel, a blended overlay, and a true-colour JPEG. All
three are the wrong thing to build an interface on, and scene_export.py says so
in its own docstring. The overlay in particular has the class colours already
mixed into the photograph and cannot be taken apart again: you cannot fade
between the picture and the decision, cannot hide a class, cannot read a class
back out of a blended pixel. The raster is class IDS, not colours, so the page
can recolour it, toggle classes, and count cells and get the number the CSV
reports. It is also 2.4 KB against the overlay's megabyte.

THE CHECK THAT MATTERS. A raster from a different run than the published tables
would be a picture of a different analysis, presented beside numbers it did not
produce. So every scene's class counts are compared against summary.csv before
it is copied, and a mismatch is refused rather than reported.

One field is allowed to differ, and only one. summary.csv carries `land_px` as
the static land mask, constant at 8869 cells for 613 of the 617 scenes, while
the export counts the cells that were still labelled land after cloud and nodata
took precedence. Those are two different quantities with one name. Solid, light,
water and cloud have to match exactly, and across all 617 scenes they do.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "archive" / "reprocessed_2026"
OUT = ROOT / "docs" / "assets" / "classes"

# CSV column to exported class name. `land_px` is deliberately absent: see the
# module docstring.
MUST_MATCH = {
    "solid_px": "ice_solid",
    "light_px": "ice_light",
    "water_px": "water",
    "cloud_px": "cloud",
}


def usable_scenes() -> dict[str, dict[str, str]]:
    with (ARCHIVE / "summary.csv").open(newline="", encoding="utf-8") as handle:
        return {
            row["tile_id"]: row
            for row in csv.DictReader(handle)
            if row["usable"] == "1"
        }


def exported(source: Path) -> dict[str, Path]:
    """Scene id to its class raster, skipping macOS AppleDouble shadows.

    The drive is exFAT, so every file has a `._name` sibling holding resource
    forks. Globbing without this filter finds twice as many scenes as exist and
    the extra half are eight-byte stubs.
    """
    return {
        path.name.split("_L1C_")[0] + "_L1C": path
        for path in (source / "quicklooks" / "classes").glob("*_classes.png")
        if not path.name.startswith("._")
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="the archive run directory")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    scenes = usable_scenes()
    have = exported(args.source)

    missing = sorted(set(scenes) - set(have))
    if missing:
        sys.exit(
            f"{len(missing)} usable scenes have no class raster, e.g. {missing[:3]}"
        )

    OUT.mkdir(parents=True, exist_ok=True)
    copied = skipped = 0
    index: dict[str, dict] = {}
    palettes: list[dict] = []
    for tile_id, row in sorted(scenes.items()):
        png = have[tile_id]
        meta = json.loads(
            png.with_name(png.name.replace("_classes.png", "_classes.json")).read_text()
        )
        counts = meta["classes"]
        wrong = [
            (column, int(row[column]), counts.get(name, 0))
            for column, name in MUST_MATCH.items()
            if int(row[column]) != counts.get(name, 0)
        ]
        if wrong:
            sys.exit(
                f"{tile_id} does not match summary.csv, so it is from another run: "
                + ", ".join(f"{c} table={a} raster={b}" for c, a, b in wrong)
            )

        index[tile_id] = {
            "grid": [meta["class_grid"]["width"], meta["class_grid"]["height"]],
            "image": [meta["scene_image"]["width"], meta["scene_image"]["height"]],
            "classes": counts,
        }
        palettes.append(meta["palette"])

        target = OUT / f"{tile_id}.png"
        if target.exists() and not args.force:
            skipped += 1
            continue
        shutil.copyfile(png, target)
        copied += 1

    # ONE index rather than 617 sidecars. The first version wrote a JSON beside
    # every raster and they came to 3.3 MB, as much as the pictures, because the
    # palette is the same seven colours 617 times over. The page never read them
    # at all: a paletted PNG carries its own colours, so the browser draws it
    # without help. What the file is actually for is the guardrail test, which
    # checks these counts against summary.csv, and the legend, which is one
    # palette for the whole record.
    if len({json.dumps(p, sort_keys=True) for p in palettes}) != 1:
        sys.exit("the class palette is not constant across the record")
    (OUT / "index.json").write_text(
        json.dumps({"palette": palettes[0], "scenes": index}, separators=(",", ":")),
        encoding="utf-8",
    )

    size = sum(f.stat().st_size for f in OUT.iterdir())
    print(
        f"{copied} copied, {skipped} already present, {len(scenes)} verified against "
        f"summary.csv\n{size / 1024 / 1024:.2f} MB in {OUT.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
