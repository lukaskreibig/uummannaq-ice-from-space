# Models

## Cloud segmentation (MobilenetV2 UNet)

- **File**: `src/uummannaq_ice/models/unet_mobv2_v2.pt`
- **Architecture**: `segmentation_models_pytorch.Unet` with MobilenetV2 encoder, 13-channel input, 4 output classes.
- **Lineage**: This is the May 2025 checkpoint used in `ice_classification_experimental_copy.py`. It was trained on Sentinel-2 crops labelled with the CloudSEN12 taxonomy (cloud / thin cloud / surface / nodata).
- **Usage**: Loaded once per run (`model.load_state_dict(...)`, strict=False to ignore auxiliary keys) and evaluated under `torch.autocast`. Output channel 1 corresponds to “cloud”.

### Retraining guidance

1. Gather annotated tiles (cloud masks) into `data/raw/sentinel/<year>/...`.
2. Reuse the notebooks under `archive/legacy_pipeline/ice-final/*` as a starting point, or build a clean PyTorch Lightning training loop.
3. Export checkpoints to `models/` with descriptive names (e.g., `cloud_unet_2025Q3.pt`).
4. Update `docs/models.md` with provenance (date, dataset, metrics) and set `default_checkpoint_path()` to the new file.
5. Validate overlays manually before rolling out.

## Landmask

- **File**: `src/uummannaq_ice/assets/landmask_template.png`
- **Resolution**: Matches the downsampled 40 m grid for the current AOI.
- **Origin**: Digitised mask from the legacy pipeline. Stored as grayscale (white = land).
- **Maintenance**: When the AOI changes, regenerate via GIS:
  - Create a vector polygon for land boundaries.
  - Rasterise to the Sentinel-2 grid (EPSG:4326) and export as PNG.
  - Verify alignment by overlaying on an RGB tile.

## Legacy models

`models/legacy/` contains Keras checkpoints (`backup_best_cloud_model.keras`, `backup_best_ice_model.keras`) and the legacy `cloud_unet_rgb.pt` export that originally lived in `archive/legacy_pipeline/ice-final/`. These binaries exceed GitHub's size limits and are therefore ignored by git—copy them into `models/legacy/` manually (or retrieve them from a secure artefact store) if you need to reproduce the old notebooks. Treat the directory as read-only unless you intend to resurrect the earlier architecture.

## Recommendations

- Version model artefacts alongside metrics (e.g., store a `metrics.json` next to the checkpoint).
- Consider exporting ONNX or TorchScript variants if you plan to serve the model in a non-Python environment.
- Integrate automated QA (overlay diffing) whenever a new model is introduced.
