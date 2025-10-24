"""CSV writers and result persistence."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Tuple

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
    "mean_ndsi_solid",
    "mean_ndsi_light",
    "mean_ndwi_water",
    "eo_cloud_cover",
    "sun_elev",
    "sun_azim",
    "edge_gap",
]


class SummaryWriter:
    """Handle CSV persistence and duplicate detection."""

    def __init__(self, path: Path, overwrite: bool):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if overwrite or not path.exists():
            self.file = path.open("w", newline="")
            self.writer = csv.writer(self.file)
            self.writer.writerow(CSV_HEADER)
            self.file.flush()
            self.seen: set[Tuple[str, str]] = set()
        else:
            self.file = path.open("r+", newline="")
            reader = csv.reader(self.file)
            header = next(reader, None)
            self.seen = {(row[0], row[1]) for row in reader if len(row) >= 2}
            if header is None:
                self.writer = csv.writer(self.file)
                self.writer.writerow(CSV_HEADER)
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
        row = [
            tile_id,
            timestamp,
            stats["solid_px"],
            stats["light_px"],
            stats["water_px"],
            stats["cloud_px"],
            stats["land_px"],
            stats["nodata_px"],
            stats["unknown_px"],
            stats["solid_pct"],
            stats["light_pct"],
            stats["water_pct"],
            stats["cloud_pct"],
            stats["land_pct"],
            stats["nodata_pct"],
            stats["mean_ndsi_solid"],
            stats["mean_ndsi_light"],
            stats["mean_ndwi_water"],
            metadata.get("eo_cloud_cover", ""),
            metadata.get("sun_elev", ""),
            metadata.get("sun_azim", ""),
            stats["edge_gap"],
        ]
        self.writer.writerow(row)
        self.file.flush()
        self.seen.add((tile_id, timestamp))

    def close(self) -> None:
        self.file.close()

    def __enter__(self) -> "SummaryWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
