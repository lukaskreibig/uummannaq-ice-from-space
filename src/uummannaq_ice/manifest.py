"""Run metadata capture for pipeline executions."""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .config_loader import run_config_to_dict


def write_manifest(
    *,
    config,
    stats: Mapping[str, Any],
    started_at: datetime,
    finished_at: datetime,
    manifest_path: Path,
) -> None:
    """Persist run metadata to disk."""
    payload = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": (finished_at - started_at).total_seconds(),
        "config": run_config_to_dict(config),
        "stats": dict(stats),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "executable": sys.executable,
        },
        "git": _git_snapshot(manifest_path.parent),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _git_snapshot(repo_root: Path) -> Mapping[str, Any]:
    try:
        commit = _run_git(["rev-parse", "HEAD"], cwd=repo_root)
        status = _run_git(["status", "--short"], cwd=repo_root)
    except Exception:
        return {"commit": None, "status": None}
    return {
        "commit": commit.strip(),
        "status": status.strip(),
    }


def _run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout
