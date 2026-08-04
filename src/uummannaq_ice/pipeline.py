"""Orchestrate the Sentinel-2 sea-ice classification workflow."""

from __future__ import annotations

import collections
import concurrent.futures as cf
import datetime as dt
import gc
import logging
import os
import time
from typing import Any, Iterable, Iterator

import matplotlib.pyplot as plt
import numpy as np
import torch
from odc.stac import load

from .config import RunConfig
from .manifest import write_manifest
from .model import load_cloud_model, resolve_device
from .output import SummaryWriter
from .processing import (
    BANDS,
    build_rgb_preview,
    classify_tile,
    downsample_cube,
    export_rgb,
    land_mask_from_raster,
    make_land_mask,
    reflectance_cube,
    refresh_landmask,
    summarise_masks,
)
from .scene_export import write_scene_export
from .stac import fetch_tiles

# Only ask S3 for the bands the classifier consumes.  A Sentinel-2 L1C item also
# advertises a `visual` asset, the pre-rendered true-colour composite, and odc
# will happily add it to the dataset.  Nothing reads it, but once the load is
# eager (see _stream_datasets) an unused band is a real download rather than an
# unused lazy reference, so it has to be excluded by name.
BAND_SELECTION = tuple(BANDS)

# A scene is 13 objects fetched over the public internet, and over a run of
# ~1550 scenes a transient S3 or DNS blip is close to certain.  Without a retry
# a single blip silently costs that day: the scene is logged as a failure and
# the published series simply has a hole where an observation exists.
LOAD_ATTEMPTS = 3
LOAD_RETRY_BACKOFF_SECONDS = 2.0

# Detection of a silently failed band read. See _reject_partial_reads for the
# reasoning; in short, GDAL can return a band as pure fill without raising, and
# the scene is then published as a plausible open-water day.
#
# A band this full of fill is not geometry, it is a failed read.
BLANK_BAND_SHARE = 0.95
# ... provided the scene itself is not simply outside the swath.
NOT_A_BLANK_SCENE = 0.50
# Second net, deliberately generous: the thirteen bands have three native
# resolutions (10, 20 and 60 m) and resample differently at a swath edge, so a
# tight spread rule rejects real observations. Only gross disagreement counts.
PARTIAL_READ_TOLERANCE = 0.25

# Compatibility shims – downstream libraries import this key on import.
try:  # pragma: no cover - optional dependency quirk
    import dask.typing  # type: ignore

    _ = dask.typing.Key
except Exception:  # pragma: no cover
    import dask.typing  # type: ignore

    dask.typing.Key = object  # type: ignore

# numpy compatibility for older SMP builds
if not hasattr(np, "round_"):
    np.round_ = np.round  # type: ignore[attr-defined]


def _epsg_or_wkt(crs: Any) -> str:
    """EPSG:nnnnn where the CRS knows its code, the WKT where it does not."""
    try:
        epsg = crs.epsg
    except AttributeError:
        epsg = None
    return f"EPSG:{epsg}" if epsg else str(crs)


def run_pipeline(config: RunConfig) -> dict[str, Any]:
    """Execute the full ingestion + classification loop and return run statistics."""
    os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
    logging.getLogger().setLevel(getattr(logging, config.log_level, logging.INFO))

    overlays_dir = (config.quicklook_dir / "overlays").resolve()
    panels_dir = (config.quicklook_dir / "panels").resolve()
    overlays_dir.mkdir(parents=True, exist_ok=True)
    panels_dir.mkdir(parents=True, exist_ok=True)
    # Separate from the quicklooks on purpose: those are for judging a scene by
    # eye, these are for a viewer to build on. See scene_export.
    classes_dir = (config.quicklook_dir / "classes").resolve()
    scenes_dir = (config.quicklook_dir / "scenes").resolve()

    tiles = fetch_tiles(config)
    started_at = dt.datetime.now(dt.timezone.utc)
    device = resolve_device(config.device)
    logging.info("Using torch device: %s", device)
    _warn_if_archive_is_device_dependent(config, device)

    if not tiles:
        logging.info("Nothing to process – exiting.")
        finished_at = dt.datetime.now(dt.timezone.utc)
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

    # A georeferenced mask is reprojected per scene; the painted template can
    # only be stretched. Which one is in play is worth stating in the log,
    # because it changes what "land" means by about four points of the grid.
    landmask_is_raster = str(config.landmask_path).lower().endswith((".tif", ".tiff"))
    landmask_template = (
        None if landmask_is_raster else refresh_landmask(config.landmask_path)
    )
    logging.info(
        "Land mask: %s (%s)",
        config.landmask_path.name,
        "georeferenced, reprojected per scene"
        if landmask_is_raster
        else "painted template, stretched to the grid",
    )

    with SummaryWriter(config.csv_path, overwrite=config.overwrite_csv) as writer:
        pending: list[Any] = []
        already_processed = 0
        for item in tiles:
            if item.datetime is None:
                logging.warning("Skipping %s – missing datetime metadata", item.id)
                continue
            timestamp = item.datetime.strftime("%Y%m%dT%H%M%S")
            if writer.already_processed(item.id, timestamp):
                logging.info("Skipping %s %s (already in CSV)", item.id, timestamp)
                already_processed += 1
                continue
            pending.append(item)

        if not pending:
            logging.info("All tiles already processed – nothing to do.")
            # Must match started_at, which is timezone aware. utcnow() is naive
            # and subtracting the two raises, so the resume path (every tile
            # already in the CSV) used to crash instead of exiting cleanly.
            finished_at = dt.datetime.now(dt.timezone.utc)
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

            if item.datetime is None:
                logging.warning("Skipping %s – missing datetime metadata", item.id)
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
            if small.ndim == 4:
                small = small.squeeze(0)
            _, h4, w4 = small.shape

            if landmask_is_raster:
                land_mask = land_mask_from_raster(
                    config.landmask_path, dataset.odc.geobox, w4, h4
                )
            elif landmask_template is not None:
                land_mask = make_land_mask(landmask_template, w4, h4)
            else:  # pragma: no cover - unreachable, both branches are covered
                raise RuntimeError("no land mask available")

            classification = classify_tile(
                small,
                land_mask,
                config.thresholds,
                model,
                device,
                rgb_preview,
                baseline_str,
            )

            tile_stats = summarise_masks(
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

            # The class raster is the one artefact here that cannot be
            # reconstructed from anything else afterwards. The overlay has the
            # classes blended into the photograph and the CSV has only totals,
            # so without this a viewer that wants per-cell classes means
            # reprocessing the entire archive a second time.
            try:
                write_scene_export(
                    item.id,
                    ts,
                    classification.masks,
                    export_rgb(dataset),
                    classes_dir,
                    scenes_dir,
                    bounds=list(dataset.odc.geobox.boundingbox),
                    # The EPSG code, not the full WKT: a viewer needs the identifier
                    # and 1100 copies of a 1.4 kB projection definition help nobody.
                    crs=_epsg_or_wkt(dataset.odc.geobox.crs),
                    indices={
                        "ndsi": classification.ndsi,
                        "ndwi": classification.ndwi,
                    },
                    extra={
                        "sun_elev": item.properties.get("view:sun_elevation"),
                        "eo_cloud_cover": item.properties.get("eo:cloud_cover"),
                    },
                )
            except Exception as error:  # noqa: BLE001 - a viewer file is not
                # worth losing a measured scene over; the CSV row is written
                # either way and the export can be rebuilt from a rerun.
                logging.warning("scene export failed for %s: %s", item.id, error)

            metadata: dict[str, float | int | str | None] = {
                "eo_cloud_cover": item.properties.get("eo:cloud_cover"),
                "sun_elev": item.properties.get("view:sun_elevation"),
                "sun_azim": item.properties.get("view:sun_azimuth"),
            }
            writer.write(item.id, ts, tile_stats, metadata)

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

    finished_at = dt.datetime.now(dt.timezone.utc)
    elapsed = (finished_at - started_at).total_seconds()
    avg = sum(proc_times) / len(proc_times) if proc_times else 0.0
    stats_summary: dict[str, float | int | str] = {
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


class PartialReadError(RuntimeError):
    """A scene came back with one or more bands silently filled with nodata."""


def _reject_partial_reads(dataset: Any, tile_id: str) -> None:
    """Refuse a scene whose bands disagree about where the data is missing.

    ESA defines NO_DATA as DN = 0, and a genuine gap is geometric: the swath
    edge, or the corner of the tile, falls outside the AOI in *every* band at
    once.  A read that fails silently is not geometric.  It leaves one band full
    of fill while its neighbours are complete, which is exactly what was observed
    under concurrent loading: a scene whose green band was 100 per cent nodata
    and whose other twelve bands had none at all.

    So the test is agreement, not absolute level.  Measured over nine scenes
    read serially, including two with real swath-edge gaps of 5.6 and 7.9 per
    cent, no band's nodata share sat more than 0.15 percentage points above the
    median of the thirteen.  The two corrupted scenes measured +10.5 and +94.4
    points.

    A tight spread threshold nevertheless proved wrong, and it is worth saying
    why rather than just widening it.  The thirteen bands are not all native 10 m:
    B11 and B12 are 20 m, and B01, B09 and B10 are 60 m, so at a swath edge they
    resample onto the analysis grid with genuinely different fill fractions.  A
    one point rule therefore rejected real observations, an estimated hundred or
    more across the archive, for doing something entirely legitimate.

    So the primary test is the SIGNATURE of the failure rather than a tolerance.
    A failed curl read returns a band that is essentially all fill while its
    neighbours are complete: the observed case had green 100 per cent nodata and
    the other twelve at zero.  Resampling can never do that.  A generous spread
    check stays as a second net for the partial version of the same fault.

    The tell downstream is unmistakable and worth knowing: with NIR zeroed,
    NDWI = (green - 0)/(green + 0) = 1 exactly, so the scene is published as a
    plausible open-water day with mean_ndwi_water of 1.0.

    Raising here rather than logging is deliberate: the caller retries, and a
    scene that cannot be read cleanly must be recorded as a failure rather than
    quietly published as an observation.
    """
    fractions = []
    for band in BAND_SELECTION:
        if band not in dataset.data_vars:
            continue
        fractions.append((band, float(np.mean(np.asarray(dataset[band]) == 0))))
    if len(fractions) < 3:
        return
    median = float(np.median([value for _, value in fractions]))

    # Primary: a blank band in a scene that is not itself blank.
    for band, value in fractions:
        if value >= BLANK_BAND_SHARE and median <= NOT_A_BLANK_SCENE:
            raise PartialReadError(
                f"{tile_id}: band {band!r} came back {value:.1%} fill while the "
                f"median band is {median:.1%}. A whole band of fill in a scene "
                f"that has data is a failed read, not geometry. Downstream this "
                f"publishes as open water with mean_ndwi_water = 1.0."
            )

    # Second net: gross disagreement short of a fully blank band.
    for band, value in fractions:
        if value - median > PARTIAL_READ_TOLERANCE:
            raise PartialReadError(
                f"{tile_id}: band {band!r} is {value:.1%} nodata against a "
                f"median of {median:.1%} across the other bands, which is too "
                f"far apart to be resampling at the swath edge"
            )


def _warn_if_archive_is_device_dependent(
    config: RunConfig, device: torch.device
) -> None:
    """Warn when the device was picked for the run rather than chosen for it.

    The large device split is gone: inference no longer runs under autocast, and
    with it removed cpu and mps produce the same cloud mask.  Measured on three
    scenes with the current argmax mask, the two devices disagreed on 0.0000 per
    cent of cells, against 0.01 to 0.22 per cent when autocast was still on.  The
    residue is float ordering, up to 1.8e-5 in class probability, which only
    matters where two classes are within that of each other.

    What is still a hazard is leaving the choice implicit.  `resolve_device(None)`
    returns mps on this Mac and cpu on a machine without it, so the same command
    can write a slightly different archive depending on where it ran, and nothing
    in the output says which happened.  The manifest records the device after the
    fact; pinning it in config decides the question before the run.

    mps is the faster option and is safe to use: 32 ms per scene against 171 ms
    on cpu, which over 1550 scenes is about 3.6 minutes either way and is not
    worth optimising.  Pick one and write it down.
    """
    if config.device is not None:
        return
    logging.warning(
        "No device was configured, so %s was auto-selected. A machine without "
        "it would pick something else and reproduce this archive only to within "
        "float ordering. Pin `device` in the run config before an archive run.",
        device.type,
    )


def _stream_datasets(items: Iterable[Any], config: RunConfig) -> Iterator[Any]:
    """Fetch each scene's bands into memory, ahead of and in parallel with the loop.

    This used to hand `load()` to a thread pool and call it a download.  It was
    not one.  `odc.stac.load(..., chunks={})` returns dask arrays, so every task
    finished in about 30 ms having touched the network exactly zero times, and
    the pool was parallelising the construction of a task graph.  The 13 COG
    reads actually happened later and one after another, on the main thread, the
    first time `.values` was touched inside `build_rgb_preview` and
    `reflectance_cube`.  `download_workers` was therefore a knob wired to
    nothing, which is why turning it up had never helped.

    Two things follow from forcing the read here instead.

    The reads now overlap.  A band read is almost pure round-trip latency: the
    13 bands of one measured scene took 60.9 s serially at 17 per cent CPU and
    7.8 s with one thread per band, on the same scene and the same connection.

    And red, green and blue are fetched once rather than twice.  Under lazy
    loading `build_rgb_preview` pulled those three bands, then `reflectance_cube`
    pulled all 13 again from a graph that caches nothing: 16 band reads per
    scene, of which 3 were repeats, measured at 26 per cent of total wall clock.
    With the dataset materialised up front both callers read the same arrays out
    of memory.

    Order is preserved, and at most ``download_workers + decode_queue_size``
    scenes are held at once so a long run cannot outrun the classifier and fill
    RAM with prefetched bands.

    All band reads share ONE pool rather than each scene thread starting its own.
    That is not a tidiness point.  With a nested arrangement, four scene threads
    each running a 13-thread dask compute, reads started coming back silently
    filled with the nodata value instead of pixels: in one measured run three of
    five scenes were affected, one of them with the whole green band replaced by
    fill while every other band was clean.  Nothing raised.  The scene simply
    became wrong, and since green drives both NDSI and NDWI it became wrong in
    the two indices the whole product rests on.  Neither level of parallelism
    reproduced it alone.  Sharing a single bounded pool keeps the concurrency
    without the nesting, and `_reject_partial_reads` below is the net underneath.
    """
    conc = config.concurrency
    band_workers = max(1, conc.band_workers)
    in_flight = max(1, conc.download_workers)
    depth = in_flight + max(0, conc.decode_queue_size)

    def load_item(it: Any, read_pool: cf.ThreadPoolExecutor) -> Any:
        failure: Exception | None = None
        for attempt in range(1, LOAD_ATTEMPTS + 1):
            try:
                dataset = load(
                    [it],
                    geopolygon=config.search_aoi,
                    bands=BAND_SELECTION,
                    chunks={},
                )
                # Materialise here, on this worker thread, rather than leaving a
                # lazy graph for the main loop to walk band by band.
                dataset = dataset.compute(scheduler="threads", pool=read_pool)
                _reject_partial_reads(dataset, getattr(it, "id", "?"))
                return dataset
            except Exception as exc:  # pragma: no cover - network-driven
                failure = exc
                if attempt < LOAD_ATTEMPTS:
                    logging.warning(
                        "Load attempt %d/%d failed for %s (%s); retrying",
                        attempt,
                        LOAD_ATTEMPTS,
                        getattr(it, "id", "?"),
                        exc,
                    )
                    time.sleep(LOAD_RETRY_BACKOFF_SECONDS * attempt)
        return failure

    with (
        cf.ThreadPoolExecutor(
            max_workers=band_workers, thread_name_prefix="band"
        ) as read_pool,
        cf.ThreadPoolExecutor(
            max_workers=in_flight, thread_name_prefix="scene"
        ) as pool,
    ):
        remaining = iter(items)
        queue: collections.deque[tuple[Any, cf.Future[Any]]] = collections.deque()

        def submit_next() -> None:
            nxt = next(remaining, None)
            if nxt is not None:
                queue.append((nxt, pool.submit(load_item, nxt, read_pool)))

        for _ in range(depth):
            submit_next()

        while queue:
            item, future = queue.popleft()
            dataset = future.result()
            submit_next()
            yield item, dataset


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
