# Uummannaq Ice From Space

Sentinel-2 processing pipeline that classifies the Uummannaq fjord (Greenland) scene into solid ice, light ice, water, cloud, land and nodata pixels. The modern code lives in `src/uummannaq_ice` and exposes a CLI (`uummannaq-ice`) that performs the end‑to‑end workflow: STAC discovery, STAC loading via `odc-stac`, MobilenetV2 UNet cloud masking, rule-based ice classification, and reporting/visualisation.

The original exploratory notebooks and scripts from the climate-dashboard project remain under `archive/legacy_pipeline` for traceability.

## Read this first

The pipeline produces one ice-fraction number per day. Three documents say what
that number is, what it is not, and how the current version was arrived at.

| | |
|---|---|
| [docs/methods.md](docs/methods.md) | Every processing step and the reason for each parameter, with the measurement behind it. |
| [docs/limitations.md](docs/limitations.md) | What the method cannot do, quantified, ordered by how much it could change a conclusion. |
| [docs/investigation-log.md](docs/investigation-log.md) | How four systematic errors were found and corrected. None of them raised an exception. |
| [docs/generalisation.md](docs/generalisation.md) | What it would take to run this at any Arctic coastal site, and what already does. |

Short version of what the record supports: the later seasons hold about **20
percent** less spring ice than the earlier ones, at **p = 0.056** over nine
seasons, with no detectable monotone trend and interannual variability nearly as
large as the difference between periods. The direction is consistent. The
certainty is not there, and nine winters is why.


## Quick start

```bash
python3 -m venv .venv              # Python 3.10 – 3.13 are supported
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
# Install PyTorch (pick the command that matches your platform)
# macOS / CPU / MPS:
pip install "torch==2.7.0" "torchvision==0.22.0" "torchaudio==2.7.0"
# CUDA 12.4 (Linux/Windows) (not tested):
# pip install "torch==2.7.0+cu124" "torchvision==0.22.0+cu124" "torchaudio==2.7.0+cu124" \
#   --index-url https://download.pytorch.org/whl/cu124
pip install -e .

# (optional) install development tooling + hooks
make dev

# Run the pipeline with the baseline YAML config (May–June 2025 AOI)
uummannaq-ice --config-file config/baseline.yaml --output-dir out/runs/latest
```

Use `uummannaq-ice --help` to view all parameters (AOI override, thresholds, device selection, etc.).

If you need a different build (e.g., other CUDA versions), follow the [official PyTorch install selector](https://pytorch.org/get-started/locally/) and then run `pip install -e .` afterwards.

## Repository layout

```
archive/                # Unmodified legacy notebooks/scripts/outputs from climate-dashboard
config/                 # YAML run configurations (supports inheritance)
data/                   # Raw/interim/processed datasets (ignored by git by default)
docs/                   # Extended documentation (architecture, pipeline, datasets, integration)
docker/                 # Container definitions (CPU + CUDA)
notebooks/              # Exploratory notebooks (moved from legacy pipeline)
scripts/                # Utilities (benchmarking, satellite scraping)
src/uummannaq_ice/      # Production Python package and CLI
tests/                  # Pytest suite (unit + mocked integration)
out/                    # Default runtime outputs (Git-ignored)
summary_test_singleimage.csv  # Historical output sample kept for reference
```

The packaged assets are:

- `src/uummannaq_ice/models/unet_mobv2_v2.pt`: MobilenetV2 UNet checkpoint (cloud segmentation).
- `src/uummannaq_ice/assets/landmask_template.png`: Reference landmask aligned to the AOI grid.
- `config/*.yaml`: Versioned run presets (supports `extends` for layered configs).

## Pipeline overview

`docs/pipeline.md` describes every stage in detail; at a high level:

1. Search the Element84 STAC (`sentinel-2-l1c`) within the configured AOI and date range, deduplicated by observation date.
2. Stream tiles through `odc-stac.load`, average-pool to 40 m, align with the landmask, and derive NDSI/NDWI.
3. Run the MobilenetV2 UNet cloud classifier (threshold 0.5 after morphological closing).
4. Classify pixels into solid ice / light ice / water masks using the thresholds (default NDSI=0.52/0.31, NDWI=0.25).
5. Persist quicklook overlays + panels, aggregate CSV statistics (includes EO cloud cover and sun geometry), and log ETA estimates.

## Documentation

- `docs/overview.md` – domain background, architecture, AOI context.
- `docs/architecture.md` – system diagram, components, and extensibility points.
- `docs/pipeline.md` – processing stages, concurrency model, threshold rationale.
- `docs/datasets.md` – data organisation, expected file formats, landmask provenance.
- `docs/development.md` – environment setup, tooling, testing, and release process.
- `docs/integration.md` – CLI, Python, scheduler, Docker, and benchmarking guidance.
- `docs/troubleshooting.md` – symptom-based fixes and debug tips.
- `docs/models.md` – MobilenetV2 cloud model lineage and retraining guidance.
- `CHANGELOG.md` – project history (update when shipping user-facing changes).

## Configuration & manifests

- YAML configs in `config/` capture run presets; use `extends` for overrides (`single_tile_debug.yaml` extends `baseline.yaml`).
- CLI overrides merge with YAML via `--config-file`.
- Each run writes `run_metadata/run_<timestamp>.json` with the resolved configuration, environment details, git commit, and summary stats.

## Testing & QA

- `make lint`, `make typecheck`, and `make test` mirror the CI pipeline (Ruff, mypy, pytest with coverage).
- The pytest suite includes mask aggregation unit tests, YAML inheritance checks, and a mocked pipeline smoke test.
- `scripts/benchmark.py` benchmarks repeated runs with unique output directories and prints aggregated stats.
- GitHub Actions (`.github/workflows/ci.yml`) runs across Python 3.10–3.12 on every push/PR.

## Deployment

- CPU Docker image: `docker build -f docker/Dockerfile -t uummannaq-ice:cpu .`
- CUDA Docker image (untested): `docker build -f docker/Dockerfile.cuda -t uummannaq-ice:cuda .`
- Execute via Docker with volume mounts: `docker run --rm -v "$PWD/out":/app/out uummannaq-ice:cpu --config-file config/baseline.yaml`
- The benchmarking script and manifest JSON make it easy to plug the pipeline into Airflow, Dagster, Prefect, or cron (see `docs/integration.md`).

## Legacy material

Legacy experiments from the climate-dashboard repo (including `ice_classification_experimental_copy.py` and historical CSV outputs) live under `archive/legacy_pipeline`. They are read-only snapshots for documentation and should not be edited unless you intend to replicate old behaviour.

To revisit the original scripts:

```bash
cd archive/legacy_pipeline/ice-final
python ice_classification_experimental_copy.py --log DEBUG
```

Note that the original heavy checkpoints have been moved to `models/legacy/` (ignored by git); see `archive/legacy_pipeline/ice-final/README.md` for details before running the legacy notebooks.

## Next steps

1. Run the pipeline for a full 2024/2025 winter season to build a long-term CSV baseline.
2. Integrate the CLI/Docker image into your data orchestration layer (cron, Airflow, Dagster) following `docs/integration.md`.
3. Consider promoting `scripts/scrape_satellite_images.py` into a proper ingestion module for MODIS daily imagery.
