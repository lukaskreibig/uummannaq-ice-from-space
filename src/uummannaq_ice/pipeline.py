"""Orchestrate the Sentinel-2 sea-ice classification workflow."""

from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import gc
import logging
import os
import time
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import torch
from odc.stac import load

from .config import RunConfig
from .manifest import write_manifest
from .model import load_cloud_model, resolve_device
from .output import SummaryWriter
from .processing import (
    TileClassification,
    classify_tile,
    downsample_cube,
    make_land_mask,
    reflectance_cube,
    summarise_masks,
    build_rgb_preview,
    refresh_landmask,
)
from .stac import fetch_tiles

# Compatibility shims – downstream libraries import this key on import.
try:  # pragma: no cover - optional dependency quirk
    import dask.typing  # type: ignore

    _ = dask.typing.Key
except Exception:  # pragma: no cover
    import types

    import dask.typing  # type: ignore

    dask.typing.Key = object  # type: ignore

# numpy compatibility for older SMP builds
if not hasattr(np, "round_"):
    np.round_ = np.round  # type: ignore[attr-defined]


def run_pipeline(config: RunConfig) -> dict[str, Any]:
    """Execute the full ingestion + classification loop and return run statistics."""
    os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
    logging.getLogger().setLevel(getattr(logging, config.log_level, logging.INFO))

    overlays_dir = (config.quicklook_dir / "overlays").resolve()
    panels_dir = (config.quicklook_dir / "panels").resolve()
    overlays_dir.mkdir(parents=True, exist_ok=True)
    panels_dir.mkdir(parents=True, exist_ok=True)

    tiles = fetch_tiles(config)
    if not tiles:
        logging.info("Nothing to process – exiting.")
    started_at = dt.datetime.utcnow()
    device = resolve_device(config.device)
    logging.info("Using torch device: %s", device)

    if not tiles:
        logging.info("Nothing to process – exiting.")
        finished_at = dt.datetime.utcnow()
        stats = {
            "tiles_total": 0,
            "tiles_requested": 0,
            "tiles_processed": 0,
            "tiles_already_done": 0,
            "tiles_failed": 0,
            "tiles_skipped": 0,
            "elapsed_seconds": (finished_at - started_at).total_seconds(),
            "average_seconds_per_tile": 0.0,
            "device": str(device),
        }
        _write_run_manifest(config, stats, started_at, finished_at)
        return stats

    model = load_cloud_model(config.checkpoint_path, device)

    landmask_template = refresh_landmask(config.landmask_path)

    with SummaryWriter(config.csv_path, overwrite=config.overwrite_csv) as writer:
        pending = []
        already_processed = 0
        for item in tiles:
            timestamp = item.datetime.strftime("%Y%m%dT%H%M%S")
            if writer.already_processed(item.id, timestamp):
                logging.info("Skipping %s %s (already in CSV)", item.id, timestamp)
                already_processed += 1
                continue
            pending.append(item)

        if not pending:
            logging.info("All tiles already processed – nothing to do.")
            finished_at = dt.datetime.utcnow()
            stats = {
                "tiles_total": len(tiles),
                "tiles_requested": 0,
                "tiles_processed": 0,
                "tiles_already_done": already_processed,
                "tiles_failed": 0,
                "tiles_skipped": 0,
                "elapsed_seconds": (finished_at - started_at).total_seconds(),
                "average_seconds_per_tile": 0.0,
                "device": str(device),
            }
            _write_run_manifest(config, stats, started_at, finished_at)
            return stats

        proc_times: list[float] = []
        processed = 0
        load_failures = 0
        skipped_invalid = 0
        for idx, (item, dataset) in enumerate(
            _stream_datasets(pending, config), start=1
        ):
            if isinstance(dataset, Exception):
                logging.error("Failed to load %s: %s", item.id, dataset)
                load_failures += 1
                continue
            if not {"red", "green", "blue"}.issubset(dataset.data_vars):
                logging.error("   skipped – RGB bands missing for %s", item.id)
                skipped_invalid += 1
                continue

            ts = item.datetime.strftime("%Y%m%dT%H%M%S")
            logging.info("[%d/%d] %s  %s", idx, len(pending), item.id, ts)

            t0 = time.time()
            baseline_str = item.properties.get("s2:processing_baseline", "0.0")
            logging.info("   processing baseline: %s", baseline_str)

            try:
                baseline_major = int(float(baseline_str))
            except Exception:
                baseline_major = 0

            rgb_preview = build_rgb_preview(dataset)
            cube = reflectance_cube(dataset, baseline_major)
            small = downsample_cube(cube)
            _, h4, w4 = small.shape

            land_mask = make_land_mask(landmask_template, w4, h4)

            classification = classify_tile(
                small,
                land_mask,
                config.thresholds,
                model,
                device,
                rgb_preview,
                baseline_str,
            )

            stats = summarise_masks(
                classification.masks,
                classification.ndsi,
                classification.ndwi,
                config.thresholds.nodata_fraction,
            )

            overlay_path = overlays_dir / f"{item.id}_{ts}_overlay.png"
            panel_path = panels_dir / f"{item.id}_{ts}_panel.png"
            classification.overlay.save(overlay_path)
            classification.panel.suptitle(f"{item.id}  {ts}", fontsize=11)
            classification.panel.savefig(panel_path, dpi=150)
            plt.close(classification.panel)

            metadata = {
                "eo_cloud_cover": item.properties.get("eo:cloud_cover"),
                "sun_elev": item.properties.get("view:sun_elevation"),
                "sun_azim": item.properties.get("view:sun_azimuth"),
            }
            writer.write(item.id, ts, stats, metadata)

            dt_sec = time.time() - t0
            proc_times.append(dt_sec)
            mean_dt = sum(proc_times) / len(proc_times)
            eta_sec = mean_dt * (len(pending) - idx)
            processed += 1
            logging.info(
                "   elapsed %.1fs | mean %.1fs | ETA %s",
                dt_sec,
                mean_dt,
                dt.timedelta(seconds=int(eta_sec)),
            )

            del dataset, cube, small, classification
            gc.collect()
            if device.type == "mps":
                torch.mps.empty_cache()  # type: ignore[attr-defined]
            elif device.type == "cuda":
                torch.cuda.empty_cache()

    finished_at = dt.datetime.utcnow()
    elapsed = (finished_at - started_at).total_seconds()
    avg = sum(proc_times) / len(proc_times) if proc_times else 0.0
    stats_summary = {
        "tiles_total": len(tiles),
        "tiles_requested": len(pending),
        "tiles_processed": processed,
        "tiles_already_done": already_processed,
        "tiles_failed": load_failures,
        "tiles_skipped": skipped_invalid,
        "elapsed_seconds": elapsed,
        "average_seconds_per_tile": avg,
        "device": str(device),
    }
    _write_run_manifest(config, stats_summary, started_at, finished_at)
    logging.info("Finished – results written to %s", config.csv_path)
    logging.info(
        "Run summary: %s processed, %s skipped, %s failures (%.1fs total).",
        processed,
        skipped_invalid,
        load_failures,
        elapsed,
    )
    return stats_summary


def _stream_datasets(items, config: RunConfig):
    """Load STAC datasets concurrently while preserving submission order."""

    def load_item(it):
        try:
            return load([it], geopolygon=config.search_aoi, chunks={})
        except Exception as exc:  # pragma: no cover - network-driven
            return exc

    with cf.ThreadPoolExecutor(max_workers=config.concurrency.download_workers) as pool:
        futures = [(item, pool.submit(load_item, item)) for item in items]
        for item, future in futures:
            yield item, future.result()


def _write_run_manifest(
    config: RunConfig,
    stats: dict[str, Any],
    started_at: dt.datetime,
    finished_at: dt.datetime,
) -> None:
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    manifest_path = config.output_dir / "run_metadata" / f"run_{timestamp}.json"
    write_manifest(
        config=config,
        stats=stats,
        started_at=started_at,
        finished_at=finished_at,
        manifest_path=manifest_path,
    )
