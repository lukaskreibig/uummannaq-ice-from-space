"""Tests for the run-configuration loader.

These test the loader's BEHAVIOUR, not the contents of the shipped production
config. They used to assert the literal dates in config/baseline.yaml, so simply
retargeting a run at a different week turned the suite red while nothing was
actually broken. What matters here is that YAML values reach the config object,
that `extends` inherits and that a child can override a parent.

The thresholds ARE asserted against the shipped baseline, deliberately: those
four numbers define the published series and the story prints them, so a silent
edit should fail loudly.
"""

from pathlib import Path

import pytest
import yaml

from uummannaq_ice.config_loader import load_run_config

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE = REPO_ROOT / "config" / "baseline.yaml"
DEBUG_CONFIG = REPO_ROOT / "config" / "single_tile_debug.yaml"


def _write(path: Path, payload: dict) -> Path:
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_yaml_values_reach_the_config(tmp_path):
    cfg = _write(
        tmp_path / "run.yaml",
        {
            "stac_url": "https://earth-search.aws.element84.com/v1",
            "collection": "sentinel-2-l1c",
            "start_date": "2026-02-14",
            "end_date": "2026-06-29",
            "output_dir": "out/ignored",
        },
    )
    config = load_run_config(cfg, overrides={"output_dir": tmp_path})

    assert config.start_date.isoformat() == "2026-02-14"
    assert config.end_date.isoformat() == "2026-06-29"
    assert config.collection == "sentinel-2-l1c"
    assert config.output_dir == tmp_path.resolve()


def test_overrides_beat_the_file(tmp_path):
    # Both dates are set on purpose: leaving one out would fall through to the
    # package default and couple this test to whatever window is configured.
    cfg = _write(
        tmp_path / "run.yaml",
        {"start_date": "2026-02-14", "end_date": "2026-06-29", "max_tiles": 9},
    )
    config = load_run_config(cfg, overrides={"output_dir": tmp_path, "max_tiles": 1})

    assert config.max_tiles == 1
    assert config.start_date.isoformat() == "2026-02-14"


def test_extends_inherits_and_child_overrides(tmp_path):
    parent = _write(
        tmp_path / "parent.yaml",
        {"start_date": "2026-02-14", "end_date": "2026-06-29", "log_level": "INFO"},
    )
    child = _write(
        tmp_path / "child.yaml",
        {"extends": parent.name, "max_tiles": 1, "log_level": "DEBUG"},
    )
    config = load_run_config(child, overrides={"output_dir": tmp_path})

    # inherited from the parent
    assert config.start_date.isoformat() == "2026-02-14"
    assert config.end_date.isoformat() == "2026-06-29"
    # set by the child
    assert config.max_tiles == 1
    assert config.log_level == "DEBUG"


def test_shipped_configs_still_load(tmp_path):
    """A syntax error or a renamed key in the shipped configs must fail here."""
    for path in (BASELINE, DEBUG_CONFIG):
        config = load_run_config(path, overrides={"output_dir": tmp_path})
        assert config.start_date <= config.end_date
        assert config.collection
        assert config.output_dir == tmp_path.resolve()


def test_single_tile_debug_still_inherits_from_baseline(tmp_path):
    """The debug config's whole purpose is one tile off the baseline window."""
    baseline = load_run_config(BASELINE, overrides={"output_dir": tmp_path})
    debug = load_run_config(DEBUG_CONFIG, overrides={"output_dir": tmp_path})

    assert debug.start_date == baseline.start_date
    assert debug.max_tiles == 1
    assert debug.log_level == "DEBUG"


def test_published_thresholds_are_locked():
    """These numbers define the published series and the story prints them.

    Changing one is a legitimate decision, but it must be a deliberate one, so it
    has to break this test and the methodology copy at the same time.

    They were changed deliberately. The previous values (ndsi_solid 0.52,
    ndsi_light 0.31, ndwi 0.25) were tuned while every reflectance in the
    pipeline sat 0.1 too high, so they no longer mean what they meant once the
    baseline 04.00 offset was corrected. The current values were re-derived on
    corrected reflectance by scripts/derive_thresholds.py over eighteen scenes
    spanning February to October and both sides of the 25 January 2022 boundary.
    The two brightness floors are locked here as well: since the correction they
    are what actually separates ice from water, so they belong in the same lock
    as the NDSI cuts rather than sitting unwatched in the dataclass defaults.
    """
    config = load_run_config(BASELINE, overrides={"output_dir": Path("out/ignored")})
    assert config.thresholds.ndsi_solid == pytest.approx(0.70)
    assert config.thresholds.ndsi_light == pytest.approx(0.40)
    assert config.thresholds.ndwi == pytest.approx(0.20)
    assert config.thresholds.vis_bright_min == pytest.approx(0.10)
    assert config.thresholds.nir_bright_min == pytest.approx(0.17)


def test_concurrency_defaults_survive_the_loader(tmp_path):
    config = load_run_config(BASELINE, overrides={"output_dir": tmp_path})
    assert config.concurrency.download_workers >= 1


def test_the_dataclass_fallback_matches_the_shipped_yaml():
    """A run without --config must classify by the same rule as one with it.

    The derived thresholds were written into baseline.yaml while the dataclass
    kept the pre-correction values, so a plain `uummannaq-ice` invocation
    silently used ndsi_solid 0.52 where the configured run used 0.83. That does
    not fail, it produces a complete and plausible archive against the wrong
    rule, which is the worst shape a defect can take.
    """
    from uummannaq_ice.config import Thresholds, build_config

    configured = load_run_config(
        BASELINE, overrides={"output_dir": Path("out/ignored")}
    ).thresholds
    fallback = build_config(output_dir="out/ignored").thresholds

    for field in (
        "ndsi_light",
        "ndsi_solid",
        "ndwi",
        "vis_bright_min",
        "nir_bright_min",
        "nodata_fraction",
    ):
        assert getattr(fallback, field) == pytest.approx(
            getattr(configured, field)
        ), f"{field} differs between the dataclass default and baseline.yaml"
        assert getattr(Thresholds(), field) == pytest.approx(getattr(configured, field))
