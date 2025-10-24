# Datasets & Assets

## Directory conventions

The repository separates runtime code (`src/uummannaq_ice`) from data artefacts. Git ignores the heavy directories by default so you can keep local caches without committing them.

```
data/
├── raw/          # untouched downloads (Sentinel-2 COGs, chips, STAC exports, etc.)
├── interim/      # intermediate artefacts (e.g., chunked numpy arrays, masks)
├── processed/    # analysis-ready datasets / exports
└── examples/     # hand-picked reference imagery (moved from "good ice examples")
```

Legacy training sets (clustered by `train`, `train_new_kmeans`, etc.) were relocated from `src/data` to `data/raw/sentinel/*`. These are not part of the automated pipeline but remain for future retraining experiments.

## Packaged assets

| Path                                         | Purpose                                           |
|----------------------------------------------|---------------------------------------------------|
| `src/uummannaq_ice/models/unet_mobv2_v2.pt`  | MobilenetV2 UNet checkpoint (cloud segmentation)  |
| `src/uummannaq_ice/assets/landmask_template.png` | Landmask raster aligned to the AOI grid       |

Both files are shipped with the package to keep the CLI usable immediately. The same files are left in `archive/legacy_pipeline/ice-final/` for parity with historical notebooks.

## External sources

- **Sentinel-2 L1C**: Retrieved via Element84 STAC (`sentinel-2-l1c`). The STAC client defaults to unsigned requests (`AWS_NO_SIGN_REQUEST=YES`).
- **MODIS daily JPGs**: `scripts/scrape_satellite_images.py` downloads DMI “Uummannaq” glamour shots (AQUA/TERRA). These end up in `data/raw/satellite/aqua` by default.
- **Landmask**: Derived from manual digitisation (see `archive/legacy_pipeline/ice-final/landmask_template.png`). Treat as a reference artefact; update via `gdalwarp` + manual QA if AOI changes.

## Outputs

- Runtime outputs are stored under `out/` by default. Within each run:

```
out/<run-name>/
├── summary.csv
└── quicklooks/
    ├── overlays/*.png
    └── panels/*.png
```

- `summary_test_singleimage.csv` in the repo root is an example output from a previous experiment and can be used to sanity-check column ordering.

## Data hygiene

- Do not commit `data/raw`, `data/interim`, or `data/processed`. They can easily exceed Git’s size limits.
- When generating new checkpoints or landmasks, keep provenance notes in `docs/models.md` or `docs/datasets.md`.
- Use descriptive run folders under `out/` (e.g., `out/2025_q2_baseline/`) so that archived quicklooks remain meaningful.
