# Pipeline Details

## 1. Configuration and logging

- The CLI (`uummannaq_ice.cli`) accepts ISO dates, AOI GeoJSON, checkpoint/landmask overrides, concurrency settings, and individual threshold tweaks.
- Defaults (replicating the 2025 study):
  - AOI: polygon around the Uummannaq fjord (`config.DEFAULT_AOI`).
  - Date window: 2025-05-06 → 2025-06-25.
  - Thresholds: NDSI solid 0.52, NDSI light 0.31, NDWI 0.25, nodata fraction flag 0.20.
  - Threading: 4 concurrent loads, decode queue size 3.
- Logging format matches the original script (`"%H:%M:%S  LEVEL message"`).

## 2. STAC query

1. Open the Element84 STAC endpoint (`https://earth-search.aws.element84.com/v1`).
2. Search the `sentinel-2-l1c` collection with `intersects=AOI` and `datetime=<start/end>`.
3. Deduplicate by observation date so we only keep one tile per day.
4. Sort chronologically and clamp to `--max-tiles` when requested.

## 3. Prefetching and dataset loading

Tiles are submitted to a `ThreadPoolExecutor`. Each worker calls:

```python
load([item], geopolygon=config.search_aoi, chunks={})
```

- This keeps memory low by not chunking the `xarray.Dataset`.
- Failures are captured and logged without crashing the run (e.g., intermittent S3 timeouts).
- The pipeline skips tiles whose `(tile_id, timestamp)` already exist in the CSV (unless `--overwrite-csv` is used).

## 4. Reflectance cube preparation

Per tile:

1. Extract RGB quicklook at 512×512 for the panel layout.
2. Convert Sentinel-2 DN to TOA reflectance (`dn * 0.0001` plus +0.1 shift for baselines < 4).
3. Stack the 13 bands in the order expected by the MobilenetV2 UNet.
4. Average-pool to 40 m resolution via `torch.nn.functional.avg_pool2d`.
5. Resize the static landmask to match the downsampled grid.

## 5. Cloud inference

- `segmentation_models_pytorch.Unet("mobilenet_v2", classes=4)` is loaded with the packaged checkpoint.
- The tensor is padded to a multiple of 32, evaluated under `torch.amp.autocast`, and the cloud channel (index 1) is thresholded at 0.5.
- A morphological closing (`scipy.ndimage.binary_closing`) smooths small gaps.
- The model honours the preferred device order: MPS → CUDA → CPU unless overridden.

## 6. Rule-based masks

Computed from the downsampled cube:

| Mask       | Condition (vectorised)                                                                 |
|------------|----------------------------------------------------------------------------------------|
| `ice_solid`| `ndsi > ndsi_solid` and not cloud/land/nodata                                          |
| `ice_light`| `ndsi_light < ndsi < ndsi_solid` and not cloud/land/nodata                             |
| `water`    | `ndwi > ndwi_thr` and not (ice or cloud or land or nodata)                             |
| `land`     | From the resized landmask                                                              |
| `cloud`    | From the UNet                                                                          |
| `nodata`   | Sum of spectral bands < `1e-6`                                                         |

Percentages are stored at 4-decimal precision. Mean NDSI/NDWI are computed conditionally (blank string when no pixels qualify). A binary `edge_gap` flag is raised when nodata ≥ `nodata_fraction`.

## 7. Outputs

- **Overlays**: RGBA compositing with semi-transparent layers (identical colour palette to the legacy script).
- **Panels**: 6-up plot (RGB, cloud mask, landmask, solid ice, light ice, overlay). Saved at 150 dpi.
- **CSV**: Columns match the legacy format plus EO metadata:

```
tile_id, timestamp, solid_px, light_px, water_px, cloud_px, land_px, nodata_px,
unknown_px, solid_pct, light_pct, water_pct, cloud_pct, land_pct, nodata_pct,
mean_ndsi_solid, mean_ndsi_light, mean_ndwi_water, eo_cloud_cover, sun_elev,
sun_azim, edge_gap
```

- EO properties (`eo:cloud_cover`, `view:sun_elevation`, `view:sun_azimuth`) are stored when available; otherwise they are left blank.
- Runtime statistics (per-tile duration, rolling average, ETA) are logged. GPU caches are flushed between tiles.

## 8. Failure handling

- Dataset load exceptions are logged and skipped (the CSV remains untouched).
- Missing RGB bands cause the tile to be skipped (matching previous behaviour).
- The CLI exit code is non-zero only on argument/initialisation errors; individual tile failures do not abort the run.

## 9. Extending the pipeline

Recommended extension points:

- Add cloud probability band persistence for later QA (write `.npy` per tile).
- Introduce ensemble thresholds or dynamic water detection based on seasonal context.
- Replace the static landmask with a vector AOI if the area of interest changes.
- Integrate the CLI into scheduled workflows; the project is installable thanks to the `pyproject.toml` metadata.

## 10. Run manifests

- After every invocation, `run_metadata/run_<timestamp>.json` stores:
  - Resolved configuration (`RunConfig`) as JSON-safe primitives.
  - Aggregated stats (`tiles_processed`, failures, elapsed seconds, average seconds/tile).
  - Environment snapshot (Python version, platform, git commit).
- Use the manifest files to audit runs, compare configurations, or drive downstream QA pipelines.
