"""CSV writers and result persistence."""

from __future__ import annotations

import csv
import logging
import os
from pathlib import Path
from typing import Dict, List, Tuple

CSV_HEADER = [
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
    # Clear-sky denominator: everything that is not cloud, land or a data gap.
    # summarise_masks has been emitting these since the radiometric fix; without
    # them in the header they were computed on every tile and then dropped on the
    # floor, and the only way to get them back was to reprocess the archive.
    "clear_px",
    "clear_pct",
    "usable",
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

# Columns that come from the metadata mapping rather than the stats mapping.
_METADATA_COLUMNS = {"eo_cloud_cover", "sun_elev", "sun_azim"}


class HeaderMismatchError(RuntimeError):
    """Raised when an existing CSV was written by a different column layout."""


def _repair_torn_tail(path: Path) -> bool:
    """Drop a final line that has no newline terminator. Returns True if it did.

    A run killed mid-flush leaves the last row half written. Appending to that
    file glues the next row onto the fragment and produces a line with more
    fields than the header, which pandas refuses to parse at all: one lost
    scene turns into a lost archive. The fragment is always re-derivable, the
    scene simply gets processed again, so the safe move is to cut it.
    """
    if not path.exists() or path.stat().st_size == 0:
        return False
    with path.open("rb+") as handle:
        handle.seek(-1, os.SEEK_END)
        if handle.read(1) in (b"\n", b"\r"):
            return False
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        # Walk back to the last newline and truncate there.
        block = 8192
        pos = size
        while pos > 0:
            step = min(block, pos)
            pos -= step
            handle.seek(pos)
            chunk = handle.read(step)
            idx = chunk.rfind(b"\n")
            if idx != -1:
                handle.truncate(pos + idx + 1)
                return True
        # No newline anywhere: the whole file is one fragment.
        handle.truncate(0)
        return True


class SummaryWriter:
    """Handle CSV persistence and duplicate detection."""

    def __init__(self, path: Path, overwrite: bool):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.header: List[str] = list(CSV_HEADER)
        if overwrite or not path.exists():
            self.file = path.open("w", newline="")
            self.writer = csv.writer(self.file)
            self.writer.writerow(CSV_HEADER)
            self.file.flush()
            self.seen: set[Tuple[str, str]] = set()
            return

        if _repair_torn_tail(path):
            logging.warning(
                "%s ended mid-row, most likely a run killed during a write. "
                "Dropped the fragment; that scene will be processed again.",
                path,
            )

        self.file = path.open("r+", newline="")
        reader = csv.reader(self.file)
        header = next(reader, None)
        self.seen = {(row[0], row[1]) for row in reader if len(row) >= 2}
        if header is None:
            self.writer = csv.writer(self.file)
            self.writer.writerow(CSV_HEADER)
        elif header != CSV_HEADER:
            self.file.close()
            raise HeaderMismatchError(
                f"{path} was written with a different column layout, so appending "
                f"to it would produce rows of two different widths.\n"
                f"  on disk: {header}\n"
                f"  expected: {CSV_HEADER}\n"
                f"Point --output-dir at a fresh directory, or pass --overwrite-csv "
                f"to start the file again."
            )
        else:
            self.header = header
        self.file.seek(0, 2)
        self.writer = csv.writer(self.file)

    def already_processed(self, tile_id: str, timestamp: str) -> bool:
        return (tile_id, timestamp) in self.seen

    def write(
        self,
        tile_id: str,
        timestamp: str,
        stats: Dict[str, float | int | str],
        metadata: Dict[str, float | int | str | None],
    ) -> None:
        row: list[float | int | str | None] = []
        for column in self.header:
            if column == "tile_id":
                row.append(tile_id)
            elif column == "timestamp":
                row.append(timestamp)
            elif column in _METADATA_COLUMNS:
                row.append(metadata.get(column, ""))
            else:
                row.append(stats[column])
        self.writer.writerow(row)
        self.file.flush()
        self.seen.add((tile_id, timestamp))

    def close(self) -> None:
        self.file.close()

    def __enter__(self) -> "SummaryWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
