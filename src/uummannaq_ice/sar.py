"""Sentinel-1 backscatter over the Uummannaq fjord, for cross-checking the optical series.

The optical pipeline reports days in February and March, when this fjord is
frozen with near certainty, on which almost no ice is found. Radar needs neither
sunlight nor a clear sky, so it can be asked directly whether the fjord was
frozen on those days. This module answers exactly one question per acquisition:
what was the median gamma0 over the fjord water surface, in decibels.

It deliberately does not classify. There is no threshold here and no ice
fraction. Turning a fjord median into an ice map would need per-cell confidence
this data does not support at this site, and the analysis in
`scripts/validate_sar.py` is built to work with a distribution of medians
instead.

Design notes, each of which is a decision that could have gone the other way:

**Ready-made RTC, not raw GRD.** Microsoft Planetary Computer publishes
`sentinel-1-rtc`, radiometrically terrain corrected gamma0 on a projected grid.
Raw GRD from AWS carries ground control points and no projection, so using it
would mean writing our own orthorectification against a DEM for fjord walls over
1000 m high. That is a project of its own, and getting it subtly wrong is
exactly the failure mode this repository has already suffered three times.

**The land mask's grid, not the scene's.** `assets/landmask.tif` is EPSG:32622
at 10 m, and most RTC scenes over this AOI are too, so the crop is usually a
plain window read with no resampling at all. Uummannaq sits near the boundary of
UTM zones 21N and 22N, though, and a minority of acquisitions arrive in
EPSG:32621; those are warped onto the mask grid with nearest neighbour, which
keeps the sensor's own values rather than inventing intermediate ones. Reusing
the optical land mask also means the two series measure approximately the same
water surface. Approximately, not exactly: see the note on area in
`docs/limitations.md`.

**No speckle filter.** The output is a median over about 2.5 million cells.
Speckle is multiplicative noise with a median that converges quickly at that
count, while a spatial filter would smear the shoreline and introduce its own
bias exactly where the land mask matters most.

**No incidence angle normalisation.** Relative orbits over this AOI differ by
roughly 2 dB for the same surface. Rather than model that away, the orbit is
recorded per scene so the analysis can stratify on it.

**HH, because that is what flies here.** Over Greenland the mission runs the
polar observation plan with HH and HV. Not one VV or VH acquisition exists over
this AOI, so no threshold calibrated on VV in the literature transfers.
"""

from __future__ import annotations

import json
import logging
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.windows import from_bounds

LOGGER = logging.getLogger(__name__)

STAC_SEARCH_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS_TOKEN_URL = (
    "https://planetarycomputer.microsoft.com/api/sas/v1/token/"
    "sentinel1euwestrtc/sentinel1-grd-rtc"
)
RTC_COLLECTION = "sentinel-1-rtc"

# The AOI used by the optical pipeline, so both series look at the same fjord.
AOI_BBOX: tuple[float, float, float, float] = (
    -52.336121,
    70.628226,
    -51.945564,
    70.788206,
)

LANDMASK_PATH = Path(__file__).with_name("assets") / "landmask.tif"

# A scene has to cover essentially the whole fjord or its median is a median of
# somewhere else. Measured over the archive, qualifying scenes come in at 1.000,
# so anything below this is a real gap rather than edge rounding.
MIN_VALID_SHARE = 0.98

# The land contrast, and why it is NOT a per-scene filter.
#
# Shifting the land mask 1000 m against a real scene (2021-03-10) moved the
# fjord median by only 0.17 dB, from -18.65 to -18.48, while the contrast
# between land and water fell from 5.75 dB to 1.99. A misaligned mask therefore
# produces a completely plausible number and nothing raises, which makes the
# contrast the one cheap diagnostic worth carrying on every scene.
#
# The first version of this module rejected scenes below 3 dB. That was wrong,
# and measuring showed why: a February ice anchor came in at 2.64 dB with the
# mask correctly aligned, because dry snow on the surrounding rock is radar dark
# in midwinter while the frozen fjord is not especially dark. The legitimate
# winter range and the misalignment range overlap, so no per-scene threshold can
# separate them, and one that tries throws away real observations and biases the
# sample towards summer.
#
# So alignment is checked GLOBALLY instead, in scripts/validate_sar.py: the mask
# is the same file on the same grid for every scene, so a georeferencing error
# would show up across the whole set rather than in one acquisition. Per scene,
# only a contrast at or below zero is rejected, because land darker than the
# fjord is not something this terrain does and points at a real fault.
MIN_LAND_CONTRAST_DB = 0.0

# gamma0 arrives as linear power. Zero and the -32768 fill both mean "no
# measurement" and would take the logarithm to minus infinity.
_LINEAR_FLOOR = 1e-8

SAR_CSV_HEADER: tuple[str, ...] = (
    "date",
    "scene_id",
    "acquired_utc",
    "polarisation",
    "relative_orbit",
    "orbit_state",
    "platform",
    "valid_share",
    "water_cells",
    "land_cells",
    "water_median_db",
    "water_p5_db",
    "water_p95_db",
    "land_median_db",
    "land_contrast_db",
    "passes_gates",
    "reject_reason",
)


class SarAccessError(RuntimeError):
    """Raised when the catalogue or the asset store cannot be reached."""


@dataclass(frozen=True, slots=True)
class SceneStats:
    """One acquisition, reduced to the numbers the analysis needs."""

    date: date
    scene_id: str
    acquired_utc: str
    polarisation: str
    relative_orbit: Optional[int]
    orbit_state: Optional[str]
    platform: Optional[str]
    valid_share: float
    water_cells: int
    land_cells: int
    water_median_db: float
    water_p5_db: float
    water_p95_db: float
    land_median_db: float
    land_contrast_db: float
    passes_gates: bool
    reject_reason: str

    def as_row(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "scene_id": self.scene_id,
            "acquired_utc": self.acquired_utc,
            "polarisation": self.polarisation,
            "relative_orbit": self.relative_orbit
            if self.relative_orbit is not None
            else "",
            "orbit_state": self.orbit_state or "",
            "platform": self.platform or "",
            "valid_share": round(self.valid_share, 4),
            "water_cells": self.water_cells,
            "land_cells": self.land_cells,
            "water_median_db": round(self.water_median_db, 3),
            "water_p5_db": round(self.water_p5_db, 3),
            "water_p95_db": round(self.water_p95_db, 3),
            "land_median_db": round(self.land_median_db, 3),
            "land_contrast_db": round(self.land_contrast_db, 3),
            "passes_gates": int(self.passes_gates),
            "reject_reason": self.reject_reason,
        }


class SasToken:
    """A Planetary Computer SAS token that renews itself before it expires.

    The tokens are handed out anonymously and last about 45 minutes. A full run
    takes longer than that, and a run that dies halfway leaves a partly filled
    result file that looks exactly like a complete one.
    """

    # Renew this far before the stated expiry, so a slow read cannot straddle it.
    _SAFETY_MARGIN = timedelta(minutes=5)

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._expires: Optional[datetime] = None

    def value(self) -> str:
        now = datetime.now(timezone.utc)
        if self._token is not None and self._expires is not None:
            if now + self._SAFETY_MARGIN < self._expires:
                return self._token

        try:
            with urllib.request.urlopen(SAS_TOKEN_URL, timeout=60) as response:
                payload = json.load(response)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
            raise SarAccessError(f"could not obtain a SAS token: {error}") from error

        token = payload.get("token")
        if not token:
            raise SarAccessError("SAS token response carried no token")

        expiry = payload.get("msft:expiry")
        self._token = str(token)
        self._expires = (
            _parse_iso8601(expiry) if expiry else now + timedelta(minutes=30)
        )
        LOGGER.debug("SAS token renewed, valid until %s", self._expires)
        return self._token


def _parse_iso8601(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def search_scenes(
    start: date,
    end: date,
    *,
    bbox: Sequence[float] = AOI_BBOX,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Every RTC acquisition intersecting the AOI between two dates, inclusive."""

    body = {
        "collections": [RTC_COLLECTION],
        "bbox": list(bbox),
        "datetime": f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z",
        "limit": limit,
    }
    request = urllib.request.Request(
        STAC_SEARCH_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            document = json.load(response)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
        raise SarAccessError(f"STAC search failed: {error}") from error

    features = document.get("features", [])
    # The catalogue returns newest first. Sorting makes every run's scene order
    # identical, which matters because the analysis is meant to be reproducible.
    features.sort(
        key=lambda item: (item["properties"].get("datetime", ""), item.get("id", ""))
    )
    return features


def scenes_by_date(
    features: Iterable[Mapping[str, Any]],
) -> dict[date, list[Mapping[str, Any]]]:
    """Group acquisitions by their UTC calendar day."""

    grouped: dict[date, list[Mapping[str, Any]]] = {}
    for feature in features:
        stamp = feature.get("properties", {}).get("datetime")
        if not stamp:
            continue
        day = _parse_iso8601(stamp).date()
        grouped.setdefault(day, []).append(feature)
    return grouped


def load_landmask(path: Path = LANDMASK_PATH) -> tuple[np.ndarray, Any, Any, Any]:
    """The optical pipeline's land mask, with the geometry needed to crop to it."""

    with rasterio.open(path) as dataset:
        land = dataset.read(1) > 0
        return land, dataset.bounds, dataset.crs, dataset.transform


def measure_scene(
    feature: Mapping[str, Any],
    land: np.ndarray,
    bounds: Any,
    mask_crs: Any,
    mask_transform: Any,
    token: SasToken,
    *,
    polarisation: str = "hh",
) -> SceneStats:
    """Crop one acquisition to the fjord and reduce it to medians in decibels."""

    properties = feature.get("properties", {})
    scene_id = str(feature.get("id", "unknown"))
    acquired = str(properties.get("datetime", ""))
    day = _parse_iso8601(acquired).date() if acquired else date(1970, 1, 1)

    asset = feature.get("assets", {}).get(polarisation)
    if asset is None:
        return _rejected(
            day,
            scene_id,
            acquired,
            polarisation,
            properties,
            f"no {polarisation.upper()} asset",
        )

    href = f"{asset['href']}?{token.value()}"
    with rasterio.Env(GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2"):
        with rasterio.open(href) as dataset:
            if str(dataset.crs) == str(mask_crs):
                # The common case over this AOI. A plain window read, no
                # resampling, so the cells are the sensor's own.
                window = from_bounds(*bounds, transform=dataset.transform)
                values = dataset.read(
                    1,
                    window=window,
                    boundless=True,
                    fill_value=np.nan,
                    out_shape=land.shape,
                ).astype("float64")
            else:
                # Uummannaq sits close to the UTM 21N and 22N boundary and the
                # RTC products follow the scene's own zone, so a minority of
                # acquisitions arrive in EPSG:32621. Refusing them outright cost
                # four scenes out of 62 for no good reason. Warping onto the
                # mask grid is exact where it matters here: nearest neighbour
                # keeps every value the sensor produced rather than inventing
                # intermediate ones, and the fill stays NaN so warped-in edges
                # are counted as missing rather than as dark water.
                with WarpedVRT(
                    dataset,
                    crs=mask_crs,
                    transform=mask_transform,
                    width=land.shape[1],
                    height=land.shape[0],
                    resampling=Resampling.nearest,
                    src_nodata=dataset.nodata,
                    nodata=np.nan,
                    dtype="float32",
                ) as warped:
                    values = warped.read(1).astype("float64")

    valid = np.isfinite(values) & (values > _LINEAR_FLOOR)
    valid_share = float(valid.mean())

    water_valid = valid & ~land
    land_valid = valid & land
    if water_valid.sum() == 0 or land_valid.sum() == 0:
        return _rejected(
            day,
            scene_id,
            acquired,
            polarisation,
            properties,
            "no valid cells over water or over land",
            valid_share=valid_share,
        )

    decibels = 10.0 * np.log10(np.where(valid, values, np.nan))
    water_median = float(np.nanmedian(decibels[water_valid]))
    land_median = float(np.nanmedian(decibels[land_valid]))
    contrast = land_median - water_median

    reason = ""
    if valid_share < MIN_VALID_SHARE:
        reason = f"valid share {valid_share:.3f} below {MIN_VALID_SHARE}"
    elif not math.isfinite(contrast):
        reason = "land contrast not finite"
    elif contrast <= MIN_LAND_CONTRAST_DB:
        reason = f"land contrast {contrast:.2f} dB, land is not brighter than the fjord"

    return SceneStats(
        date=day,
        scene_id=scene_id,
        acquired_utc=acquired,
        polarisation=polarisation.upper(),
        relative_orbit=properties.get("sat:relative_orbit"),
        orbit_state=properties.get("sat:orbit_state"),
        platform=properties.get("platform"),
        valid_share=valid_share,
        water_cells=int(water_valid.sum()),
        land_cells=int(land_valid.sum()),
        water_median_db=water_median,
        water_p5_db=float(np.nanpercentile(decibels[water_valid], 5)),
        water_p95_db=float(np.nanpercentile(decibels[water_valid], 95)),
        land_median_db=land_median,
        land_contrast_db=contrast,
        passes_gates=not reason,
        reject_reason=reason,
    )


def _rejected(
    day: date,
    scene_id: str,
    acquired: str,
    polarisation: str,
    properties: Mapping[str, Any],
    reason: str,
    *,
    valid_share: float = 0.0,
) -> SceneStats:
    nan = float("nan")
    return SceneStats(
        date=day,
        scene_id=scene_id,
        acquired_utc=acquired,
        polarisation=polarisation.upper(),
        relative_orbit=properties.get("sat:relative_orbit"),
        orbit_state=properties.get("sat:orbit_state"),
        platform=properties.get("platform"),
        valid_share=valid_share,
        water_cells=0,
        land_cells=0,
        water_median_db=nan,
        water_p5_db=nan,
        water_p95_db=nan,
        land_median_db=nan,
        land_contrast_db=nan,
        passes_gates=False,
        reject_reason=reason,
    )
