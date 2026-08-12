#!/usr/bin/env python3
"""The ground under the map, from the same instrument the story is about.

    python3 scripts/build_basemap_image.py

The map scenes need imagery, and every option that is not ours has a problem.
Mapbox renders this fjord as an unbroken dark field with no island in it. MapTiler
answered until its free plan ran out. Esri and EOX both work and both are somebody
else's picture of a place this project has ten years of its own imagery of.

So the ground is a Sentinel-2 scene from the same archive the analysis runs on,
already in Web Mercator so mapbox-gl can lay it on a quad without stretching it,
and it ships with the story.

WHY A SUMMER SCENE. The story lays its own winter scene over this ground later, as
the beat where the reader watches the classifier work. That overlay is the subject
and it has to be the winter one. A winter ground under a winter overlay is one
white field on another and the overlay stops reading as a measurement. Open water
underneath is what makes the ice on top legible.

WHAT THIS IS NOT. Not a mosaic and not cloud free by construction: it is one
scene, chosen for being clear, and whatever cloud it has is in the picture. That
is the honest version, and the alternative would be compositing several dates into
a ground that never existed on any day.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window, from_bounds

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT.parent / "climate-dashboard/frontend/public/images"

STAC = "https://earth-search.aws.element84.com/v1/search"
# L2A rather than L1C. The analysis runs on L1C because it needs top of
# atmosphere reflectance it can reason about, but a picture wants the
# atmosphere taken out, and L2A sits on a free bucket where L1C is requester
# pays against a role this project does not have.
COLLECTION = "sentinel-2-l2a"

# Wide enough to be the ground for the whole close-up flight, tight enough to stay
# one file. Roughly 52 by 67 km around the fjord.
BBOX = (-52.9, 70.4, -51.5, 71.0)
# Sentinel-2 is 10 m; 4096 across this box is about 13 m per pixel, which is finer
# than the camera ever resolves and small enough to ship.
WIDTH = 4096
# July and August only: the fjord has to be open, and the sun has to be up.
MONTHS = (7, 8)
MAX_CLOUD = 15.0
# A partial tile is worse than a cloudy one: it is a hole in the ground.
MAX_NODATA = 1.0
TILE_ID = "22WDD"

# Percentile stretch on the 8 bit TCI, then a gentle gamma. Arctic water is
# genuinely dark and a linear stretch leaves it black, which is what the EOX
# mosaic looks like.
STRETCH = (1.0, 97.0)
GAMMA = 0.85


def search() -> dict:
    """The clearest July or August scene over this tile, newest first."""
    body = json.dumps(
        {
            "collections": [COLLECTION],
            "bbox": list(BBOX),
            "query": {"eo:cloud_cover": {"lt": MAX_CLOUD}},
            "limit": 100,
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
        }
    ).encode()
    request = urllib.request.Request(
        STAC, data=body, headers={"Content-Type": "application/json"}
    )
    items = json.load(urllib.request.urlopen(request, timeout=180))["features"]
    # Cloud cover alone is a trap here. A Sentinel-2 tile at the edge of a swath
    # is mostly empty, and an empty tile reports zero percent cloud: the clearest
    # looking scene in this search was 45 percent nodata and read back black.
    # Coverage first, then cloud.
    summer = [
        item
        for item in items
        if int(item["properties"]["datetime"][5:7]) in MONTHS
        and TILE_ID in item["id"]
        and item["properties"].get("s2:nodata_pixel_percentage", 100.0) < MAX_NODATA
    ]
    if not summer:
        raise SystemExit("no clear, fully covered summer scene found over this tile")
    summer.sort(key=lambda i: i["properties"].get("eo:cloud_cover", 100.0))
    return summer[0]


def mercator_band(
    href: str, bbox, width: int, height: int, band: int = 1
) -> np.ndarray:
    """One band, read at about the target resolution and warped to Mercator."""
    span_x = 20037508.342789244
    west, south, east, north = bbox

    def merc(lng: float, lat: float) -> tuple[float, float]:
        x = lng * span_x / 180.0
        y = math.log(math.tan(math.radians(90 + lat) / 2)) * span_x / math.pi
        return x, y

    left, bottom = merc(west, south)
    right, top = merc(east, north)
    transform = rasterio.Affine(
        (right - left) / width, 0, left, 0, -(top - bottom) / height, top
    )

    with rasterio.open(href) as src:
        bounds = transform_bounds("EPSG:4326", src.crs, *bbox)
        window = from_bounds(*bounds, src.transform).intersection(
            Window(0, 0, src.width, src.height)
        )
        scale = max(1.0, min(window.width / width, window.height / height))
        shape = (max(1, int(window.height / scale)), max(1, int(window.width / scale)))
        patch = src.read(
            band, window=window, out_shape=shape, resampling=Resampling.average
        ).astype("float32")
        src_transform = src.window_transform(window) * rasterio.Affine.scale(
            window.width / shape[1], window.height / shape[0]
        )
        out = np.zeros((height, width), dtype="float32")
        reproject(
            source=patch,
            destination=out,
            src_transform=src_transform,
            src_crs=src.crs,
            dst_transform=transform,
            dst_crs="EPSG:3857",
            resampling=Resampling.bilinear,
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--width", type=int, default=WIDTH)
    parser.add_argument("--quality", type=int, default=86)
    args = parser.parse_args(argv)

    item = search()
    props = item["properties"]
    print("Sentinel-2, the same instrument and the same fjord as the analysis")
    print("=" * 78)
    print(f"  scene   {item['id']}")
    print(f"  date    {props['datetime'][:10]}")
    print(f"  cloud   {props.get('eo:cloud_cover', float('nan')):.1f} percent")
    print(f"  sun     {props.get('view:sun_elevation', float('nan')):.1f} degrees")
    print(
        f"  nodata  {props.get('s2:nodata_pixel_percentage', float('nan')):.1f} percent"
    )

    west, south, east, north = BBOX
    aspect = (
        math.log(math.tan(math.radians(90 + north) / 2))
        - math.log(math.tan(math.radians(90 + south) / 2))
    ) / math.radians(east - west)
    height = int(round(args.width * aspect))
    print(f"  raster  {args.width} by {height}, Web Mercator")

    # Free bucket, unsigned, the same way preflight reads the catalogue.
    os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
    href = item["assets"]["visual"]["href"]
    print(f"  asset   {href}")

    channels = [
        mercator_band(href, BBOX, args.width, height, band) for band in (1, 2, 3)
    ]
    print("  read    TCI, the true colour composite ESA ships with the scene")

    stack = np.stack(channels, axis=-1)
    lit = stack[stack > 0]
    lo, hi = np.percentile(lit, STRETCH)
    print(f"  stretch {lo:.1f} to {hi:.1f} of 255, gamma {GAMMA}")
    scaled = np.clip((stack - lo) / (hi - lo), 0, 1) ** GAMMA
    rgb = (scaled * 255).astype(np.uint8)

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "basemap-summer.jpg"
    Image.fromarray(rgb, "RGB").save(path, quality=args.quality, optimize=True)
    size_mb = path.stat().st_size / 1024 / 1024
    print()
    print(f"  {path}  {size_mb:.1f} MB")

    corners = {
        "scene": item["id"],
        "date": props["datetime"][:10],
        "cloud_cover": props.get("eo:cloud_cover"),
        "bbox": list(BBOX),
        "coordinates": [
            [west, north],
            [east, north],
            [east, south],
            [west, south],
        ],
    }
    meta = args.out / "basemap-summer.json"
    meta.write_text(json.dumps(corners, indent=2) + "\n")
    print(f"  {meta}")
    print()
    print(
        "  The image is already in Web Mercator, so the four corners above map it\n"
        "  onto a mapbox-gl image source without any stretch of their own."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
