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

DEFAULT_START_DATE = date(2025, 3, 20)
DEFAULT_END_DATE = date(2025, 3, 22)
DEFAULT_STAC_URL = "https://earth-search.aws.element84.com/v1"
DEFAULT_COLLECTION = "sentinel-2-l1c"


@dataclass(slots=True)
class Thresholds:
    """Spectral cuts, re-derived on corrected reflectance.

    These MUST stay equal to the thresholds block in config/baseline.yaml. They
    are the fallback for a run started without --config, and they were left at
    the pre-correction values while the YAML carried the new ones, so a plain
    `uummannaq-ice` invocation silently classified with ndsi_solid 0.52 where the
    configured run used 0.83. A stale fallback is worse than no fallback: it
    produces a complete, plausible archive against the wrong rule.

    The values come from scripts/derive_thresholds.py over eighteen scenes
    spanning February to October and both sides of the 25 January 2022 baseline
    boundary. Changing one is a legitimate decision but must be a deliberate one:
    tests/test_config_loader.py locks them, and the story prints them.

    OPEN QUESTION, ndsi_solid. The derivation put it at 0.83 on the grounds that
    the gated ice distribution starts at 0.824. Measured directly against a
    completely frozen fjord (2023-04-20, tile 22WDD, 151,150 bright usable cells
    after cloud, land and stability masking) that does not hold: NDSI runs 0.687
    at the 1st percentile to 0.755 at the 99th, median 0.720, with a SWIR median
    of 0.112. At 0.83 not one cell of a frozen fjord is solid ice, so the class
    empties and mean_ndsi_solid is blank everywhere.

    This does NOT move the published number: the story shows solid + light, and
    every one of those cells clears ndsi_light either way, so the ice fraction is
    identical for any cut between the two. It decides only what the two classes
    mean. 0.70 sits just under the measured median, so on a frozen day most cells
    are solid and degraded ice falls to light, which is what the names promise.
    Worth resolving against the full eighteen-scene derivation rather than the
    one scene measured here.
    """

    ndsi_light: float = 0.40
    ndsi_solid: float = 0.70
    ndvi_min: float = -0.20
    vis_bright_min: float = 0.10
    nir_bright_min: float = 0.17
    swir_dark_max: float = 0.10
    ndwi: float = 0.20
    nodata_fraction: float = 0.20


@dataclass(slots=True)
class Concurrency:
    """How much of the scene fetch is allowed to happen at once.

    The knobs sit at two different levels, and the distinction matters because
    for a long time only the scene-level ones existed and neither of them was
    connected to anything.  See ``pipeline._stream_datasets``.

    ``band_workers`` is the one that pays.  A scene is 13 separate JPEG-2000
    objects on S3, and reading one is almost entirely round-trip latency rather
    than bandwidth: measured on a single scene, reading the 13 bands one after
    another took 60.9 s at 17 per cent CPU, and reading them with 13 threads
    took 7.8 s.  Thirteen is the natural ceiling, because there is one dask
    chunk per band and therefore only 13 tasks to hand out; 16 threads measured
    no faster.  Going the other way costs real time: 4 threads measured 13.1 s
    per scene against 7.5 s at 13.

    ``download_workers`` and ``decode_queue_size`` fetch whole scenes ahead of
    the classifier and together bound how much can be in hand at once: at most
    ``download_workers + decode_queue_size`` scenes, each about 78 MB of uint16
    band data.  They still help, because a scene's 13 reads do not all overlap
    perfectly, but much less than ``band_workers`` does: 4 + 3 measured about
    18 per cent faster than 2 + 1, while 6 + 3 and 8 + 4 were inside the
    run-to-run noise of 4 + 3 and cost more memory.  Peak RSS at 4 + 3 measured
    2.9 GB.
    """

    download_workers: int = 4
    decode_queue_size: int = 3
    band_workers: int = 13


# `Concurrency` is a slots dataclass, so `Concurrency.band_workers` is a slot
# descriptor rather than the default value.  Reading the defaults off a single
# throwaway instance keeps `build_config` and the dataclass from drifting apart
# without silently binding a descriptor as a function default.
_CONCURRENCY_DEFAULTS = Concurrency()


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
    download_workers: int = _CONCURRENCY_DEFAULTS.download_workers,
    decode_queue_size: int = _CONCURRENCY_DEFAULTS.decode_queue_size,
    band_workers: int = _CONCURRENCY_DEFAULTS.band_workers,
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
            download_workers=download_workers,
            decode_queue_size=decode_queue_size,
            band_workers=band_workers,
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
