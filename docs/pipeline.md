# Pipeline Details

## 1. Configuration and logging

- The CLI (`uummannaq_ice.cli`) accepts ISO dates, AOI GeoJSON, checkpoint/landmask overrides, concurrency settings, and individual threshold tweaks.
- Defaults live in `config.Thresholds` and `config.Concurrency`; read them there
  rather than here, because they move. At the time of writing:
  - AOI: polygon around the Uummannaq fjord (`config.DEFAULT_AOI`), about
    14 by 18 km, 267.3 km².
  - Thresholds: NDSI solid 0.70, NDSI light 0.40, NDWI 0.20, visible brightness
    floor 0.10, NIR brightness floor 0.17, nodata fraction flag 0.20.
    Authoritative copy: `config/baseline.yaml`, which carries the derivation of
    each one. The brightness floors are not a detail: over this fjord NDSI runs
    about 0.94 for solid ice, thin ice and open water alike, because all three
    are nearly black at 1.6 um, so it is the floors that separate ice from
    water and not the index.
  - All five were re-derived on radiometrically corrected reflectance by
    `scripts/derive_thresholds.py`, over eighteen acquisitions spanning February
    to October and both sides of the baseline 04.00 boundary. What is still open
    is narrower: that derivation produced `ndsi_solid` 0.83 and the shipped value
    is 0.70, because 0.83 empties the solid class over a fjord that is frozen
    shore to shore. The disagreement decides only what the two class names mean,
    not the published series, which is `solid + light`. See
    [limitations.md](limitations.md#the-solidlight-split).
- Logging format matches the original script (`"%H:%M:%S  LEVEL message"`).
- For a full archive reprocess, use `docs/reprocessing-runbook.md`, not this
  page.

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
2. Convert Sentinel-2 DN to TOA reflectance. ESA baseline 04.00, from
   25 January 2022, carries `RADIO_ADD_OFFSET = -1000`, so from that baseline on
   the conversion is `DN/10000 - 0.1`; before it, `DN/10000`.

   This was wrong for a long time and every published number came out of the
   wrong version. The code added `+0.1` to the older era and subtracted nothing
   from the newer, leaving **both** eras 0.1 above true reflectance. Measured on
   the 2023-08-18 scene, correcting the sign alone moved the ice fraction from
   0.004 to 0.584: 58 percent of an open summer fjord called ice. Two things had
   to change with it, and are described in sections 6 and 6b.
3. Stack the 13 bands in the order expected by the MobilenetV2 UNet.
4. Average-pool to 40 m resolution via `torch.nn.functional.avg_pool2d`.
5. Resize the static landmask to match the downsampled grid.

## 5. Cloud inference

- `segmentation_models_pytorch.Unet("mobilenet_v2", classes=4)` is loaded with the packaged checkpoint.
- The tensor is padded to a multiple of 32 and evaluated under `torch.amp.autocast`. The four CloudSEN12 classes are reduced by argmax and everything not called clear is masked, then closed with a 3 by 3 element. There is no probability threshold.
- A morphological closing (`scipy.ndimage.binary_closing`) smooths small gaps.
- The model honours the preferred device order: MPS → CUDA → CPU unless overridden.

## 6. Rule-based masks

Computed from the downsampled cube:

Let `usable = ~cloud & ~land & ~nodata` and
`bright = green > vis_bright_min & nir > nir_bright_min`.

| Mask       | Condition (vectorised)                                                                 |
|------------|----------------------------------------------------------------------------------------|
| `ice_solid`| `ndsi > ndsi_solid` **and `bright`** and `usable`                                       |
| `ice_light`| `ndsi_light < ndsi < ndsi_solid` **and `bright`** and `usable`                          |
| `water`    | `ndwi > ndwi_thr` and not ice and `usable`                                             |
| `land`     | From the resized landmask                                                              |
| `cloud`    | From the UNet                                                                          |
| `nodata`   | Every band equal to the per-baseline void reflectance, within `1e-4`                    |

### 6a. Why the brightness gate exists

NDSI alone does not separate ice from water at top of atmosphere. Open water is
nearly black in the SWIR, so its NDSI runs about 0.82, **higher** than April
fast ice at about 0.72. While reflectances carried the +0.1 bias, dark pixels
were compressed far more than bright ones, and that compression was doing the
separating. Remove the bias and the thresholds alone classify the open fjord as
ice.

The gate is the Dozier construction the MODIS snow products still use: ice
requires a high NDSI **and** brightness in the visible and the near infrared,
because snow and ice are bright in both and water is dark in both.

Note what this does to the job NDSI is left with. Ice versus water is now
decided by brightness. NDSI's remaining work is mostly separating solid ice from
thin or wet ice, and the two thresholds should be re-derived with that in mind.

### 6b. Why the void test changed

The void test used to be `sum(bands) < 1e-6`. After the sign fix that would
throw away real water: 13 bands of -0.09 sum to -1.2, and an actually empty
pixel sums to -1.3. The test now compares every band against the known
per-baseline void value, which is `0.0` before baseline 04.00 and `-0.1` from
04.00 on.

### 6c. Percentages

Percentages are stored at 4-decimal precision and divide by the **whole grid**,
land, cloud and data gaps included. The `_clear` columns divide instead by the
cells where the surface could be judged at all, `~cloud & ~land & ~nodata`.

Mean NDSI and NDWI are written as a blank string when no pixel qualifies. A
binary `edge_gap` flag is raised when nodata ≥ `nodata_fraction`.

A mean NDWI outside -1 to 1 in the output is a real signal, not a rounding
artefact: it means the selected cells had `green + nir` at or below zero, so
they were picked by an unstable ratio rather than by being wet. `ice_solid` and
`ice_light` are shielded from this by the brightness gate; `water` is not.
`scripts/check_summary.py` reports it.

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
