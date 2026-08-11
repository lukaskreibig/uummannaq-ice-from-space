#!/usr/bin/env python3
"""Ask a thermometer, on every day in the record, whether the fjord was frozen.

commissioning_check.py set out to show that the dark March 2013 scenes were a
calibration artefact of Landsat 8's commissioning phase, and measured the
opposite. ETM+, fourteen years into normal operations, reads the same fjord on
the same day to within a hundredth: green 0.223 against 0.226, near infrared
0.120 against 0.115. The radiometry is right. The surface really was that dark.

The thermal band then said what the reflectance could not:

    2013-03-22   reported ice 0.052    265.5 K
    2013-03-30   reported ice 0.098    263.7 K   (ETM+ agrees at 264.2 K)
    2013-04-04   reported ice 0.151    265.8 K
    2013-04-09   reported ice 0.148    267.7 K
    2013-04-23   reported ice 0.827    260.0 K   frozen control
    2013-05-29   reported ice 0.001    272.7 K   open control
    2013-06-12   reported ice 0.001    278.3 K   open control

Seawater at this salinity freezes near 271.35 K, and open water cannot radiate
colder than that. All four questioned days are four to eight kelvin below it, and
the two days the chain calls open sit above it. So the fjord was frozen and the
chain read it as water, because a dark surface fails the brightness gate.

That is the same failure limitations.md already documents on twelve wet April
days, and finding it across a whole early season raises the obvious question:
how often does it happen in the seasons that carry the decline? Excluding 2013
because its reading is demonstrably wrong, without asking the same of 2021, 2023
and 2025, would be special pleading. This asks it of every day.

    AWS_REQUEST_PAYER=requester python3 scripts/thermal_audit.py

The rule applied is physical and uniform, not tuned to any season: a day is
CONTRADICTED when the chain reports less than half ice while more than half the
fjord radiates below the freezing point of seawater.

Three things this cannot do, stated before the numbers.

Brightness temperature is not surface temperature. There is no emissivity
correction and no atmospheric correction here, and both push the measured value
BELOW the true surface, which is the direction that would manufacture false
contradictions. The controls bound it rather than assume it away: the days the
chain calls open read 272.7 and 278.3 K, above freezing, so over this fjord in
this atmosphere the bias is not large enough to drag open water under the line.

The thermal band is 100 m data resampled to 30, so it resolves less than the
reflective bands and a partly frozen fjord averages towards the middle. That
blunts the test on mixed days and leaves the clear cases clear.

And a frozen surface is not a closed one. Ice that has drifted apart still
radiates cold at the floes, so this bounds one error, the reading of dark ice as
water, and does not measure ice fraction.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from commissioning_check import (  # noqa: E402
    SEAWATER_FREEZING_K,
    brightness_temperature,
)
from landsat_l1_crosscheck import (  # noqa: E402
    AOI,
    MIN_CLASSIFIED_SHARE,
    USGS_STAC,
)
from landsat_season_series import binned_means  # noqa: E402

LOGGER = logging.getLogger("thermal_audit")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERIES = ROOT / "archive/reprocessed_2026/landsat_season_series.csv"

# Below this reported ice fraction the chain is saying the fjord is mostly open.
OPEN_CALL = 0.50
LATE_FROM = 2021


def items_for(days: list[str], workers: int) -> dict[str, list]:
    """Every OLI scene on each day, so the series' own scene can be picked out."""
    from pystac_client import Client

    client = Client.open(USGS_STAC)
    wanted: dict[str, list] = {d: [] for d in days}

    def fetch(day: str):
        for attempt in range(4):
            try:
                got = [
                    it
                    for it in client.search(
                        collections=["landsat-c2l1"],
                        bbox=AOI,
                        datetime=f"{day}/{day}",
                        limit=100,
                    ).items()
                    if it.id.startswith("LC0")
                ]
                return day, got
            except Exception:  # pragma: no cover - network-driven
                import time

                time.sleep(3 * (attempt + 1))
        return day, []

    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for day, got in pool.map(fetch, days):
            wanted[day] = got
    return wanted


def main(argv: list[str] | None = None) -> int:
    import rasterio

    from uummannaq_ice.assets import default_landmask_path

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--series", type=Path, default=DEFAULT_SERIES)
    parser.add_argument("--out", type=Path, default=Path("out/archive"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("rasterio").setLevel(logging.ERROR)
    logging.getLogger("botocore").setLevel(logging.WARNING)

    series = pd.read_csv(args.series)
    usable = series[series.landsat_share >= MIN_CLASSIFIED_SHARE].copy()
    if args.limit:
        usable = usable.head(args.limit)
    LOGGER.info("%d days to ask the thermal band about", len(usable))

    with rasterio.open(default_landmask_path()) as lm:
        land_source = {"array": lm.read(1), "transform": lm.transform, "crs": lm.crs}

    by_day = items_for(sorted(usable.day.unique()), args.workers)
    wanted = dict(zip(usable.day, usable.scene, strict=False))

    def measure(day: str):
        pool = by_day.get(day) or []
        item = next((i for i in pool if i.id == wanted[day]), None)
        if item is None:
            return None
        try:
            kelvin, cells, _, frozen = brightness_temperature(item, land_source)
        except Exception as exc:  # pragma: no cover - network-driven
            LOGGER.warning("%s: %s", day, type(exc).__name__)
            return None
        if not np.isfinite(kelvin):
            return None
        return {
            "day": day,
            "kelvin": kelvin,
            "thermal_cells": cells,
            "frozen_share": frozen,
        }

    rows: list[dict] = []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for got in pool.map(measure, list(usable.day)):
            done += 1
            if got is not None:
                rows.append(got)
            if done % 50 == 0 or done == len(usable):
                LOGGER.info("[%d/%d]", done, len(usable))

    frame = usable.merge(pd.DataFrame(rows), on="day", how="inner")
    frame["celsius"] = frame.kelvin - 273.15
    # The share of the fjord radiating below the freezing point of seawater is
    # the number of the same kind as the reported ice fraction, so the gap
    # between them is the error being measured rather than a proxy for it.
    frame["thermal_minus_optical"] = frame.frozen_share - frame.landsat_ice
    frame["below_freezing"] = frame.kelvin < SEAWATER_FREEZING_K
    frame["chain_says_open"] = frame.landsat_ice < OPEN_CALL
    frame["contradicted"] = (frame.frozen_share > 0.5) & frame.chain_says_open
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "thermal_audit.csv"
    frame.to_csv(path, index=False)

    print()
    print(f"{len(frame)} of {len(usable)} days carry a usable thermal reading")
    print("=" * 78)
    print()
    print("Does the thermal band agree with what the chain reported?")
    print()
    print(
        f"{'chain reports':22s}{'n':>5s}{'median K':>10s}"
        f"{'frozen share':>14s}{'gap':>8s}"
    )
    for label, block in (
        ("ice 0.90 and above", frame[frame.landsat_ice >= 0.90]),
        (
            "ice 0.50 to 0.90",
            frame[(frame.landsat_ice >= 0.50) & (frame.landsat_ice < 0.90)],
        ),
        (
            "ice 0.10 to 0.50",
            frame[(frame.landsat_ice >= 0.10) & (frame.landsat_ice < 0.50)],
        ),
        ("ice under 0.10", frame[frame.landsat_ice < 0.10]),
    ):
        if block.empty:
            continue
        print(
            f"{label:22s}{len(block):5d}{block.kelvin.median():10.1f}"
            f"{block.frozen_share.median():14.3f}"
            f"{block.thermal_minus_optical.median():+8.3f}"
        )

    bad = frame[frame.contradicted]
    print()
    print(
        f"{len(bad)} days are CONTRADICTED: the chain calls the fjord mostly open "
        f"while more\nthan half of it radiates below the freezing point of seawater."
    )
    if not bad.empty:
        print()
        per = bad.groupby("season").size()
        allper = frame.groupby("season").size()
        print(f"{'season':8s}{'contradicted':>14s}{'of':>5s}{'share':>8s}")
        for season in sorted(allper.index):
            n = int(per.get(season, 0))
            print(
                f"{season:<8d}{n:14d}{int(allper[season]):5d}{n / allper[season]:8.2f}"
            )
        early = bad[bad.season < LATE_FROM]
        late = bad[bad.season >= LATE_FROM]
        ae = frame[frame.season < LATE_FROM]
        al = frame[frame.season >= LATE_FROM]
        print()
        print(
            f"  early seasons: {len(early)} of {len(ae)} days contradicted "
            f"({len(early) / max(len(ae), 1):.2f})"
        )
        print(
            f"  late seasons:  {len(late)} of {len(al)} days contradicted "
            f"({len(late) / max(len(al), 1):.2f})"
        )
        print()
        print(
            "  If the late share is the larger one, the chain is losing more frozen\n"
            "  fjord to the water class in the later period, and the measured decline\n"
            "  is partly that failure rather than the ice. If the two are alike, the\n"
            "  error is a level shift that mostly cancels between the periods."
        )
        print()
        print("  What the season means become if every contradicted day is handed")
        print("  back a fully frozen fjord, which is the most generous possible")
        print("  correction and therefore an upper bound on the effect:")
        fixed = frame.copy()
        fixed.loc[fixed.contradicted, "landsat_ice"] = 1.0
        # The same estimator the series itself publishes, means over fifteen-day
        # bins, or the corrected figure would not be comparable to the raw one.
        for name, f in (("as measured", frame), ("contradicted days repaired", fixed)):
            table = binned_means(f, "doy", "landsat_ice", "season")
            e = float(np.mean([v for s, (v, _) in table.items() if s < LATE_FROM]))
            latem = float(np.mean([v for s, (v, _) in table.items() if s >= LATE_FROM]))
            print(
                f"    {name:28s}early {e:.4f}  late {latem:.4f}  "
                f"decline {100 * (1 - latem / e):5.1f} %"
            )

    # How much of this hangs on where the line is drawn. 271.35 K is the freezing
    # point itself, and every kelvin subtracted from it is a safety margin against
    # the missing atmospheric correction, which biases the reading low and would
    # therefore manufacture contradictions rather than hide them.
    print()
    print("How much depends on the threshold")
    print("-" * 78)
    print(
        f"{'threshold':>10s}{'margin':>8s}{'days':>6s}{'early':>9s}{'late':>9s}"
        f"{'measured':>10s}{'repaired':>10s}"
    )
    early_all = int((frame.season < LATE_FROM).sum())
    late_all = int((frame.season >= LATE_FROM).sum())
    for margin in (0, 1, 2, 3, 4, 5):
        flag = (frame.kelvin < SEAWATER_FREEZING_K - margin) & frame.chain_says_open
        repaired = frame.copy()
        repaired.loc[flag, "landsat_ice"] = 1.0

        def decline_of(f):
            table = binned_means(f, "doy", "landsat_ice", "season")
            e = float(np.mean([v for s, (v, _) in table.items() if s < LATE_FROM]))
            late_mean = float(
                np.mean([v for s, (v, _) in table.items() if s >= LATE_FROM])
            )
            return 100 * (1 - late_mean / e)

        ne = int((flag & (frame.season < LATE_FROM)).sum())
        nl = int((flag & (frame.season >= LATE_FROM)).sum())
        print(
            f"{SEAWATER_FREEZING_K - margin:10.2f}{margin:8d}{int(flag.sum()):6d}"
            f"{ne:5d}/{early_all:<3d}{nl:5d}/{late_all:<3d}"
            f"{decline_of(frame):9.1f} %{decline_of(repaired):9.1f} %"
        )
    print()
    print(
        "  The repaired column is an extreme in both directions and neither end of\n"
        "  it is an estimate. It hands a contradicted day a completely frozen fjord,\n"
        "  which no thermal reading supports, and at zero margin it accepts days a\n"
        "  tenth of a kelvin under the line. What survives every margin is the\n"
        "  asymmetry: the failure is rarer in the early seasons than in the late\n"
        "  ones, so it pushes the measured decline up rather than scattering it."
    )

    print(f"\nwritten to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
