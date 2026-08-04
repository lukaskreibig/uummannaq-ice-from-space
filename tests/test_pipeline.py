from datetime import datetime

import numpy as np
import torch
from affine import Affine
from PIL import Image

from uummannaq_ice.config import build_config
from uummannaq_ice.pipeline import run_pipeline
from uummannaq_ice.processing import BANDS


class FakeBand:
    def __init__(self, value: float):
        self._values = np.full((8, 8), value, dtype=np.float32)

    def __getitem__(self, _index):
        return self

    @property
    def values(self):  # noqa: D401 - compatibility shim
        return self._values


class FakeGeobox:
    """Just enough geometry for the land-mask reprojection path."""

    width = 64
    height = 64
    transform = Affine(10.0, 0.0, 500000.0, 0.0, -10.0, 7860000.0)

    class crs:  # noqa: N801 - mimics the odc geobox attribute
        @staticmethod
        def to_wkt():
            return "EPSG:32622"


class FakeOdc:
    geobox = FakeGeobox()


class FakeDataset:
    def __init__(self):
        self.data_vars = {band: FakeBand(self._value_for_band(band)) for band in BANDS}
        self.computed_with = None
        # The pipeline asks the dataset for its geometry so a georeferenced land
        # mask can be reprojected onto the pooled analysis grid.
        self.odc = FakeOdc()

    def __getitem__(self, key):
        return self.data_vars[key]

    def compute(self, **kwargs):
        # The pipeline materialises the bands up front instead of leaving a lazy
        # dask graph for the main loop to walk one band at a time.
        self.computed_with = kwargs
        return self

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
        return torch.zeros(
            (batch, 4, height, width), dtype=torch.float32, device=tensor.device
        )


def test_run_pipeline_smoke(tmp_path, monkeypatch):
    import uummannaq_ice.pipeline as pipeline

    monkeypatch.setattr(pipeline, "fetch_tiles", lambda cfg: [FakeItem("TILE_TEST")])
    loaded: list[dict] = []

    def fake_load(items, geopolygon, bands, chunks):
        loaded.append({"bands": bands, "chunks": chunks})
        return FakeDataset()

    monkeypatch.setattr(pipeline, "load", fake_load)
    monkeypatch.setattr(
        pipeline, "load_cloud_model", lambda path, device: FakeModel(device)
    )
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

    # Only the 13 classified bands are requested. The `visual` asset would
    # otherwise be downloaded on every scene and never read.
    assert loaded and tuple(loaded[0]["bands"]) == tuple(BANDS)
    assert "visual" not in loaded[0]["bands"]


class BandDict:
    """Minimal stand-in for the loaded xarray Dataset."""

    def __init__(self, arrays):
        self.data_vars = arrays

    def __getitem__(self, key):
        return self.data_vars[key]


def _cube(nodata_fraction_per_band):
    arrays = {}
    for band, fraction in nodata_fraction_per_band.items():
        arr = np.ones((1, 10, 100), dtype=np.uint16)
        arr[:, :, : int(100 * fraction)] = 0
        arrays[band] = arr
    return BandDict(arrays)


def test_partial_read_check_accepts_a_shared_swath_edge():
    """A real gap is geometric: every band misses the same pixels."""
    from uummannaq_ice.pipeline import _reject_partial_reads

    # 8 per cent nodata in every band, as a swath edge actually looks.
    _reject_partial_reads(_cube(dict.fromkeys(BANDS, 0.08)), "TILE")


def test_partial_read_check_rejects_one_band_filled_with_nodata():
    """The observed concurrency failure: green is fill, everything else is fine.

    Green drives both NDSI and NDWI, so this scene would not look broken, it
    would look like a different fjord.
    """
    import pytest

    from uummannaq_ice.pipeline import PartialReadError, _reject_partial_reads

    fractions = dict.fromkeys(BANDS, 0.0)
    fractions["green"] = 1.0
    with pytest.raises(PartialReadError, match="green"):
        _reject_partial_reads(_cube(fractions), "TILE")


def test_partial_read_check_tolerates_small_resampling_differences():
    """Measured spread across bands on clean scenes was under 0.2 points."""
    from uummannaq_ice.pipeline import _reject_partial_reads

    fractions = dict.fromkeys(BANDS, 0.056)
    fractions["red"] = 0.058
    _reject_partial_reads(_cube(fractions), "TILE")


def test_stream_datasets_preserves_order_and_bounds_prefetch(monkeypatch):
    """Scenes come back in submission order, and prefetch stays bounded.

    The bound is what keeps a 1550-scene run from filling RAM: the loader is
    much faster than the classifier, so without a limit every finished scene
    would queue up as ~78 MB of materialised bands.
    """
    import threading
    import time as _time

    import uummannaq_ice.pipeline as pipeline

    lock = threading.Lock()
    fetched: list[str] = []

    class FetchedDataset:
        def __init__(self, name):
            self.name = name
            # Uniformly present bands, so the partial-read check passes.
            self.data_vars = {band: np.ones((4, 4), dtype=np.uint16) for band in BANDS}

        def __getitem__(self, key):
            return self.data_vars[key]

        def compute(self, **_kwargs):
            return self

    def fake_load(items, geopolygon, bands, chunks):
        with lock:
            fetched.append(items[0])
        return FetchedDataset(items[0])

    monkeypatch.setattr(pipeline, "load", fake_load)

    depth = 2 + 1  # download_workers + decode_queue_size, as configured below
    config = build_config(download_workers=2, decode_queue_size=1, band_workers=3)
    items = [f"scene-{i}" for i in range(12)]

    got = []
    for index, (item, dataset) in enumerate(pipeline._stream_datasets(items, config)):
        got.append((item, dataset.name))
        # Give the pool a chance to run ahead if nothing were holding it back.
        _time.sleep(0.01)
        with lock:
            ahead = len(fetched)
        assert ahead <= min(len(items), depth + 1 + index), (index, ahead)

    assert [item for item, _ in got] == items
    assert [name for _, name in got] == items
