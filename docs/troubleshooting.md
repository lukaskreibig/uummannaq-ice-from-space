# Troubleshooting

For a long archive run specifically, see
[`reprocessing-runbook.md`](reprocessing-runbook.md), which covers resume,
validation and the failure table for an unattended job.

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| The run finishes fast with an almost empty CSV, log full of 403 | `AWS_NO_SIGN_REQUEST` is not set | `export AWS_NO_SIGN_REQUEST=YES`. The Sentinel-2 bucket is public but anonymous access has to be asked for. |
| `HeaderMismatchError` on start | The CSV was written by an older column layout | Point `--output-dir` at a fresh directory, or pass `--overwrite-csv`. Appending would produce rows of two widths. |
| A warning that the CSV ended mid-row | A previous run was killed during a write | Nothing to do. The fragment is trimmed on open and that scene is processed again. |
| The second run over a finished window used to raise `can't subtract offset-naive and offset-aware datetimes` | `pipeline.py` mixed `utcnow()` with a timezone-aware `started_at` on the resume path | Fixed. If it reappears, look for a naive `datetime` next to `started_at`. |
| `scripts/check_summary.py` fails the `tiles` gate | A scene from 30QUL, 60UXB or 23XMJ reached the CSV | Those catalogue records have whole-planet bounding boxes, so the AOI coverage floor in `stac.py` scores them 1.0. Delete those rows and re-run the affected days. |
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
