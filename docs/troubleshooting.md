# Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `pip install` fails with `No matching distribution found for torch` | Platform-specific wheels | Use the version selector at https://pytorch.org/get-started/locally/ and then rerun `pip install -e .`. On macOS, `torch==2.7.0` / `torchvision==0.22.0` / `torchaudio==2.7.0` work for CPU/MPS. |
| `ModuleNotFoundError: uummannaq_ice` | Editable install missing | Run `pip install -e .` (or `make install`) from the repo root. |
| `RuntimeError: CUDA requested but not available` | `--device cuda` set without GPU | Drop the override or run inside the CUDA Docker image. |
| CSV not updated despite tiles available | Existing CSV rows keep being skipped | Delete or move the CSV, or run with `--overwrite-csv` / set `overwrite_csv: true` in YAML. |
| Landmask misalignment in overlays | AOI or landmask mismatch | Regenerate the landmask PNG to match the updated AOI grid, or switch to a different config file. |
| `odc.stac.load` timeouts | Network hiccups or large concurrency | Retry the run; consider lowering `download_workers` in the config or using the benchmarking script to identify bottlenecks. |
| CI fails on Linux due to GDAL | System libs missing locally | Install `gdal-bin` and `libgdal-dev` (apt) or follow Rasterio’s platform-specific instructions. |

## Debug tips

- Enable verbose logging with `--log-level DEBUG` or in YAML.
- Inspect the manifest JSON under `out/<run>/run_metadata/` for the resolved configuration, git commit, and tile statistics.
- Use `scripts/benchmark.py` with `--max-tiles 1` to reproduce flaky cases quickly.
- For deeper inspection, call `run_pipeline` from a notebook and inspect the returned stats dictionary.
