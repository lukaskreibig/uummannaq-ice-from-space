"""High-level helpers for the Uummannaq sea-ice classification pipeline."""

from .config import RunConfig, Thresholds, build_config
from .config_loader import load_run_config
from .pipeline import run_pipeline

__all__ = [
    "RunConfig",
    "Thresholds",
    "build_config",
    "load_run_config",
    "run_pipeline",
]

# Provide a human-readable package version when the project is installed.
try:  # pragma: no cover - executed only in installed distributions
    from importlib.metadata import version as _version

    __version__ = _version("ummannaq-ice-from-space")
except Exception:  # pragma: no cover
    __version__ = "0.0.0"
