# Legacy Assets

The original climate-dashboard repository stored trained Keras checkpoints and a secondary PyTorch model inside this folder. Those binaries exceed GitHub's 100 MB limit, so they now live outside version control under `models/legacy/from_archive/` (ignored by git).

If you need them, copy the files into that directory with the same filenames:

- `backup_best_cloud_model.keras`
- `backup_best_ice_model.keras`
- `cloud_unet_rgb.pt`

The cleaned notebooks and scripts remain available here with outputs stripped for reasonable repository size.
