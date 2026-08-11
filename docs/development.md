# Development Guide

## Environment

1. Create a virtual environment (Python 3.10 to 3.13 are supported) and install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip setuptools wheel
   # Install PyTorch (choose the variant matching your system):
   pip install "torch==2.7.0" "torchvision==0.22.0" "torchaudio==2.7.0"                    # macOS / CPU / MPS
   # pip install "torch==2.7.0+cu124" "torchvision==0.22.0+cu124" "torchaudio==2.7.0+cu124" \
   #   --index-url https://download.pytorch.org/whl/cu124                                    # CUDA 12.4
   pip install -e ".[dev,test]"
   ```

2. The optional `dev` extra installs IPython only; feel free to add lint/test tooling (e.g., `ruff`, `pytest`) locally.
3. If you plan to work in notebooks, store them under `notebooks/` (git tracks them) and keep large outputs in `out/`.

## Tooling shortcuts

- `make dev`: install project + dev/test/docs extras and set up pre-commit.
- `make lint` / `make format` / `make typecheck`: run Ruff and mypy targets.
- `make test`: execute the pytest suite with coverage.
- `pre-commit run --all-files`: mirror the CI checks locally.

## Running the pipeline locally

```bash
uummannaq-ice --start-date 2025-05-06 --end-date 2025-06-25 \
  --output-dir out/2025_q2 \
  --csv-name summary.csv \
  --log-level INFO
```

- Use `--max-tiles` when debugging to run a small subset.
- The CLI prints progress, rolling average, and ETA; monitor GPU usage separately if needed (`activity monitor`, `nvidia-smi`, etc.).

## Coding conventions

- The project follows the standard `src/` layout. Only production code belongs in `src/uummannaq_ice`.
- Keep computational functions side-effect free (e.g., `processing.summarise_masks`) to ease testing.
- Add concise comments only when logic is non-obvious (threshold rationale, data quirks).
- Update the relevant doc pages whenever you change thresholds, models, or data directories.

## Tests and validation

- Run `pytest` or `make test` for the headless suite (mask maths, config loader, and a mocked pipeline smoke test).
- Use `scripts/benchmark.py --max-tiles 1` for performance snapshots and to debug concurrency settings.
- Inspect `out/<run>/run_metadata/run_*.json` to confirm configuration + environment metadata.

## Releasing & collaboration

- Update `pyproject.toml` and `CHANGELOG.md` when cutting a release.
- CI (`.github/workflows/ci.yml`) enforces linting, typing, and tests, keep it green before merging.
- Docker images (`docker/Dockerfile*`) provide reproducible environments for clients and schedulers.

## Troubleshooting

| Symptom                                   | Likely cause / fix                                                   |
|-------------------------------------------|---------------------------------------------------------------------|
| `ModuleNotFoundError: torch`              | Install the correct torch build for your platform (see Quick start).|
| `RuntimeError: CUDA requested...`         | You forced `--device cuda` but no GPU is visible. Drop the flag.    |
| `ValueError` when loading AOI             | Ensure the GeoJSON is either a Polygon, Feature, or FeatureCollection.|
| STAC loads time out                       | Retry; `odc-stac` performs remote reads. Consider reducing threads. |
| Empty CSV despite run                     | All tiles were already present; delete/overwrite the CSV to rerun.  |
