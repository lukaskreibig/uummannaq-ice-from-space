from pathlib import Path

from uummannaq_ice.config_loader import load_run_config


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_load_baseline_config(tmp_path):
    cfg_path = REPO_ROOT / "config" / "baseline.yaml"
    config = load_run_config(cfg_path, overrides={"output_dir": tmp_path})

    assert config.start_date.isoformat() == "2025-05-06"
    assert config.end_date.isoformat() == "2025-06-25"
    assert config.output_dir == tmp_path.resolve()
    assert config.thresholds.ndsi_solid == 0.52
    assert config.concurrency.download_workers == 4


def test_config_inheritance(tmp_path):
    cfg_path = REPO_ROOT / "config" / "single_tile_debug.yaml"
    config = load_run_config(cfg_path, overrides={"output_dir": tmp_path})

    # inherits baseline dates
    assert config.start_date.isoformat() == "2025-05-06"
    # overrides max_tiles and log level
    assert config.max_tiles == 1
    assert config.log_level == "DEBUG"
    assert config.output_dir == tmp_path.resolve()
