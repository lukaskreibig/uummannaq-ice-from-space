#!/usr/bin/env python3
"""Shadow does not just darken a surface. It changes its colour, and that shows.

    python3 scripts/shadow_discriminant.py

shadow_bias.py measures how much ice this project reads as water at low sun.
This asks the next question: is there anything in the two indices the classifier
already computes that tells shadowed ice apart from the open water it is being
confused with? Reading only committed artefacts, so it costs nothing.

THE PHYSICS, and it is the whole finding. A shadow is not switched off. It is lit
by skylight, and skylight is Rayleigh scattered, so its intensity falls off
steeply with wavelength. Green keeps a third of its light, the near infrared
about a tenth, and the shortwave infrared at 1.6 um almost nothing at all. Every
index with green in the numerator therefore RISES in shadow while the absolute
brightness collapses. Shadowed ice does not look like darker ice. It looks
simultaneously snowier and wetter than any sunlit surface can.

That is testable against surfaces whose answer is not in question, and the two
numbers it produces are printed below.

WHAT IT DOES NOT DO. It does not separate mountain shadow from wet or thin ice,
which sits between the two. That overlap is not a defect of the discriminant so
much as a statement about what it detects: both are ice that the brightness gate
rejects, and neither is open water. It is also measured on one February scene,
the only one whose per cell rasters are committed, against endmembers from three
others. Deploying it means reprocessing the archive with the rule in place and
validating the result against the thermal and radar controls, which is a run this
project has not made. Nothing published here depends on it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPECTRA = ROOT / "out/archive/endmember_spectra.csv"
# The one scene whose per cell classes and indices are committed. 19 February
# 2017, a day on which this fjord has never in the record been open.
SCENE = ROOT / (
    "out/panel_rerun/quicklooks/classes/S2A_22WDD_20170219_0_L1C_20170219T153251"
)
# Where a cut would have to sit to be above every sunlit surface measured here.
CANDIDATE_CUT = 0.94


def ndsi(green: float, swir: float) -> float:
    return (green - swir) / (green + swir)


def ndwi(green: float, nir: float) -> float:
    return (green - nir) / (green + nir)


def ndsi_spread(green: float, swir: float, s_green: float, s_swir: float) -> float:
    """The spread of NDSI, propagated from the two band spreads it is built on."""
    denom = (green + swir) ** 2
    return float(np.hypot(2 * swir / denom * s_green, 2 * green / denom * s_swir))


def endmembers(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    rows = []
    labels = {
        "water": "open water, July 2019",
        "ice": "fast ice, April 2018",
        "ice_2023": "fast ice, March 2023",
        "wet_ice": "ice cells, April 2023",
        "wet": "contested cells, April 2023",
    }
    for key, label in labels.items():
        block = frame[frame.member == key].set_index("band")
        r, s = block.reflectance, block.spread
        rows.append(
            {
                "surface": label,
                "green": float(r["green"]),
                "nir": float(r["nir"]),
                "swir16": float(r["swir16"]),
                "ndsi": ndsi(r["green"], r["swir16"]),
                "ndwi": ndwi(r["green"], r["nir"]),
                "ndsi_spread": ndsi_spread(
                    r["green"], r["swir16"], s["green"], s["swir16"]
                ),
            }
        )
    return pd.DataFrame(rows)


def scene_cells(
    base: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """The class codes, the two indices, and the names the codes stand for."""
    meta = json.loads(base.with_name(base.name + "_classes.json").read_text())
    names = list(meta["palette"])
    classes = np.array(Image.open(base.with_name(base.name + "_classes.png")))
    arrays = np.load(base.with_name(base.name + "_indices.npz"))
    return (
        classes,
        arrays["ndsi"].astype("float32"),
        arrays["ndwi"].astype("float32"),
        names,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "out/archive")
    args = parser.parse_args(argv)

    table = endmembers(SPECTRA)
    print("1. What the two indices read on surfaces whose answer is not in question")
    print("=" * 78)
    print(
        f"{'surface':32s}{'green':>8s}{'nir':>8s}{'swir16':>9s}{'NDSI':>8s}{'NDWI':>8s}"
    )
    for row in table.itertuples():
        print(
            f"{row.surface:32s}{row.green:8.3f}{row.nir:8.3f}{row.swir16:9.4f}"
            f"{row.ndsi:8.3f}{row.ndwi:8.3f}"
        )

    ice_ndsi = float(table.loc[table.surface.str.startswith("fast ice"), "ndsi"].mean())
    water = table[table.surface.str.startswith("open water")].iloc[0]
    print()
    print(
        f"  NDSI separates fast ice ({ice_ndsi:.3f}) from open water ({water.ndsi:.3f})\n"
        f"  by {abs(ice_ndsi - water.ndsi):.3f}, which is nothing. Snow and water both\n"
        "  absorb the shortwave infrared, so the index that is supposed to find snow\n"
        "  cannot see the difference. That is the reason a brightness gate exists at\n"
        "  all, and the reason losing brightness costs the classifier everything."
    )

    classes, scene_ndsi, scene_ndwi, names = scene_cells(SCENE)
    called_water = classes == names.index("water")
    called_ice = classes == names.index("ice_solid")

    print()
    print("2. The same two indices on 19 February 2017, per cell")
    print("=" * 78)
    print(
        f"{'the chain called it':32s}{'cells':>8s}{'NDSI med':>10s}{'NDSI p5':>9s}{'NDWI med':>10s}"
    )
    rows = []
    for label, mask in (("water", called_water), ("ice_solid", called_ice)):
        print(
            f"{label:32s}{int(mask.sum()):8d}{np.median(scene_ndsi[mask]):10.3f}"
            f"{np.percentile(scene_ndsi[mask], 5):9.3f}{np.median(scene_ndwi[mask]):10.3f}"
        )
        rows.append(
            {
                "source": "2017-02-19",
                "surface": f"chain called {label}",
                "cells": int(mask.sum()),
                "ndsi": float(np.median(scene_ndsi[mask])),
                "ndsi_p5": float(np.percentile(scene_ndsi[mask], 5)),
                "ndwi": float(np.median(scene_ndwi[mask])),
            }
        )

    p5 = float(np.percentile(scene_ndsi[called_water], 5))
    sigmas = (p5 - water.ndsi) / water.ndsi_spread
    print()
    print(
        f"  The fjord is frozen shore to shore on this day. The cells the chain calls\n"
        f"  water read NDSI {np.median(scene_ndsi[called_water]):.3f}, ABOVE the ice beside them and\n"
        f"  above open water itself. Even the fifth percentile, {p5:.3f}, sits {sigmas:.0f} spreads\n"
        f"  above the open water endmember of {water.ndsi:.3f} +/- {water.ndsi_spread:.3f}. No surface lit by\n"
        "  the sun reaches there. Skylight is the only light that produces it."
    )

    print()
    print("3. Would a cut work, and against what")
    print("=" * 78)
    print(
        f"  A cut at NDSI {CANDIDATE_CUT}, applied only to cells already called water:"
    )
    caught = float((scene_ndsi[called_water] > CANDIDATE_CUT).mean())
    print(f"    catches {caught:.1%} of the false water on this frozen February scene")
    for row in table.itertuples():
        margin = (
            (CANDIDATE_CUT - row.ndsi) / row.ndsi_spread
            if row.ndsi_spread
            else float("nan")
        )
        verdict = "clear" if margin > 2 else "OVERLAPS"
        print(
            f"    vs {row.surface:30s} NDSI {row.ndsi:.3f} +/- {row.ndsi_spread:.3f}"
            f"  {margin:+5.1f} spreads  {verdict}"
        )

    print()
    print(
        "  Open water in July and clean fast ice in April sit far below the cut, at\n"
        "  five and thirteen spreads. Everything measured close to break-up does not:\n"
        "  the March 2023 ice, the April 2023 ice and the contested cells all carry\n"
        "  spreads wide enough to cross it, because a fjord about to open is a mixed\n"
        "  surface and its endmember is a mixed number.\n"
        "\n"
        "  That overlap is worth being precise about rather than apologetic. Wet ice\n"
        "  is ICE. A rule that pulls both mountain shadow and wet ice out of the water\n"
        "  class removes two instances of the same error, which is dark ice failing a\n"
        "  brightness gate. What it would also do is move the break-up date, and that\n"
        "  is the part a deployment has to defend rather than assume."
    )
    print()
    print(
        "  What it cannot do is help on a day when the fjord is genuinely open AND\n"
        "  shadowed, because open water in shadow inflates the same way. That window\n"
        "  is small here, since the fjord opens in the half of the year when the sun\n"
        "  is high and the shadow is short, but small is not zero and it is the first\n"
        "  thing a deployment would have to measure."
    )

    print()
    print("4. What this is not")
    print("=" * 78)
    print(
        "  One scene, against endmembers from three others. It is a hypothesis with a\n"
        "  measured basis, not a correction. Turning it into one means reprocessing\n"
        "  the archive with the rule in place and checking the result against the\n"
        "  thermal and radar controls that already exist, and nothing published by\n"
        "  this project uses it today."
    )

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "shadow_discriminant.csv"
    frame = pd.concat([table.assign(source="endmember"), pd.DataFrame(rows)])
    frame.to_csv(path, index=False)
    print(f"\nwritten to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
