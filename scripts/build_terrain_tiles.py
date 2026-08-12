#!/usr/bin/env python3
"""Mapbox thinks the mountain is 198 m high. It is not, so we bake our own relief.

    python3 scripts/build_terrain_tiles.py

The story flies a camera down to this fjord and pitches it over, and the beat it
lands on is the mountain whose shadow the classifier reads as open water. That
needs elevation data, and until now it came from MapTiler, whose free plan ran out
of requests in August 2026 and suspended the key for sixteen days.

The obvious replacement is Mapbox's own terrain-dem-v1, which the story already
pays for. It does not work here, and the reason is worth writing down because the
first explanation I reached for was wrong. It is not the SRTM cutoff at 60 degrees
north: measured against known peaks, Mapbox is accurate at the Matterhorn (4252
against 4478), at Mount Rainier (4391 against 4392) and at Kebnekaise, 67.9
degrees north (2108 against 2096). Over Uummannaq at 70.7 north it returns 198 m
where Copernicus DEM returns 792. It is a Greenland gap, not a latitude one.

So this builds terrain-RGB tiles from Copernicus DEM GLO-30, 30 m, free, read
through the same Planetary Computer catalogue the rest of this project uses. The
output is a few hundred PNGs that ship with the story and cannot be rate limited,
suspended or repriced.

WHAT IT IS NOT. It is not a global basemap. It covers one bounding box around one
fjord, at zoom levels 8 to 11, because that is what the camera path visits. At
zoom 11 a tile pixel is about 25 m on the ground here, which is already finer than
the 30 m source, so going further would invent detail. mapbox-gl overzooms a
raster-dem source past its maxzoom on its own.
"""

from __future__ import annotations

import argparse
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.warp import reproject

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT.parent / "climate-dashboard/frontend/public/terrain"

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SIGN = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
COLLECTION = "cop-dem-glo-30"

# Generous enough to hold every camera waypoint in scenesConfig.tsx with its
# pitch, tight enough that the whole set stays in the low tens of megabytes.
BBOX = (-53.3, 70.2, -51.2, 71.2)
ZOOMS = range(8, 12)

# Web Mercator, the constants mapbox-gl and every XYZ scheme agree on.
EARTH_CIRCUMFERENCE = 2 * math.pi * 6378137.0
ORIGIN = -EARTH_CIRCUMFERENCE / 2.0
TILE = 256
# The floor of the terrain-RGB encoding, and its step.
BASE, STEP = -10000.0, 0.1


def tile_xy(lat: float, lng: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    x = int((lng + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def dem_hrefs(bbox: tuple[float, float, float, float]) -> list[str]:
    """Every Copernicus DEM tile touching the box, signed for reading."""
    body = json.dumps(
        {"collections": [COLLECTION], "bbox": list(bbox), "limit": 100}
    ).encode()
    request = urllib.request.Request(
        STAC, data=body, headers={"Content-Type": "application/json"}
    )
    items = json.load(urllib.request.urlopen(request, timeout=120))["features"]
    signed = []
    for item in items:
        href = item["assets"]["data"]["href"]
        quoted = urllib.parse.quote(href, safe="")
        signed.append(
            json.load(urllib.request.urlopen(f"{SIGN}?href={quoted}", timeout=120))[
                "href"
            ]
        )
    return signed


def mercator_grid(
    hrefs: list[str], bbox: tuple[float, float, float, float], zoom: int
) -> tuple[np.ndarray, int, int]:
    """The DEM, reprojected onto the tile grid of `zoom` so tiles are slices.

    Cutting tiles out of one aligned array is both faster and less error prone
    than warping each tile separately, and it guarantees neighbouring tiles agree
    on their shared edge, which a per tile warp does not.
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
    for href in hrefs:
        with rasterio.open(href) as src:
            patch = np.full((rows, cols), np.nan, dtype="float32")
            reproject(
                source=rasterio.band(src, 1),
                destination=patch,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=transform,
                dst_crs="EPSG:3857",
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
        out = np.where(np.isnan(out), patch, out)
    # Sea level for anything the DEM does not cover, which here is the sea.
    return np.nan_to_num(out, nan=0.0), x0, y0


def encode(height: np.ndarray) -> np.ndarray:
    """Heights to the RGB triplet mapbox-gl decodes as `encoding: "mapbox"`."""
    value = np.clip(np.rint((height - BASE) / STEP), 0, 256**3 - 1).astype(np.uint32)
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

    print(f"Copernicus DEM GLO-30 over {BBOX}")
    print("=" * 78)
    hrefs = dem_hrefs(BBOX)
    print(f"  {len(hrefs)} source tile(s) from the Planetary Computer catalogue")

    grid, x0, y0 = mercator_grid(hrefs, BBOX, args.max_zoom)
    print(f"  reprojected to the zoom {args.max_zoom} tile grid: {grid.shape}")
    print(f"  highest point in the box: {grid.max():.0f} m")

    written = total_bytes = 0
    for zoom in range(min(ZOOMS), args.max_zoom + 1):
        # Each step down halves the grid, which is what a tile pyramid is.
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
        f'  encoding "mapbox", tileSize 256 and maxzoom {args.max_zoom}. Nothing about it\n'
        "  can be rate limited, suspended or repriced."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
