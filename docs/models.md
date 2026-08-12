# Models

## Cloud segmentation (MobilenetV2 UNet)

- **File**: `src/uummannaq_ice/models/unet_mobv2_v2.pt`
- **Architecture**: `segmentation_models_pytorch.Unet` with MobilenetV2 encoder, 13-channel input, 4 output classes.
- **Lineage**: third party, not ours, and the previous wording here was ambiguous about that. The legacy entry point `archive/legacy_pipeline/ice-final/ice_classification_experimental_copy.py` declares `CHECKPOINT_FILE = "UNetMobV2_V2.pt"`, builds the matching architecture with `encoder_weights=None`, and loads the file while stripping `module.` and `model.` prefixes with `strict=False`. It contains no training code. Prefix stripping is what a foreign checkpoint needs, and the filename, the architecture and the four-class CloudSEN12 label set (clear / thick cloud / thin cloud / cloud shadow, `processing.py:275-278`) all match the model published by the CloudSEN12 project.
- **Licence**: not recorded, and not guessed. See [NOTICE](https://github.com/lukaskreibig/uummannaq-ice-from-space/blob/main/NOTICE) at the repository root. The terms have to be read at the source and honoured before this checkpoint is redistributed as part of anything, and a public repository is already redistribution.
- **Usage**: Loaded once per run (`model.load_state_dict(...)`, strict=False to ignore auxiliary keys) and evaluated in **full precision on every device**. `torch.autocast` used to be enabled and was removed because it made the mask depend on the hardware. The decision is an `argmax` over all four channels and every class that is not `clear` counts as obscured; the earlier single-channel rule reading “channel 1 is cloud” has been retired.

### Retraining guidance

1. Gather annotated tiles (cloud masks) into `data/raw/sentinel/<year>/...`.
2. Reuse the notebooks under `archive/legacy_pipeline/ice-final/*` as a starting point, or build a clean PyTorch Lightning training loop.
3. Export checkpoints to `models/` with descriptive names (e.g., `cloud_unet_2025Q3.pt`).
4. Update `docs/models.md` with provenance (date, dataset, metrics) and set `default_checkpoint_path()` to the new file.
5. Validate overlays manually before rolling out.

## Land mask

- **File**: `src/uummannaq_ice/assets/landmask.tif`
- **Grid**: EPSG:32622, 10 m, 1474 by 1812, carrying its own CRS and transform. It
  is resampled onto each scene rather than assumed to align with it.
- **Origin**: derived from imagery by `scripts/derive_landmask.py`. The
  hand-digitised `landmask_template.png` beside it is the superseded predecessor
  and is kept only so the legacy notebooks still run.
- **Maintenance**: rerun `scripts/derive_landmask.py`. **Do not rasterise to
  EPSG:4326 and export as PNG**, which is what this section used to instruct. A
  PNG carries no transform, reprojecting one without scaling its transform is one
  of the five errors in [investigation-log.md](investigation-log.md), and it laid
  a band of false land over open water across the whole archive.

## Legacy models

`models/legacy/` contains Keras checkpoints (`backup_best_cloud_model.keras`, `backup_best_ice_model.keras`) and the legacy `cloud_unet_rgb.pt` export that originally lived in `archive/legacy_pipeline/ice-final/`. These binaries exceed GitHub's size limits and are therefore ignored by git, so copy them into `models/legacy/` manually (or retrieve them from a secure artefact store) if you need to reproduce the old notebooks. Treat the directory as read-only unless you intend to resurrect the earlier architecture.

## Recommendations

- Version model artefacts alongside metrics (e.g., store a `metrics.json` next to the checkpoint).
- Consider exporting ONNX or TorchScript variants if you plan to serve the model in a non-Python environment.
- Integrate automated QA (overlay diffing) whenever a new model is introduced.
