"""Command line interface for the Uummannaq ice pipeline."""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

from .config import Thresholds, build_config
from .config_loader import load_run_config
from .pipeline import run_pipeline


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover - user input
        raise argparse.ArgumentTypeError(f"Invalid date: {value}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uummannaq-ice",
        description="Classify Sentinel-2 tiles over Uummannaq into ice/water/cloud classes.",
    )
    parser.add_argument(
        "--config-file", type=Path, help="YAML file describing the run configuration."
    )
    parser.add_argument(
        "--start-date", type=_parse_date, help="Inclusive start date (YYYY-MM-DD)."
    )
    parser.add_argument(
        "--end-date", type=_parse_date, help="Inclusive end date (YYYY-MM-DD)."
    )
    parser.add_argument(
        "--aoi", type=Path, help="GeoJSON file describing the AOI polygon."
    )
    parser.add_argument("--output-dir", type=Path, help="Root directory for outputs.")
    parser.add_argument("--csv-name", type=str, help="Filename for the summary CSV.")
    parser.add_argument(
        "--quicklook-subdir",
        type=str,
        help="Subdirectory within the output dir for overlay PNGs.",
    )
    parser.add_argument(
        "--checkpoint", type=Path, help="Path to the UNet MobilenetV2 checkpoint."
    )
    parser.add_argument(
        "--landmask", type=Path, help="Path to the landmask template PNG."
    )
    parser.add_argument(
        "--max-tiles", type=int, help="Limit number of tiles to process."
    )
    parser.add_argument(
        "--overwrite-csv",
        action="store_true",
        help="Rewrite the summary CSV instead of appending.",
    )
    parser.add_argument(
        "--device", type=str, help="Force a specific torch device (cpu, cuda, mps)."
    )
    parser.add_argument(
        "--threads", type=int, help="Concurrent STAC loads (default: 4)."
    )
    parser.add_argument(
        "--decode-queue", type=int, help="Prefetch queue size (default: 3)."
    )
    parser.add_argument("--log-level", type=str, help="Python logging level.")

    thresh = parser.add_argument_group("Thresholds")
    thresh.add_argument(
        "--ndsi-light", type=float, help="NDSI threshold for light ice detection."
    )
    thresh.add_argument(
        "--ndsi-solid", type=float, help="NDSI threshold for solid ice detection."
    )
    thresh.add_argument(
        "--ndwi", type=float, help="NDWI threshold for water detection."
    )
    thresh.add_argument(
        "--nodata-fraction", type=float, help="No-data fraction flag threshold."
    )
    thresh.add_argument(
        "--ndvi-min", type=float, help="Optional NDVI floor (currently inactive)."
    )
    thresh.add_argument(
        "--vis-bright-min", type=float, help="Optional visible band brightness floor."
    )
    thresh.add_argument(
        "--nir-bright-min", type=float, help="Optional NIR brightness floor."
    )
    thresh.add_argument(
        "--swir-dark-max", type=float, help="Optional SWIR darkness ceiling."
    )

    return parser


def _thresholds_from_args(args: argparse.Namespace) -> Optional[Thresholds]:
    base = Thresholds()
    changed = False
    overrides = {
        "ndsi_light": args.ndsi_light,
        "ndsi_solid": args.ndsi_solid,
        "ndwi": args.ndwi,
        "nodata_fraction": args.nodata_fraction,
        "ndvi_min": args.ndvi_min,
        "vis_bright_min": args.vis_bright_min,
        "nir_bright_min": args.nir_bright_min,
        "swir_dark_max": args.swir_dark_max,
    }
    for key, value in overrides.items():
        if value is not None:
            setattr(base, key, value)
            changed = True
    return base if changed else None


def _build_kwargs_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if args.start_date:
        kwargs["start_date"] = args.start_date
    if args.end_date:
        kwargs["end_date"] = args.end_date
    if args.aoi:
        kwargs["aoi_path"] = args.aoi
    if args.output_dir:
        kwargs["output_dir"] = args.output_dir
    if args.csv_name:
        kwargs["csv_filename"] = args.csv_name
    if args.quicklook_subdir:
        kwargs["quicklook_subdir"] = args.quicklook_subdir
    if args.checkpoint:
        kwargs["checkpoint_path"] = args.checkpoint
    if args.landmask:
        kwargs["landmask_path"] = args.landmask
    thresholds = _thresholds_from_args(args)
    if thresholds:
        kwargs["thresholds"] = thresholds
    if args.overwrite_csv:
        kwargs["overwrite_csv"] = True
    if args.threads is not None:
        kwargs["download_workers"] = args.threads
    if args.decode_queue is not None:
        kwargs["decode_queue_size"] = args.decode_queue
    if args.max_tiles is not None:
        kwargs["max_tiles"] = args.max_tiles
    if args.log_level:
        kwargs["log_level"] = args.log_level
    if args.device:
        kwargs["device"] = args.device
    return kwargs


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    kwargs = _build_kwargs_from_args(args)
    if args.config_file:
        config = load_run_config(args.config_file, overrides=kwargs)
    else:
        config = build_config(**kwargs)  # type: ignore[arg-type]

    logging.basicConfig(
        format="%(asctime)s  %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
        level=getattr(logging, config.log_level, logging.INFO),
    )

    stats = run_pipeline(config)
    if stats:
        logging.info(
            "CLI summary: processed %s tile(s) (%.1fs total, %.2fs avg)",
            stats.get("tiles_processed", 0),
            stats.get("elapsed_seconds", 0.0),
            stats.get("average_seconds_per_tile", 0.0),
        )


if __name__ == "__main__":  # pragma: no cover
    main()
