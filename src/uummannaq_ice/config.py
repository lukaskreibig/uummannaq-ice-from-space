"""Configuration helpers for the sea-ice classification pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Optional

from .assets import default_checkpoint_path, default_landmask_path

DEFAULT_AOI: Mapping[str, Any] = {
    "type": "Polygon",
    "coordinates": [
        [
            [-52.336121, 70.788206],
            [-51.945564, 70.788206],
            [-51.945564, 70.628226],
            [-52.336121, 70.628226],
            [-52.336121, 70.788206],
        ]
    ],
}

DEFAULT_START_DATE = date(2025, 5, 6)
DEFAULT_END_DATE = date(2025, 6, 25)
DEFAULT_STAC_URL = "https://earth-search.aws.element84.com/v1"
DEFAULT_COLLECTION = "sentinel-2-l1c"


@dataclass(slots=True)
class Thresholds:
    ndsi_light: float = 0.31
    ndsi_solid: float = 0.52
    ndvi_min: float = -0.20
    vis_bright_min: float = 0.08
    nir_bright_min: float = 0.17
    swir_dark_max: float = 0.10
    ndwi: float = 0.25
    nodata_fraction: float = 0.20


@dataclass(slots=True)
class Concurrency:
    download_workers: int = 4
    decode_queue_size: int = 3


@dataclass
class RunConfig:
    stac_url: str
    collection: str
    start_date: date
    end_date: date
    search_aoi: Mapping[str, Any]
    checkpoint_path: Path
    landmask_path: Path
    output_dir: Path
    csv_path: Path
    quicklook_dir: Path
    thresholds: Thresholds = field(default_factory=Thresholds)
    overwrite_csv: bool = False
    log_level: str = "INFO"
    concurrency: Concurrency = field(default_factory=Concurrency)
    max_tiles: Optional[int] = None
    device: Optional[str] = None

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be earlier than start_date")

        self.output_dir = _resolve_dir(self.output_dir)
        self.quicklook_dir = _resolve_dir(self.quicklook_dir)
        self.csv_path = _resolve_path(self.csv_path, self.output_dir)
        self.checkpoint_path = _resolve_path(self.checkpoint_path)
        self.landmask_path = _resolve_path(self.landmask_path)

    @property
    def date_range(self) -> str:
        return (
            f"{self.start_date.isoformat()}T00:00:00Z/"
            f"{self.end_date.isoformat()}T23:59:59Z"
        )


def build_config(
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    aoi_path: Optional[Path] = None,
    stac_url: str = DEFAULT_STAC_URL,
    collection: str = DEFAULT_COLLECTION,
    output_dir: Path | str = Path("out"),
    csv_filename: str | Path = "summary.csv",
    quicklook_subdir: Optional[str] = "quicklooks",
    checkpoint_path: Optional[Path | str] = None,
    landmask_path: Optional[Path | str] = None,
    thresholds: Optional[Thresholds] = None,
    overwrite_csv: bool = False,
    download_workers: int = 4,
    decode_queue_size: int = 3,
    max_tiles: Optional[int] = None,
    log_level: str = "INFO",
    device: Optional[str] = None,
) -> RunConfig:
    """Build a ready-to-use :class:`RunConfig` instance."""
    start = start_date or DEFAULT_START_DATE
    end = end_date or DEFAULT_END_DATE
    aoi = load_aoi(aoi_path) if aoi_path else DEFAULT_AOI
    out_dir = Path(output_dir)

    csv_path = Path(csv_filename)
    quicklook_dir = Path(quicklook_subdir) if quicklook_subdir else Path("quicklooks")
    quicklook_path = out_dir / quicklook_dir

    chk_path = Path(checkpoint_path) if checkpoint_path else default_checkpoint_path()
    land_path = Path(landmask_path) if landmask_path else default_landmask_path()

    return RunConfig(
        stac_url=stac_url,
        collection=collection,
        start_date=start,
        end_date=end,
        search_aoi=aoi,
        checkpoint_path=chk_path,
        landmask_path=land_path,
        output_dir=out_dir,
        csv_path=csv_path,
        quicklook_dir=quicklook_path,
        thresholds=thresholds or Thresholds(),
        overwrite_csv=overwrite_csv,
        log_level=log_level.upper(),
        concurrency=Concurrency(
            download_workers=download_workers, decode_queue_size=decode_queue_size
        ),
        max_tiles=max_tiles,
        device=device,
    )


def load_aoi(path: Path) -> Mapping[str, Any]:
    """Load a GeoJSON polygon from disk."""
    data = json.loads(path.read_text())
    if data.get("type") == "FeatureCollection":
        return data["features"][0]["geometry"]
    if data.get("type") == "Feature":
        return data["geometry"]
    if data.get("type") == "Polygon":
        return data
    raise ValueError(f"Unsupported GeoJSON structure in {path}")


def _resolve_path(path: Path | str, base: Optional[Path] = None) -> Path:
    p = Path(path)
    if not p.is_absolute() and base is not None:
        p = base / p
    return p.expanduser().resolve()


def _resolve_dir(path: Path | str) -> Path:
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p
