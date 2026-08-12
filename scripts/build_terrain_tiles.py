#!/usr/bin/env python3
"""The mountain is 1206 m. Two global models lose most of it, so read the Arctic one.

    python3 scripts/build_terrain_tiles.py

The story flies a camera down to this fjord and pitches it over, and the beat it
lands on is the mountain whose shadow the classifier reads as open water. That
needs elevation, and it used to come from MapTiler, whose free plan ran out of
requests in August 2026 and suspended the key for sixteen days.

Three models, one mountain, measured on the same window:

    Mapbox terrain-dem-v1     198 m
    Copernicus DEM GLO-30     792 m     30 m posting
    ArcticDEM v4.1           1206 m      2 m posting

The height usually quoted for this peak is 1175 m, so ArcticDEM is the one
telling the truth. Mapbox fails through a Greenland gap rather than a latitude
cutoff: it is accurate at the Matterhorn (4252 against 4478), at Mount Rainier
(4391 against 4392) and at Kebnekaise at 67.9 degrees north (2108 against 2096).
Copernicus fails differently and more instructively: a 30 m grid cannot hold a
peak this steep and this narrow, and it loses 414 m of it. The first version of
this script used Copernicus and produced a fjord with a hill in it.

So the tiles come from ArcticDEM, which the Polar Geospatial Center builds for
exactly this latitude and publishes openly. They ship with the story and cannot
be rate limited, suspended or repriced.

WHY 512 PIXEL TILES. mapbox-gl picks its DEM zoom as the camera zoom plus
log2(tileSize / 512). At 256 that is one level coarser than the camera, so a
camera at zoom 11.4 was reading 50 m ground resolution out of tiles built at 25.
At 512 the offset is zero and the same tile count carries twice the detail in
each direction.

WHAT IT IS NOT. Not a global basemap: one bounding box, one fjord, zoom 8 to 11,
because that is what the camera path visits. mapbox-gl overzooms past maxzoom on
its own.
"""

from __future__ import annotations

import argparse
import json
import math
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window, from_bounds

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT.parent / "climate-dashboard/frontend/public/terrain"

STAC = "https://stac.pgc.umn.edu/api/v1/search"
COLLECTION = "arcticdem-mosaics-v4.1-2m"

# Every camera waypoint in scenesConfig.tsx sits within 0.3 degrees of the fjord,
# so this covers all of them with room for a 70 degree pitch to see past them.
# The same box as scripts/build_basemap_image.py, so ground and relief end
# together rather than one of them running out first.
BBOX = (-52.9, 70.4, -51.5, 71.0)
ZOOMS = range(8, 12)

# Web Mercator, the constants mapbox-gl and every XYZ scheme agree on.
EARTH_CIRCUMFERENCE = 2 * math.pi * 6378137.0
ORIGIN = -EARTH_CIRCUMFERENCE / 2.0
TILE = 512
# The floor of the terrain-RGB encoding, and its step.
BASE, STEP = -10000.0, 0.1
# ArcticDEM is a land model and marks the sea well below anything real.
NODATA_BELOW = -100.0


def tile_xy(lat: float, lng: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    x = int((lng + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def dem_hrefs(bbox: tuple[float, float, float, float]) -> list[str]:
    """Every ArcticDEM mosaic tile touching the box. Open data, no signing."""
    body = json.dumps(
        {"collections": [COLLECTION], "bbox": list(bbox), "limit": 50}
    ).encode()
    request = urllib.request.Request(
        STAC, data=body, headers={"Content-Type": "application/json"}
    )
    items = json.load(urllib.request.urlopen(request, timeout=180))["features"]
    return [item["assets"]["dem"]["href"] for item in items]


def mercator_grid(
    hrefs: list[str], bbox: tuple[float, float, float, float], zoom: int
) -> tuple[np.ndarray, int, int]:
    """The DEM on the tile grid of `zoom`, so that cutting tiles is slicing.

    One aligned array rather than a warp per tile: faster, and it guarantees
    neighbouring tiles agree on their shared edge, which a per tile warp does not.

    At 2 m over a box of roughly 78 by 111 km the source is 2.2 billion pixels and
    will not be read whole. Each mosaic tile is read through `out_shape` at about
    the target resolution, which makes rasterio pull the matching overview.
    """
    west, south, east, north = bbox
    x0, y0 = tile_xy(north, west, zoom)
    x1, y1 = tile_xy(south, east, zoom)
    cols, rows = (x1 - x0 + 1) * TILE, (y1 - y0 + 1) * TILE

    span = EARTH_CIRCUMFERENCE / 2**zoom
    left = ORIGIN + x0 * span
    top = -ORIGIN - y0 * span
    resolution = span / TILE
    transform = rasterio.Affine(resolution, 0, left, 0, -resolution, top)

    out = np.full((rows, cols), np.nan, dtype="float32")
    for index, href in enumerate(hrefs, 1):
        with rasterio.open(href) as src:
            bounds = transform_bounds("EPSG:4326", src.crs, *bbox)
            window = from_bounds(*bounds, src.transform).intersection(
                Window(0, 0, src.width, src.height)
            )
            if window.width < 2 or window.height < 2:
                continue
            # Read at roughly the target resolution so an overview is used.
            scale = max(1.0, min(window.width / cols, window.height / rows))
            shape = (
                max(1, int(window.height / scale)),
                max(1, int(window.width / scale)),
            )
            patch = src.read(
                1, window=window, out_shape=shape, resampling=Resampling.average
            ).astype("float32")
            patch[patch < NODATA_BELOW] = np.nan
            src_transform = src.window_transform(window) * rasterio.Affine.scale(
                window.width / shape[1], window.height / shape[0]
            )
            warped = np.full((rows, cols), np.nan, dtype="float32")
            reproject(
                source=patch,
                destination=warped,
                src_transform=src_transform,
                src_crs=src.crs,
                src_nodata=np.nan,
                dst_transform=transform,
                dst_crs="EPSG:3857",
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
        out = np.where(np.isnan(out), warped, out)
        print(f"    {index}/{len(hrefs)} merged, peak so far {np.nanmax(out):.0f} m")
    # Sea level wherever the land model has nothing, which here is the sea.
    return np.nan_to_num(out, nan=0.0), x0, y0


def encode(height: np.ndarray) -> np.ndarray:
    """Heights to the RGB triplet mapbox-gl decodes as `encoding: "mapbox"`.

    Rounded to the metre first. The encoding carries 0.1 m, which no terrain mesh
    on a screen can show and which puts noise in the low byte where PNG cannot
    compress it. Rounding costs nothing visible and takes the set from 45 MB to
    a third of that.
    """
    metres = np.rint(height)
    value = np.clip(np.rint((metres - BASE) / STEP), 0, 256**3 - 1).astype(np.uint32)
    rgb = np.empty(height.shape + (3,), dtype=np.uint8)
    rgb[..., 0] = (value >> 16) & 0xFF
    rgb[..., 1] = (value >> 8) & 0xFF
    rgb[..., 2] = value & 0xFF
    return rgb


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-zoom", type=int, default=max(ZOOMS))
    args = parser.parse_args(argv)

    print(f"ArcticDEM v4.1, 2 m, over {BBOX}")
    print("=" * 78)
    hrefs = dem_hrefs(BBOX)
    print(f"  {len(hrefs)} mosaic tile(s) from the Polar Geospatial Center")

    grid, x0, y0 = mercator_grid(hrefs, BBOX, args.max_zoom)
    print(f"  on the zoom {args.max_zoom} tile grid at {TILE} px: {grid.shape}")
    print(f"  highest point in the box: {grid.max():.0f} m")

    written = total_bytes = 0
    for zoom in range(min(ZOOMS), args.max_zoom + 1):
        step = 2 ** (args.max_zoom - zoom)
        rows, cols = grid.shape[0] // step, grid.shape[1] // step
        level = (
            grid[: rows * step, : cols * step]
            .reshape(rows, step, cols, step)
            .mean(axis=(1, 3))
            if step > 1
            else grid
        )
        zx0, zy0 = x0 // step, y0 // step
        for ty in range(level.shape[0] // TILE):
            for tx in range(level.shape[1] // TILE):
                block = level[ty * TILE : (ty + 1) * TILE, tx * TILE : (tx + 1) * TILE]
                path = args.out / str(zoom) / str(zx0 + tx) / f"{zy0 + ty}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(encode(block), "RGB").save(path, optimize=True)
                written += 1
                total_bytes += path.stat().st_size
        print(f"  z{zoom}: {level.shape[1] // TILE} by {level.shape[0] // TILE} tiles")

    print()
    print(f"  {written} tiles, {total_bytes / 1024 / 1024:.1f} MB, under {args.out}")
    print()
    print(
        "  Point a mapbox-gl raster-dem source at /terrain/{z}/{x}/{y}.png with\n"
        f'  encoding "mapbox", tileSize {TILE} and maxzoom {args.max_zoom}.'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
