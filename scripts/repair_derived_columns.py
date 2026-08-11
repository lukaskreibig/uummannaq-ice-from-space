#!/usr/bin/env python3
"""Recompute the columns that are derived, and refuse if a measured one moves.

A summary CSV holds two kinds of column. The six pixel counts are the
measurement, the output of the classifier on that scene, and nothing may touch
them outside a reprocess. Everything else is arithmetic on those six, and can be
rebuilt at any time from the file itself.

    python3 scripts/repair_derived_columns.py --check
    python3 scripts/repair_derived_columns.py --write

This exists because a derived column in the committed archive stopped agreeing
with its own definition. `usable` is documented, and computed by
processing.py:583, as `classified_share >= 0.30`. In the committed file it is
`clear_pct >= 0.30`, which is what the gate used to mean before the denominator
changed. 694 scenes carry the flag under the old rule and 617 under the current
one, and 77 rows disagree.

Nothing published is wrong because of it: every analysis script recomputes the
share from the counts rather than trusting the flag, which is why the headline
reproduces. But a reader who trusted the column got 23.4 percent and p = 0.090
against a published 22.6 and 0.119, and there was nothing in the file to warn
them. `classified_px`, which is the denominator that flag is defined on, was
computed on every tile and then dropped before writing, so it was not even
possible to check the flag against its own definition without recomputing it.

WHAT THIS IS NOT. It is not a correction of the archive. Repairing a derived
column from the measurement it derives from is bookkeeping; the measurement is
untouched and this script fails loudly if any of the six counts differs by so
much as one pixel. If a count is wrong, the answer is a reprocess and not this.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / "archive/reprocessed_2026/summary.csv"

# The measurement. Never rewritten here, and a difference in any of them is a
# reason to stop rather than to continue.
MEASURED = ("solid_px", "light_px", "water_px", "cloud_px", "land_px", "nodata_px")
# Where the visibility gate sits, matching processing.py's MIN_CLEAR_SHARE.
MIN_CLEAR_SHARE = 0.30


def derived(frame: pd.DataFrame) -> pd.DataFrame:
    """Every column that is arithmetic on the six counts, rebuilt."""
    counts = {c: pd.to_numeric(frame[c], errors="coerce").fillna(0.0) for c in MEASURED}
    classified = counts["solid_px"] + counts["light_px"] + counts["water_px"]
    grid = classified + counts["cloud_px"] + counts["land_px"] + counts["nodata_px"]
    share = classified.divide(grid.where(grid > 0))
    out = frame.copy()
    out["classified_px"] = classified.astype("int64")
    out["usable"] = (share >= MIN_CLEAR_SHARE).astype(int)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--write", action="store_true", help="write the repair back")
    parser.add_argument("--check", action="store_true", help="report and exit non-zero")
    args = parser.parse_args(argv)

    frame = pd.read_csv(args.archive)
    fixed = derived(frame)

    for column in MEASURED:
        if not frame[column].equals(fixed[column]):
            print(f"REFUSING: {column} is a measurement and this script moved it.")
            return 2

    moved: list[str] = []
    for column in ("classified_px", "usable"):
        if column not in frame:
            moved.append(
                f"{column}: absent, {int(fixed[column].sum())} would be written"
            )
        else:
            differs = int(
                (pd.to_numeric(frame[column], errors="coerce") != fixed[column]).sum()
            )
            if differs:
                moved.append(f"{column}: {differs} of {len(frame)} rows disagree")

    print(f"{args.archive}, {len(frame)} scenes")
    print("  the six measured counts are untouched")
    if not moved:
        print("  every derived column already agrees with its definition")
        return 0
    for line in moved:
        print(f"  {line}")
    if "usable" in frame:
        old = int(pd.to_numeric(frame.usable, errors="coerce").sum())
        print(
            f"\n  scenes flagged usable: {old} before, {int(fixed.usable.sum())} after"
        )
        print("  Nothing published changes: the analysis scripts recompute the share")
        print("  from the counts and never read this flag.")

    if args.write:
        # Keep the column order the writer produces, with classified_px in front
        # of the flag it defines.
        columns = list(frame.columns)
        if "classified_px" not in columns:
            columns.insert(columns.index("usable"), "classified_px")
        fixed[columns].to_csv(args.archive, index=False)
        print(f"\n  written to {args.archive}")
        return 0
    if args.check:
        print("\n  run with --write to repair")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
