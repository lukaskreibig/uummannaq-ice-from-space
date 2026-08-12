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
| `src/uummannaq_ice/assets/landmask.tif`      | Land mask, EPSG:32622, 10 m, derived from imagery |

Both files are shipped with the package to keep the CLI usable immediately. The same files are left in `archive/legacy_pipeline/ice-final/` for parity with historical notebooks.

## External sources

- **Sentinel-2 L1C**: Retrieved via Element84 STAC (`sentinel-2-l1c`). The STAC client defaults to unsigned requests (`AWS_NO_SIGN_REQUEST=YES`).
- **MODIS daily JPGs**: `scripts/scrape_satellite_images.py` downloads DMI “Uummannaq” glamour shots (AQUA/TERRA). These end up in `data/raw/satellite/aqua` by default.
- **Land mask**: `assets/landmask.tif`, derived from imagery by `scripts/derive_landmask.py` and carrying its own CRS and transform. The hand-digitised `landmask_template.png` beside it is the superseded predecessor, kept only so the legacy notebooks still run. Do not reintroduce it: reprojecting a PNG without scaling its transform is one of the five errors in [investigation-log.md](investigation-log.md), and it put a band of false land over open water.

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
