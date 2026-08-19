# Overview

## Context

This codebase powers the sea-ice classification component that was originally developed for the climate-dashboard project. It focuses on Sentinel-2 L1C imagery over the Uummannaq fjord (north-west Greenland) and labels each pixel as:

- solid ice (bright yellow overlay)
- light ice (cyan overlay)
- open water (blue)
- cloud (grey, derived from a CNN)
- land (brown, via a static landmask)
- nodata / missing observations (magenta)

The shape-based heuristics and cloud model are tuned for the narrow fjord AOI and the late-winter / early-summer seasonal range in 2025. The legacy exploration notebooks, visualisations, and historical CSVs are archived under `archive/legacy_pipeline`.

## Architecture

```
┌────────────────────┐      ┌────────────────────┐      ┌─────────────────────┐
│   CLI / Config      ├────▶│   Pipeline Runner   ├────▶│    Output Writers    │
└────────┬───────────┘      └──────────┬─────────┘      └──────────┬──────────┘
         │                             │                           │
         ▼                             ▼                           ▼
┌────────────────────┐      ┌────────────────────┐      ┌─────────────────────┐
│   STAC Utilities    │      │  Torch Cloud Model │      │  Quicklooks & CSV   │
└────────────────────┘      └────────────────────┘      └─────────────────────┘
```

- `uummannaq_ice.cli` parses user arguments, derives `RunConfig` instances, and bootstraps logging.
- `uummannaq_ice.config` encapsulates AOI geometry, thresholds, concurrency limits, and asset paths.
- `uummannaq_ice.stac` searches the Element84 catalog and deduplicates tiles per observation date.
- `uummannaq_ice.pipeline` orchestrates streaming loads, cloud inference, rule-based masks, and persistence.
- `uummannaq_ice.processing` performs the heavy lifting (reflectance cube generation, indices, masks, overlays).
- `uummannaq_ice.output` tracks the summary CSV and ensures we never double-count tiles.
- Packaged assets live under `uummannaq_ice/models` and `uummannaq_ice/assets`.

## Execution flow (high-level)

1. CLI builds a `RunConfig` using defaults or command-line overrides.
2. Pipeline fetches STAC items for the AOI and date range; the CSV is inspected to skip already processed tiles.
3. Tiles are streamed through a thread pool. Each job loads an `xarray.Dataset` via `odc-stac.load`.
4. For each dataset:
   - An RGB quicklook is generated.
   - DN values are converted to TOA reflectance (baseline-aware), then average pooled to 40 m.
   - The MobilenetV2 UNet predicts clouds. A static landmask marks land pixels.
   - NDSI/NDWI thresholds split the scene into solid/light ice and water.
   - Statistics, overlays, and panel figures are produced.
5. CSV rows are appended (or rewritten when `--overwrite-csv` is set) alongside EO metadata such as the reported cloud cover and sun geometry.
6. Logs report per-tile durations, averages, and a running ETA.
7. A manifest JSON is written under `run_metadata/` capturing configuration, environment (git commit, Python version), and the collected stats dictionary.

## Legacy relationship

The modern package is a direct refactor of `ice_classification_experimental_copy.py`. All heuristics, tensors, and outputs match the latest “solid + light” build (May 2025), but the logic is now modularised and testable. Keep the archive for context, comparative plots, and to replicate historical numbers when necessary. The archive reuses the same assets copied into the package (landmask + UNet checkpoint).
