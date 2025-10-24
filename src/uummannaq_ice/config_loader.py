"""Load pipeline configuration from YAML files."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional

import yaml

from .config import Concurrency, RunConfig, Thresholds, build_config


def load_run_config(
    path: Path,
    *,
    overrides: Optional[Mapping[str, Any]] = None,
) -> RunConfig:
    """Load a :class:`RunConfig` from a YAML file, supporting inheritance."""
    data = _resolve_config(path)
    if overrides:
        data = _deep_merge(data, dict(overrides))
    return _build_from_mapping(data, base_dir=path.parent)


def _resolve_config(path: Path) -> MutableMapping[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Top-level config structure must be a mapping in {path}")

    base = raw.get("extends")
    if base:
        base_path = (path.parent / base).resolve()
        parent_cfg = _resolve_config(base_path)
        merged = _deep_merge(
            parent_cfg, {k: v for k, v in raw.items() if k != "extends"}
        )
        return merged
    return deepcopy(raw)


def _build_from_mapping(data: Mapping[str, Any], *, base_dir: Path) -> RunConfig:
    kwargs: dict[str, Any] = {}
    if "start_date" in data:
        kwargs["start_date"] = _parse_date(data["start_date"])
    if "end_date" in data:
        kwargs["end_date"] = _parse_date(data["end_date"])
    if "stac_url" in data:
        kwargs["stac_url"] = data["stac_url"]
    if "collection" in data:
        kwargs["collection"] = data["collection"]
    if "output_dir" in data:
        kwargs["output_dir"] = base_dir / Path(data["output_dir"])
    if "csv_filename" in data:
        kwargs["csv_filename"] = data["csv_filename"]
    if "quicklook_subdir" in data:
        kwargs["quicklook_subdir"] = data["quicklook_subdir"]
    if "checkpoint_path" in data:
        kwargs["checkpoint_path"] = _resolve_optional_path(
            base_dir, data["checkpoint_path"]
        )
    if "landmask_path" in data:
        kwargs["landmask_path"] = _resolve_optional_path(
            base_dir, data["landmask_path"]
        )
    if "overwrite_csv" in data:
        kwargs["overwrite_csv"] = bool(data["overwrite_csv"])
    if "max_tiles" in data:
        kwargs["max_tiles"] = data["max_tiles"]
    if "log_level" in data:
        kwargs["log_level"] = data["log_level"]
    if "device" in data:
        kwargs["device"] = data["device"]

    thresholds_cfg = data.get("thresholds")
    if isinstance(thresholds_cfg, Mapping):
        kwargs["thresholds"] = Thresholds(
            **{key: value for key, value in thresholds_cfg.items() if value is not None}
        )

    concurrency_cfg = data.get("concurrency")
    if isinstance(concurrency_cfg, Mapping):
        kwargs["download_workers"] = concurrency_cfg.get(
            "download_workers",
            Concurrency().download_workers,
        )
        kwargs["decode_queue_size"] = concurrency_cfg.get(
            "decode_queue_size",
            Concurrency().decode_queue_size,
        )

    if "aoi_path" in data:
        kwargs["aoi_path"] = _resolve_optional_path(base_dir, data["aoi_path"])

    return build_config(**kwargs)


def _parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"Invalid date value in config: {value!r}")


def _resolve_optional_path(base_dir: Path, value: Any) -> Optional[Path]:
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    return path


def _deep_merge(
    base: MutableMapping[str, Any],
    incoming: Mapping[str, Any],
) -> MutableMapping[str, Any]:
    result = deepcopy(base)
    for key, value in incoming.items():
        if (
            key in result
            and isinstance(result[key], MutableMapping)
            and isinstance(value, Mapping)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def run_config_to_dict(config: RunConfig) -> dict[str, Any]:
    """Serialise a RunConfig into JSON-safe primitives."""
    data = asdict(config)
    data["start_date"] = config.start_date.isoformat()
    data["end_date"] = config.end_date.isoformat()
    data["output_dir"] = str(config.output_dir)
    data["csv_path"] = str(config.csv_path)
    data["quicklook_dir"] = str(config.quicklook_dir)
    data["checkpoint_path"] = str(config.checkpoint_path)
    data["landmask_path"] = str(config.landmask_path)
    data["thresholds"] = asdict(config.thresholds)
    data["concurrency"] = asdict(config.concurrency)
    if config.max_tiles is None:
        data["max_tiles"] = None
    return data
