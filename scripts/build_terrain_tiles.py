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
from rasterio.errors import WindowError
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window, from_bounds

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT.parent / "climate-dashboard/frontend/public/terrain"

STAC = "https://stac.pgc.umn.edu/api/v1/search"
COLLECTION = "arcticdem-mosaics-v4.1-2m"
BUCKET = (
    "https://pgc-opendata-dems.s3.us-west-2.amazonaws.com/arcticdem/mosaics/v4.1/2m"
)

# Every camera waypoint in scenesConfig.tsx sits within 0.3 degrees of the fjord,
# so this covers all of them with room for a 70 degree pitch to see past them.
# The same box as scripts/build_basemap_image.py, so ground and relief end
# together rather than one of them running out first.
BBOX = (-52.9, 70.4, -51.5, 71.0)
# From zoom 6, not 8, and the two levels matter more than their size suggests.
#
# A raster-dem source has no terrain at all below its minzoom, so the camera
# crossing that zoom is a visible edge: the mountain appears on the way down and
# vanishes again on the way up. With minzoom 8 that edge sat right where the
# reader arrives at the fjord, and it read as the relief loading late. It was not
# loading late, it did not exist yet.
#
# Zoom 6 is where the ground image also starts fading in, so relief and imagery
# now arrive together, and the two extra levels are four tiles.
# Up to 10 and no further. Zoom 11 was built for a long time and never once
# fetched: logging every /terrain request through the whole flight, at retina and
# at phone pixel ratios, the deepest level mapbox-gl asks for is 10. Ninety-nine
# tiles and 6.8 MB shipped for nothing.
ZOOMS = range(6, 11)
# More pixels in the tiles over the island, rather than more levels.
#
# WHAT mapbox ACTUALLY ASKS FOR. Measured, because the obvious guess is wrong:
# with the camera at zoom 12.65 where the story lands, mapbox-gl requests DEM
# tiles at zoom 10, and it does that at every pitch from 0 to 85. It reads its
# terrain about two and a half levels below the camera. So a zoom 12 or 13 level
# is never fetched at all on this flight; building one is dead weight.
#
# WHAT DOES REACH THE SCREEN. mapbox builds its elevation grid from the tile
# image it actually receives, not from the tile size declared on the source. Give
# the zoom 10 tile 1024 pixels instead of 512 and the posting under the camera
# halves, from 25 m to 12.6 m, and the ridges come back. Measured by serving both
# and differencing the render: 2.5 percent of pixels change, and the change is
# the silhouette.
#
# WHY EVERY TILE AT A LEVEL, AND NOT JUST THE ONES OVER THE ISLAND. This used to
# oversample a small window and leave the rest at 512, which put tiles of two
# different pixel sizes on the same zoom level. mapbox-gl stitches each DEM tile
# to its neighbours so slopes do not break at the seam, and that stitch is
# strict:
#
#     backfillBorder(borderTile, dx, dy) {
#         if (this.dim !== borderTile.dim) throw new Error('dem dimension mismatch');
#
# dim is read off the image, so every fine tile meeting a coarse neighbour threw,
# and the border was left unfilled. It reached production and showed up as a
# console error in the map scene. An earlier note in this file called serving an
# oversampled tile "a degradation, not a break"; the throw is the part that was
# missed, and it is a break.
#
# So the rule is now simple enough to test: every tile at a given zoom has the
# same pixel count. The fine window is the whole box, which also means the fjord
# in front of the island gets the finer posting rather than only the island.
# frontend/lib/__tests__/terrainTiles.test.ts enforces it.
#
# THE REMAINING RISK, unchanged. Serving a tile larger than the declared tileSize
# is not something the style spec promises. It works across mapbox-gl v3, and if
# a future version normalises the image to the declared size the story gets the
# coarser relief back. THAT is a degradation, not a break.
FINE_FROM = 10
FINE_BBOX = BBOX
OVERSAMPLE = 2

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


def snap_to_tiles(
    bbox: tuple[float, float, float, float], zoom: int
) -> tuple[float, float, float, float]:
    """Grow a box outward to whole tiles at `zoom`.

    The oversampled window has to line up with the tile grid, or a tile that is
    only half inside it cannot be filled and silently keeps the coarse version.
    That is exactly what happened first time round: of the tiles over the island
    only three were written fine, and the one holding the summit was not among
    them. Snapping at the coarsest oversampled level lines the finer ones up too,
    since each of their tiles nests inside one of these.
    """
    n = 2**zoom
    x0, y0 = tile_xy(bbox[3], bbox[0], zoom)
    x1, y1 = tile_xy(bbox[1], bbox[2], zoom)

    def lat_of(y: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))

    return (x0 / n * 360 - 180, lat_of(y1 + 1), (x1 + 1) / n * 360 - 180, lat_of(y0))


def dem_hrefs_stac(bbox: tuple[float, float, float, float]) -> list[str]:
    """Every ArcticDEM mosaic tile touching the box, via the PGC search API."""
    body = json.dumps(
        {"collections": [COLLECTION], "bbox": list(bbox), "limit": 50}
    ).encode()
    request = urllib.request.Request(
        STAC, data=body, headers={"Content-Type": "application/json"}
    )
    items = json.load(urllib.request.urlopen(request, timeout=180))["features"]
    return [item["assets"]["dem"]["href"] for item in items]


def dem_hrefs_bucket(bbox: tuple[float, float, float, float]) -> list[str]:
    """The same tiles, worked out from the grid instead of asked for.

    PGC lays its mosaics out on a 100 km grid in EPSG:3413 whose tile at column
    c and row r covers x from -4e6 + (c-1)*1e5 and y from -4e6 + (r-1)*1e5, and
    splits each of those into four 50 km quarters, i for south then north and j
    for west then east. So the tiles a box needs can be named rather than
    searched for, and the static catalogue on the open data bucket confirms each
    one and hands over the COG.
    """
    west, south, east, north = transform_bounds("EPSG:4326", "EPSG:3413", *bbox)
    cols = range(int((west + 4e6) // 1e5) + 1, int((east + 4e6) // 1e5) + 2)
    rows = range(int((south + 4e6) // 1e5) + 1, int((north + 4e6) // 1e5) + 2)
    hrefs: list[str] = []
    for row in rows:
        for col in cols:
            for i in (1, 2):
                for j in (1, 2):
                    name = f"{row:02d}_{col:02d}_{i}_{j}_2m_v4.1"
                    url = f"{BUCKET}/{row:02d}_{col:02d}/{name}.json"
                    try:
                        item = json.load(urllib.request.urlopen(url, timeout=60))
                    except Exception:
                        continue  # that quarter of the grid has no land in it
                    box = item.get("bbox")
                    if not box:
                        continue
                    if (
                        box[0] < bbox[2]
                        and bbox[0] < box[2]
                        and box[1] < bbox[3]
                        and bbox[1] < box[3]
                    ):
                        hrefs.append(item["assets"]["dem"]["href"])
    return hrefs


def dem_hrefs(bbox: tuple[float, float, float, float]) -> list[str]:
    """Every ArcticDEM mosaic tile touching the box. Open data, no signing.

    The search API in front of these files went down while this window was being
    rebuilt, answering every query with its own ConnectionRefusedError. The files
    were fine the whole time, so the fallback below reaches them directly and a
    rebuild no longer depends on that service being up.
    """
    try:
        return dem_hrefs_stac(bbox)
    except Exception as err:  # noqa: BLE001 - any failure means fall back
        print(f"  search API unavailable ({err}), naming the tiles instead")
        return dem_hrefs_bucket(bbox)


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

    # No snapping to a coarser tile grid, because every level is now read from
    # the source at its own resolution rather than halved out of the level below
    # it. When it WAS halved, a grid starting on an odd tile put its left edge in
    # the middle of the coarser tile and shifted every level below the deepest by
    # a fraction of a tile: the summit read 1203 m at zoom 11 and 27 m, sea level,
    # at zoom 10, because its relief had moved off the island.

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
            try:
                window = from_bounds(*bounds, src.transform).intersection(
                    Window(0, 0, src.width, src.height)
                )
            except WindowError:
                # No overlap at all. rasterio raises here rather than handing
                # back an empty window, and it started mattering the moment the
                # fine levels asked for a box smaller than the one the source
                # list was gathered for.
                continue
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

    fine_box = snap_to_tiles(FINE_BBOX, FINE_FROM)
    print(
        f"  fine window snapped to whole zoom {FINE_FROM} tiles: "
        f"{tuple(round(v, 4) for v in fine_box)}"
    )
    grid, x0, y0 = mercator_grid(hrefs, BBOX, max(ZOOMS))
    print(f"  on the zoom {max(ZOOMS)} tile grid at {TILE} px: {grid.shape}")
    print(f"  highest point in the box: {grid.max():.0f} m")

    written = total_bytes = 0
    levels: dict[str, dict[str, int]] = {}
    for zoom in range(min(ZOOMS), args.max_zoom + 1):
        # Each level is read from ArcticDEM again at its own resolution, not
        # decimated out of the level above it. Two earlier attempts got this
        # wrong in opposite directions and both were visible.
        #
        # Averaging my own grid down compounded: by zoom 8 every output pixel was
        # a mean of 8 by 8, and since the sea around this island is 0 m, the
        # 1206 m summit averaged away to 218. Taking the maximum instead saved
        # the peak and terraced the slopes, because a max over a moving window is
        # a staircase, and a photograph draped over a staircase smears.
        #
        # Reading the source per level avoids both. rasterio pulls the matching
        # overview, which the Polar Geospatial Center built properly, so a slope
        # stays a slope and a summit stays a summit.
        level, zx0, zy0 = (
            (grid, x0, y0) if zoom == max(ZOOMS) else mercator_grid(hrefs, BBOX, zoom)
        )
        # The same tiles again, but read at OVERSAMPLE times the resolution, over
        # the island only. Reading the finer grid once per level and slicing it
        # keeps neighbouring oversampled tiles agreeing on their shared edge.
        fine: np.ndarray | None = None
        fx0 = fy0 = 0
        if zoom >= FINE_FROM and OVERSAMPLE > 1:
            step = int(math.log2(OVERSAMPLE))
            fine, fx0, fy0 = mercator_grid(hrefs, fine_box, zoom + step)
        for ty in range(level.shape[0] // TILE):
            for tx in range(level.shape[1] // TILE):
                x, y = zx0 + tx, zy0 + ty
                block = level[ty * TILE : (ty + 1) * TILE, tx * TILE : (tx + 1) * TILE]
                if fine is not None:
                    # This tile's footprint in the finer grid's own tile numbers.
                    a, b = x * OVERSAMPLE - fx0, y * OVERSAMPLE - fy0
                    span = TILE * OVERSAMPLE
                    if (
                        a >= 0
                        and b >= 0
                        and (b + OVERSAMPLE) * TILE <= fine.shape[0]
                        and (a + OVERSAMPLE) * TILE <= fine.shape[1]
                    ):
                        block = fine[
                            b * TILE : b * TILE + span, a * TILE : a * TILE + span
                        ]
                path = args.out / str(zoom) / str(x) / f"{y}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(encode(block), "RGB").save(path, optimize=True)
                written += 1
                total_bytes += path.stat().st_size
        levels[str(zoom)] = {
            "x0": zx0,
            "x1": zx0 + level.shape[1] // TILE - 1,
            "y0": zy0,
            "y1": zy0 + level.shape[0] // TILE - 1,
        }
        print(f"  z{zoom}: {level.shape[1] // TILE} by {level.shape[0] // TILE} tiles")

    # A manifest, so the story does not have to guess. Without it mapbox-gl and
    # the prefetch both ask for tiles outside the box: measured at 202 requests
    # out of 237, all 404, for one camera path.
    manifest = {
        "bbox": list(BBOX),
        "minzoom": min(ZOOMS),
        "maxzoom": args.max_zoom,
        "fineBbox": list(fine_box),
        "fineFrom": FINE_FROM,
        "oversample": OVERSAMPLE,
        "tileSize": TILE,
        "encoding": "mapbox",
        "levels": levels,
        "source": "ArcticDEM v4.1, Polar Geospatial Center, University of Minnesota",
    }
    (args.out / "meta.json").write_text(json.dumps(manifest, indent=2) + "\n")

    print()
    print(f"  {written} tiles, {total_bytes / 1024 / 1024:.1f} MB, under {args.out}")
    print(f"  manifest at {args.out / 'meta.json'}")
    print()
    print(
        "  Point a mapbox-gl raster-dem source at /terrain/{z}/{x}/{y}.png with\n"
        f'  encoding "mapbox", tileSize {TILE} and maxzoom {args.max_zoom}.'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
