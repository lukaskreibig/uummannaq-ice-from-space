#!/usr/bin/env python3
"""
picture_corners_once.py
-------------------------------------------------------------
Print the exact lon/lat coordinates of the four image corners
(NW, NE, SE, SW) for the first Sentinel-2 tile that the given
ice-classification script will process.

Usage:
    python picture_corners_once.py <ice_processing_script.py>
"""

import ast
import pathlib
import sys
import os

# ---- NumPy ≥2.0 / Dask shim (same as in your main script) ------------------
import numpy as np
if not hasattr(np, "round_"):              # required by older Dask releases
    np.round_ = np.round
try:
    import dask.typing; dask.typing.Key
except Exception:
    import dask.typing; dask.typing.Key = object   # type: ignore

# ---------------------------------------------------------------------------
from pystac_client import Client
from odc.stac import load
import pyproj

os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")  # public S3 access

# ---------- helper to pull plain-Python literals from the target script -----
def literal(name: str, source: str):
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError(f"{name} not found")

# ---------- locate & read the processing script ----------------------------
try:
    script_path = pathlib.Path(sys.argv[1])
except IndexError:
    sys.exit("Usage: python picture_corners_once.py <ice_processing_script.py>")

src = script_path.read_text(encoding="utf-8")
SEARCH_AOI = literal("SEARCH_AOI",  src)
DATE_RANGE = literal("DATE_RANGE",  src)

# ---------- first matching Sentinel-2 item ----------------------------------
client = Client.open("https://earth-search.aws.element84.com/v1")
item   = next(client.search(
                collections=["sentinel-2-l1c"],
                intersects = SEARCH_AOI,
                datetime   = DATE_RANGE,
                limit      = 1).items())

# ---------- load a single band (lightweight) --------------------------------
ds       = load([item], geopolygon=SEARCH_AOI, bands=["red"], chunks={})
geobox   = ds.odc.geobox
transform = geobox.transform
width, height = geobox.width, geobox.height

# pixel → CRS corner points: (col,row)
corners_crs = [
    transform * (0,       0),        # NW
    transform * (width,   0),        # NE
    transform * (width, height),     # SE
    transform * (0,     height)      # SW
]

# ---------- re-project corners to WGS-84 ------------------------------------
if geobox.crs.to_epsg() != 4326:
    to4326 = pyproj.Transformer.from_crs(geobox.crs, "EPSG:4326", always_xy=True)
    corners_ll = [to4326.transform(x, y) for x, y in corners_crs]
else:
    corners_ll = corners_crs

# ---------- print once, one corner per line ---------------------------------
for lng, lat in corners_ll:
    print(f"{lng:.6f} {lat:.6f}")
