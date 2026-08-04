#!/usr/bin/env python3
"""Watch a running archive reprocess without touching it.

    python3 scripts/watch_archive.py "/Volumes/Crucial X9/uummannaq-archive"
    python3 scripts/watch_archive.py OUT --follow      # refresh every 20 s

With JOBS>1 the outer script only prints a line per finished season, while the
interesting detail goes into one log per season, all being appended at once.
This reads those logs and the per-season CSVs and puts the whole run on one
screen: how far each season is, how fast it is going, what it has rejected, and
what the rows look like so far.

Read only on purpose. It opens the same files the run is writing and never
writes anything itself, so it cannot disturb a job that has hours left.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PROGRESS = re.compile(r"\[(\d+)/(\d+)\]")
TIMING = re.compile(r"mean ([\d.]+)s \| ETA ([\d:]+)")
REJECT = re.compile(r"Rejecting|too large to be a granule|partial read|below")


@dataclass(slots=True)
class SeasonState:
    year: str
    done: int = 0
    total: int = 0
    mean_seconds: Optional[float] = None
    eta: str = ""
    rejects: int = 0
    rows: int = 0
    finished: bool = False


def read_season(out: Path, year: str) -> SeasonState:
    state = SeasonState(year=year)

    log = out / "logs" / f"{year}.log"
    if log.exists():
        # Only the tail matters and these files grow; reading the last 200 kB
        # keeps this instant even late in a long season.
        with log.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - 200_000))
            tail = handle.read().decode("utf-8", errors="replace")
        for match in PROGRESS.finditer(tail):
            state.done, state.total = int(match.group(1)), int(match.group(2))
        timings = TIMING.findall(tail)
        if timings:
            state.mean_seconds = float(timings[-1][0])
            state.eta = timings[-1][1]
        state.rejects = len(REJECT.findall(tail))

    csv_path = out / f"summary_{year}.csv"
    if not csv_path.exists():
        csv_path = out / "summary.csv"
    if csv_path.exists():
        with csv_path.open(newline="") as handle:
            state.rows = sum(1 for _ in handle) - 1

    state.finished = bool(state.total) and state.done >= state.total
    return state


def bar(done: int, total: int, width: int = 24) -> str:
    if not total:
        return "." * width
    filled = round(width * done / total)
    return "#" * filled + "." * (width - filled)


def render(out: Path) -> str:
    years = sorted(
        {p.stem.split("_")[-1] for p in out.glob("summary_[0-9][0-9][0-9][0-9].csv")}
        | {p.stem for p in (out / "logs").glob("[0-9][0-9][0-9][0-9].log")}
    )
    if not years:
        return f"nothing to watch yet in {out}"

    lines = [
        f"{'season':>7s} {'progress':<26s} {'scenes':>9s} {'rows':>6s} {'mean':>7s} {'eta':>9s}"
    ]
    total_rows = total_done = total_scenes = 0
    for year in years:
        state = read_season(out, year)
        total_rows += state.rows
        total_done += state.done
        total_scenes += state.total
        mean = f"{state.mean_seconds:.1f}s" if state.mean_seconds else ""
        lines.append(
            f"{state.year:>7s} [{bar(state.done, state.total)}] "
            f"{state.done:>4d}/{state.total:<4d} {state.rows:>6d} {mean:>7s} "
            f"{('done' if state.finished else state.eta):>9s}"
        )

    lines.append("")
    lines.append(
        f"  {total_done} of {total_scenes} scenes seen, {total_rows} rows written"
    )

    exports = out / "quicklooks" / "classes"
    if exports.exists():
        # Skip AppleDouble sidecars. Writing to a volume that is not APFS or
        # HFS+ makes macOS put a "._name" file next to every real one for the
        # extended attributes, so a naive count comes out exactly double.
        rasters = sum(
            1 for p in exports.glob("*_classes.png") if not p.name.startswith("._")
        )
        lines.append(f"  {rasters} class rasters exported")

    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path, help="the run's --output-dir")
    parser.add_argument("--follow", action="store_true", help="refresh until stopped")
    parser.add_argument("--interval", type=float, default=20.0)
    args = parser.parse_args(argv)

    if not args.out.exists():
        print(f"no such directory: {args.out}", file=sys.stderr)
        return 2

    if not args.follow:
        print(render(args.out))
        return 0

    try:
        while True:
            print("\033[2J\033[H", end="")
            print(time.strftime("%H:%M:%S"))
            print(render(args.out))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
