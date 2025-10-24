from datetime import datetime
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from uummannaq_ice.config import build_config
from uummannaq_ice.pipeline import run_pipeline
from uummannaq_ice.processing import BANDS


class FakeBand:
    def __init__(self, value: float):
        self._values = np.full((1, 8, 8), value, dtype=np.float32)

    def __getitem__(self, _index):
        return self

    @property
    def values(self):  # noqa: D401 - compatibility shim
        return self._values


class FakeDataset:
    def __init__(self):
        self.data_vars = {band: FakeBand(self._value_for_band(band)) for band in BANDS}

    def __getitem__(self, key):
        return self.data_vars[key]

    @staticmethod
    def _value_for_band(band: str) -> float:
        palette = {
            "green": 0.6,
            "swir16": 0.05,
            "red": 0.3,
            "nir": 0.2,
        }
        return palette.get(band, 0.1)


class FakeItem:
    def __init__(self, identifier: str):
        self.id = identifier
        self.datetime = datetime(2025, 5, 7, 15, 23, 19)
        self.properties = {
            "s2:processing_baseline": "04.00",
            "eo:cloud_cover": 12.0,
            "view:sun_elevation": 35.0,
            "view:sun_azimuth": 120.0,
        }


class FakeModel:
    def __init__(self, device: torch.device):
        self.device = device

    def eval(self):
        return self

    def to(self, device: torch.device):
        self.device = device
        return self

    def __call__(self, tensor: torch.Tensor) -> torch.Tensor:
        batch, _channels, height, width = tensor.shape
        return torch.zeros((batch, 4, height, width), dtype=torch.float32, device=tensor.device)


def test_run_pipeline_smoke(tmp_path, monkeypatch):
    import uummannaq_ice.pipeline as pipeline

    monkeypatch.setattr(pipeline, "fetch_tiles", lambda cfg: [FakeItem("TILE_TEST")])
    monkeypatch.setattr(pipeline, "load", lambda items, geopolygon, chunks: FakeDataset())
    monkeypatch.setattr(pipeline, "load_cloud_model", lambda path, device: FakeModel(device))
    monkeypatch.setattr(
        pipeline,
        "refresh_landmask",
        lambda path: Image.fromarray(np.zeros((8, 8), dtype=np.uint8), mode="L"),
    )

    config = build_config(
        start_date=datetime(2025, 5, 6).date(),
        end_date=datetime(2025, 5, 7).date(),
        output_dir=tmp_path,
        csv_filename="summary.csv",
        quicklook_subdir="quicklooks",
        overwrite_csv=True,
        log_level="INFO",
    )

    stats = run_pipeline(config)

    assert stats["tiles_processed"] == 1
    assert stats["tiles_failed"] == 0
    assert stats["tiles_skipped"] == 0

    csv_file = config.csv_path
    assert csv_file.exists()
    csv_content = csv_file.read_text().strip().splitlines()
    assert len(csv_content) == 2  # header + single row

    overlays = (config.quicklook_dir / "overlays").glob("*.png")
    panels = (config.quicklook_dir / "panels").glob("*.png")
    assert len(list(overlays)) == 1
    assert len(list(panels)) == 1

    manifest_dir = config.output_dir / "run_metadata"
    manifest_files = list(manifest_dir.glob("run_*.json"))
    assert manifest_files, "Manifest file was not created"
