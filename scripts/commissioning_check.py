#!/usr/bin/env python3
"""Was Landsat 8 wrong in March 2013, or was the fjord?

landsat_season_series.py drops the 2013 season, and the reason it gives is a
date: USGS puts Landsat 8 in its operational WRS-2 orbit on 11 April 2013, and
the four scenes that read 5 to 15 percent ice over a fjord every other year calls
frozen are all earlier. That argument is circumstantial three times over. It
rests on a published date, on the readings being physically implausible, and on
the first scene after the boundary reading 0.83. None of that is a measurement of
the scenes themselves.

There is a measurement available, and it is the same one the archive census turned
up as the only ETM+ against OLI bridge in forty years:

    2013-03-30   ETM+  15h UTC  sun 23.0  cloud 1.0
    2013-03-30   OLI   15h UTC  sun 23.0  cloud 0.8

Same fjord, same hour, same sun elevation, both nearly cloud free, and Landsat 7
had been in normal operations since 1999. If ETM+ reads fast ice on that day and
OLI reads open water, the commissioning scenes are miscalibrated and the exclusion
is measured rather than inferred. If both read the same thing, the exclusion is
wrong and 2013 belongs in the series.

    AWS_REQUEST_PAYER=requester python3 scripts/commissioning_check.py

Two scenes, so it costs a fraction of a cent.

The one thing this comparison needed before it could be run: read_scene had OLI's
band numbers hard coded. The STAC asset names are stable across instruments but
the MTL rescaling keys are not, because OLI carries an extra coastal aerosol band
at the front and everything after it shifts by one. Reading ETM+ with OLI's
numbers would have applied band 3's gain to band 2, band 5's to band 4 and band
6's to band 5, and produced a wrong answer that looked like a right one. The band
map is now keyed on the instrument prefix.

Note on Landsat 7 in 2013: the scan line corrector failed in May 2003, so ETM+
scenes from then on carry wedge shaped gaps that widen towards the swath edge.
Those pixels arrive as fill and are excluded by the QA fill bit, so they cost
coverage and nothing else. The classified share reported below is the honest one.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from landsat_l1_crosscheck import (  # noqa: E402
    AOI,
    USGS_STAC,
    classify,
    read_scene,
)

LOGGER = logging.getLogger("commissioning_check")

PAIR_DAY = "2013-03-30"
# What fast ice reads over this fjord, measured on days whose answer is not in
# doubt. From endmember_separability.py and the April control days.
FAST_ICE_GREEN = (0.44, 0.74)
FAST_ICE_NIR = (0.44, 0.79)

# The thermal question, and its controls. Reflectance cannot separate dark thin
# ice from open water, because both are dark; a thermometer can, because seawater
# under ice cannot go below its freezing point of about 271.3 K while an ice
# surface radiating to a cold sky in March goes far below it. Every control comes
# from 2013 itself, so no cross-year difference can be mistaken for the answer.
THERMAL_DAYS = [
    ("2013-03-22", "in question", 0.052),
    ("2013-03-30", "in question", 0.098),
    ("2013-04-04", "in question", 0.151),
    ("2013-04-09", "in question", 0.148),
    ("2013-04-23", "control, frozen", 0.827),
    ("2013-05-29", "control, open", 0.001),
    ("2013-06-12", "control, open", 0.001),
]
SEAWATER_FREEZING_K = 271.35  # about -1.8 C at 34 psu


def scenes_on(day: str) -> list:
    from pystac_client import Client

    client = Client.open(USGS_STAC)
    found = []
    for item in client.search(
        collections=["landsat-c2l1"], bbox=AOI, datetime=f"{day}/{day}", limit=100
    ).items():
        if item.id[:2] in ("LC", "LE", "LT"):
            found.append(item)
    return sorted(found, key=lambda i: i.id)


def surface(bands, land) -> dict:
    """Median reflectance over the water mask, ignoring fill and cloud."""
    qa = bands["qa_pixel"]
    fill = (qa & 1) > 0
    obscured = (qa & (1 << 1) | qa & (1 << 3) | qa & (1 << 4)) > 0
    usable = ~land & ~fill & ~obscured
    out: dict[str, float] = {"usable_cells": float(usable.sum())}
    for name in ("green", "nir08", "swir16"):
        values = bands[name][usable]
        values = values[np.isfinite(values)]
        out[name] = float(np.median(values)) if values.size else float("nan")
    return out


def brightness_temperature(item, land_source) -> tuple[float, int, str, float]:
    """Brightness temperature over the fjord water: median, cells, asset, share.

    Level 1 thermal is digital numbers. RADIANCE_MULT and RADIANCE_ADD give
    at-sensor spectral radiance, and the K1 and K2 constants in the MTL turn that
    into brightness temperature. No sun-angle correction here and no emissivity
    correction: this is what the sensor saw, and for separating ice from water a
    difference of fifteen kelvin does not need either.

    The fourth return value is the one that carries the argument. A median says
    what the typical cell did and goes quiet on a fjord that is half frozen; the
    SHARE of cells radiating below the freezing point of seawater is a number of
    the same kind as the ice fraction the chain reports, so the two can be put
    side by side and disagree in a way that means something.
    """
    import json

    import boto3
    import rasterio
    from landsat_l1_crosscheck import BOUNDS
    from rasterio.enums import Resampling
    from rasterio.warp import reproject
    from rasterio.windows import from_bounds

    asset = "lwir11" if item.id.startswith("LC") else "lwir"
    band = "10" if item.id.startswith("LC") else "6_VCID_1"

    s3 = boto3.client("s3", region_name="us-west-2")

    def s3href(name: str) -> str:
        return item.assets[name].extra_fields["alternate"]["s3"]["href"]

    bucket, key = s3href("MTL.json").replace("s3://", "").split("/", 1)
    meta = json.loads(
        s3.get_object(Bucket=bucket, Key=key, RequestPayer="requester")["Body"].read()
    )["LANDSAT_METADATA_FILE"]
    rescale = meta["LEVEL1_RADIOMETRIC_RESCALING"]
    thermal = meta["LEVEL1_THERMAL_CONSTANTS"]
    mult = float(rescale[f"RADIANCE_MULT_BAND_{band}"])
    add = float(rescale[f"RADIANCE_ADD_BAND_{band}"])
    k1 = float(thermal[f"K1_CONSTANT_BAND_{band}"])
    k2 = float(thermal[f"K2_CONSTANT_BAND_{band}"])

    with rasterio.open(s3href(asset)) as src:
        window = from_bounds(*BOUNDS, src.transform)
        arr = src.read(1, window=window)
        transform, crs = src.window_transform(window), src.crs
    with rasterio.open(s3href("qa_pixel")) as src:
        qw = from_bounds(*BOUNDS, src.transform)
        qa = src.read(1, window=qw).astype("uint16")

    land = np.zeros(arr.shape, dtype="uint8")
    reproject(
        source=land_source["array"],
        destination=land,
        src_transform=land_source["transform"],
        src_crs=land_source["crs"],
        dst_transform=transform,
        dst_crs=crs,
        resampling=Resampling.nearest,
    )
    if qa.shape != arr.shape:  # ETM+ thermal is resampled to the same grid
        qa = np.zeros(arr.shape, dtype="uint16")

    obscured = (qa & (1 << 1) | qa & (1 << 3) | qa & (1 << 4)) > 0
    usable = (land <= 127) & ~obscured & (arr > 0)
    if not usable.any():
        return float("nan"), 0, asset, float("nan")

    radiance = mult * arr[usable].astype("float64") + add
    radiance = radiance[radiance > 0]
    if not radiance.size:
        return float("nan"), 0, asset, float("nan")
    kelvin = k2 / np.log(k1 / radiance + 1.0)
    frozen_share = float((kelvin < SEAWATER_FREEZING_K).mean())
    return float(np.median(kelvin)), int(usable.sum()), asset, frozen_share


def thermal_series(land_source, out: Path) -> None:
    """Ask a thermometer what reflectance cannot answer."""
    import pandas as pd

    rows: list[dict] = []
    for day, role, ice in THERMAL_DAYS:
        for item in scenes_on(day):
            try:
                kelvin, cells, asset, frozen = brightness_temperature(item, land_source)
            except Exception as exc:  # pragma: no cover - network-driven
                LOGGER.warning("%s %s: %s", day, item.id, type(exc).__name__)
                continue
            if not np.isfinite(kelvin):
                continue
            rows.append(
                {
                    "day": day,
                    "role": role,
                    "reported_ice": ice,
                    "scene": item.id,
                    "instrument": "OLI" if item.id.startswith("LC") else "ETM+",
                    "asset": asset,
                    "kelvin": kelvin,
                    "celsius": kelvin - 273.15,
                    "cells": cells,
                }
            )
    if not rows:
        print("no thermal data")
        return
    frame = pd.DataFrame(rows)
    frame.to_csv(out / "commissioning_thermal.csv", index=False)

    print()
    print("What the thermal band says about the same fjord")
    print("=" * 78)
    print(
        f"{'day':12s}{'role':18s}{'reported ice':>13s}{'kelvin':>9s}"
        f"{'celsius':>9s}  instrument"
    )
    for r in rows:
        print(
            f"{r['day']:12s}{r['role']:18s}{r['reported_ice']:13.3f}"
            f"{r['kelvin']:9.1f}{r['celsius']:9.1f}  {r['instrument']}"
        )
    print()
    print(
        f"Seawater at this salinity freezes at about {SEAWATER_FREEZING_K:.1f} K "
        f"({SEAWATER_FREEZING_K - 273.15:.1f} C).\nOpen water cannot radiate "
        "colder than that. An ice surface can, and in March it does."
    )
    questioned = [r["kelvin"] for r in rows if r["role"] == "in question"]
    frozen_ctrl = [r["kelvin"] for r in rows if r["role"] == "control, frozen"]
    open_ctrl = [r["kelvin"] for r in rows if r["role"] == "control, open"]
    if questioned and frozen_ctrl and open_ctrl:
        q, f, o = np.mean(questioned), np.mean(frozen_ctrl), np.mean(open_ctrl)
        print()
        print(f"  in question    {q:6.1f} K")
        print(f"  frozen control {f:6.1f} K")
        print(f"  open control   {o:6.1f} K")
        print()
        if abs(q - f) < abs(q - o):
            print(
                "  The days in question sit with the frozen control, not with the open\n"
                "  one. The fjord was frozen and the chain read it as water, which is\n"
                "  the dark-surface failure this project has already measured on wet\n"
                "  April days, appearing here across a whole early season."
            )
        else:
            print(
                "  The days in question sit with the open control. The fjord really was\n"
                "  open or nearly so in March 2013, and the low readings are correct."
            )


def main(argv: list[str] | None = None) -> int:
    import rasterio

    from uummannaq_ice.assets import default_landmask_path

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--day", default=PAIR_DAY)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("rasterio").setLevel(logging.ERROR)
    logging.getLogger("botocore").setLevel(logging.WARNING)

    with rasterio.open(default_landmask_path()) as lm:
        land_source = {"array": lm.read(1), "transform": lm.transform, "crs": lm.crs}

    items = scenes_on(args.day)
    if not items:
        print(f"no Landsat scene on {args.day}")
        return 1

    rows: list[dict] = []
    for item in items:
        instrument = {"LC": "OLI", "LE": "ETM+", "LT": "TM"}[item.id[:2]]
        try:
            bands, land, sun = read_scene(item, land_source)
            got = classify(bands, land)
            look = surface(bands, land)
        except Exception as exc:  # pragma: no cover - network-driven
            LOGGER.warning("%s: %s: %s", item.id, type(exc).__name__, exc)
            continue
        rows.append(
            {
                "scene": item.id,
                "instrument": instrument,
                "sun_elevation": sun,
                "cloud": item.properties.get("eo:cloud_cover"),
                **got,
                **look,
            }
        )

    if not rows:
        print("nothing could be read")
        return 1

    import pandas as pd

    frame = pd.DataFrame(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "commissioning_check.csv"
    frame.to_csv(path, index=False)

    print(f"Both instruments over Uummannaq on {args.day}")
    print("=" * 78)
    print(
        f"{'instrument':11s}{'sun':>6s}{'cloud':>7s}{'share':>7s}{'ice':>7s}"
        f"{'green':>8s}{'NIR':>8s}{'SWIR':>8s}  scene"
    )
    for r in rows:
        print(
            f"{r['instrument']:11s}{r['sun_elevation']:6.1f}{r['cloud'] or 0:7.1f}"
            f"{r['landsat_share']:7.2f}{r['landsat_ice']:7.3f}"
            f"{r['green']:8.3f}{r['nir08']:8.3f}{r['swir16']:8.3f}  {r['scene'][:25]}"
        )
    print()
    print(
        f"Fast ice over this fjord reads {FAST_ICE_GREEN[0]:.2f} to "
        f"{FAST_ICE_GREEN[1]:.2f} in green and {FAST_ICE_NIR[0]:.2f} to "
        f"{FAST_ICE_NIR[1]:.2f} in the\nnear infrared, and the brightness gate "
        "the pipeline applies is green above 0.10\nand NIR above 0.17."
    )

    oli = [r for r in rows if r["instrument"] == "OLI"]
    other = [r for r in rows if r["instrument"] != "OLI"]
    if oli and other:
        a, b = oli[0], other[0]
        print()
        print("The verdict")
        print("-" * 78)
        ratio_g = b["green"] / a["green"] if a["green"] else float("nan")
        ratio_n = b["nir08"] / a["nir08"] if a["nir08"] else float("nan")
        print(
            f"  {b['instrument']} over OLI: green {ratio_g:.2f}x, "
            f"near infrared {ratio_n:.2f}x"
        )
        print(
            f"  ice fraction: {b['instrument']} {b['landsat_ice']:.3f}, "
            f"OLI {a['landsat_ice']:.3f}"
        )
        print()
        if b["landsat_ice"] - a["landsat_ice"] > 0.5:
            print(
                "  Two instruments, same hour, same sun, same fjord, and they do not\n"
                "  agree. The one that had been in normal operations for fourteen\n"
                "  years sees ice; the one still flying up to its operational orbit\n"
                "  sees water. The 2013 exclusion is a measurement, not an inference."
            )
        elif abs(b["landsat_ice"] - a["landsat_ice"]) < 0.1:
            print(
                "  The two instruments agree. That refutes the commissioning\n"
                "  explanation: the fjord really did read this way on this day, and\n"
                "  the 2013 exclusion in landsat_season_series.py is wrong and has to\n"
                "  be withdrawn."
            )
        else:
            print(
                "  The two disagree, but not decisively. State the numbers and do not\n"
                "  claim the exclusion is measured."
            )
    print(f"\nwritten to {path}")
    thermal_series(land_source, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
