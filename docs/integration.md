# Integration Guide

## Command-line usage

```bash
uummannaq-ice --config-file config/baseline.yaml \
  --max-tiles 10 \
  --log-level INFO
```

- CLI flags override YAML configuration values when provided.
- Use `--threads` and `--decode-queue` to tune download concurrency for different environments.

## Python API

```python
from pathlib import Path
from uummannaq_ice import load_run_config, run_pipeline

config = load_run_config(Path("config/single_tile_debug.yaml"), overrides={
    "output_dir": Path("out/custom-run"),
    "max_tiles": 5,
})

stats = run_pipeline(config)
print(stats)
```

## Airflow example

```python
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

from uummannaq_ice import load_run_config, run_pipeline

def run_ice_pipeline(**_: dict):
    config = load_run_config(Path("config/baseline.yaml"), overrides={
        "output_dir": Path("/data/out/runs") / datetime.utcnow().strftime("%Y%m%d"),
    })
    run_pipeline(config)


with DAG("uummannaq_ice", start_date=datetime(2025, 1, 1), schedule_interval="0 6 * * *") as dag:
    PythonOperator(task_id="process_tiles", python_callable=run_ice_pipeline)
```

## Dagster/op orchestrators

- Wrap the call to `run_pipeline` in an op/asset and surface the manifest JSON as metadata.
- Use the returned stats dictionary for quality gates (e.g., fail run if `tiles_failed > 0`).

## Docker

- CPU: `docker build -f docker/Dockerfile -t uummannaq-ice:cpu .`
- CUDA: `docker build -f docker/Dockerfile.cuda -t uummannaq-ice:cuda .`
- Run with bind mounts for outputs:

```bash
docker run --rm -v "$PWD/out":/app/out uummannaq-ice:cpu --config-file config/baseline.yaml
```

## Benchmarking

The `scripts/benchmark.py` helper drives repeated runs (unique output directories per iteration) and prints summary statistics:

```bash
python scripts/benchmark.py --config config/single_tile_debug.yaml --repeat 3 --max-tiles 2
```

## CI/CD

- GitHub Actions (`.github/workflows/ci.yml`) enforces linting, formatting, typing, and tests on Python 3.10–3.12.
- Use branch protection rules to require the CI workflow before merging.
- Version bumps should update `CHANGELOG.md` and tag releases; Docker images can be built from the provided Dockerfiles.
