"""STAC search helpers."""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from pystac import Item
from pystac_client import Client

from .config import RunConfig

BBox = Tuple[float, float, float, float]

# A returned item must cover at least this share of the AOI bounding box before
# we are willing to treat it as an observation of this fjord.  Anything under it
# is either a neighbouring swath clipping a corner or, as actually happened, a
# scene from an entirely different part of the world.
MIN_AOI_COVERAGE = 0.10

# A Sentinel-2 granule is about 110 km square, which at this latitude is roughly
# 3.2 degrees of longitude by 1.0 of latitude. Anything far larger is not a
# footprint, it is a catalogue artefact: tiles that cross the antimeridian get a
# bounding box of [-180, ..., 180, ...], which covers the whole planet and
# therefore covers any AOI perfectly. That is how a scene from the North Pacific
# passed a coverage test and reached the published record.
MAX_FOOTPRINT_LON_SPAN = 20.0
MAX_FOOTPRINT_LAT_SPAN = 10.0


def utm_zone_for(longitude: float) -> int:
    """UTM zone a longitude belongs to, 1 to 60."""
    return int((longitude + 180.0) // 6) % 60 + 1


def mgrs_zone_of(item_id: str) -> Optional[int]:
    """Leading UTM zone of the MGRS tile in a Sentinel-2 item id."""
    parts = str(item_id).split("_")
    if len(parts) < 2 or len(parts[1]) < 3:
        return None
    digits = parts[1][:2]
    return int(digits) if digits.isdigit() else None


def is_plausible_footprint(item_bbox: Optional[Sequence[float]]) -> bool:
    """Reject bounding boxes too large to be a single granule."""
    if not item_bbox or len(item_bbox) < 4:
        return False
    lon_span = abs(item_bbox[2] - item_bbox[0])
    lat_span = abs(item_bbox[3] - item_bbox[1])
    return lon_span <= MAX_FOOTPRINT_LON_SPAN and lat_span <= MAX_FOOTPRINT_LAT_SPAN


def fix_l1c_hrefs(item: Item) -> Item:
    """Ensure Sentinel-2 L1C assets are referenced correctly."""
    for asset in item.assets.values():
        if "sentinel-s2-l2a" in asset.href:
            asset.href = asset.href.replace("sentinel-s2-l2a", "sentinel-s2-l1c")
    return item


def bbox_of(geojson: dict) -> Optional[BBox]:
    """Bounding box of a GeoJSON geometry, as (west, south, east, north)."""

    def coords(node):
        if isinstance(node, (int, float)):
            return
        if node and isinstance(node[0], (int, float)):
            yield node[0], node[1]
            return
        for child in node:
            yield from coords(child)

    points = list(coords(geojson.get("coordinates", [])))
    if not points:
        return None
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return (min(lons), min(lats), max(lons), max(lats))


def aoi_coverage(item_bbox: Optional[Sequence[float]], aoi_bbox: BBox) -> float:
    """Share of the AOI box that an item's box covers, 0.0 to 1.0.

    A plain box test, deliberately: it needs no geometry dependency and is more
    than enough to reject a scene from another continent.  It is intentionally
    generous, so a genuinely overlapping swath is never thrown away.
    """
    if not item_bbox or len(item_bbox) < 4:
        return 0.0
    iw, iss, ie, into = item_bbox[0], item_bbox[1], item_bbox[2], item_bbox[3]
    aw, asouth, ae, anorth = aoi_bbox
    overlap_lon = min(ie, ae) - max(iw, aw)
    overlap_lat = min(into, anorth) - max(iss, asouth)
    if overlap_lon <= 0 or overlap_lat <= 0:
        return 0.0
    aoi_area = (ae - aw) * (anorth - asouth)
    if aoi_area <= 0:
        return 0.0
    return (overlap_lon * overlap_lat) / aoi_area


def _sort_key(
    item: Item, aoi_bbox: Optional[BBox], preferred_zone: Optional[int] = None
) -> Tuple[float, int, str]:
    """Rank candidates for the same day, deterministically and on the merits.

    Without this the winner was whichever item the API happened to return last,
    so two overlapping MGRS tiles on the same day could swap between runs and the
    published number for that day would change with no code change.

    Coverage decides first, but over this AOI both neighbouring tiles cover it
    completely and score 1.0, so coverage alone would leave the choice to the
    alphabet: 21WXU sorts before 22WDD and would have won almost every day, where
    the published archive is 81 percent 22WDD. That is a change nobody asked for,
    on top of one that was already deliberate.

    So the UTM zone the AOI actually belongs to breaks the tie. Uummannaq sits at
    52.1 degrees west, which is zone 22, and a scene delivered in its own zone
    needs the least reprojection to reach the analysis grid. The id remains the
    final tiebreak so the order is total.
    """
    coverage = aoi_coverage(item.bbox, aoi_bbox) if aoi_bbox else 0.0
    zone = mgrs_zone_of(item.id or "")
    zone_rank = 0 if (preferred_zone is not None and zone == preferred_zone) else 1
    return (-coverage, zone_rank, item.id or "")


def fetch_tiles(config: RunConfig) -> List[Item]:
    """Return Sentinel-2 tiles respecting the configured AOI and date range."""
    logging.info(
        "Searching STAC %s for %s between %s and %s",
        config.stac_url,
        config.collection,
        config.start_date.isoformat(),
        config.end_date.isoformat(),
    )

    client = Client.open(config.stac_url)
    geojson = dict(config.search_aoi)
    search = client.search(
        collections=[config.collection],
        intersects=geojson,
        datetime=config.date_range,
    )

    items = list(search.items())
    if not items:
        logging.warning("No STAC items found for the current configuration.")
        return []

    aoi_bbox = bbox_of(geojson)
    preferred_zone = (
        utm_zone_for((aoi_bbox[0] + aoi_bbox[2]) / 2.0) if aoi_bbox else None
    )
    if preferred_zone is not None:
        logging.info(
            "AOI sits in UTM zone %d; tiles from that zone win ties.", preferred_zone
        )

    # Reject anything that does not actually see this fjord.  The catalogue has
    # returned scenes from other continents for this AOI: tile 30QUL off West
    # Africa and 60UXB in the North Pacific both reached the published record and
    # contributed an ice fraction of 0.0 for a day that then looked ice free.
    candidates: List[Tuple[date, Item]] = []
    for item in items:
        if item.datetime is None:
            logging.warning("Skipping STAC item without datetime: %s", item.id)
            continue
        captured_on = item.datetime.date()
        if not is_plausible_footprint(item.bbox):
            logging.warning(
                "Rejecting %s: bounding box %s is too large to be a granule, "
                "which is what a tile crossing the antimeridian looks like.",
                item.id,
                item.bbox,
            )
            continue
        if aoi_bbox is not None:
            coverage = aoi_coverage(item.bbox, aoi_bbox)
            if coverage < MIN_AOI_COVERAGE:
                logging.warning(
                    "Rejecting %s: covers %.1f%% of the AOI, below the %.0f%% floor. "
                    "bbox=%s",
                    item.id,
                    coverage * 100,
                    MIN_AOI_COVERAGE * 100,
                    item.bbox,
                )
                continue
        candidates.append((captured_on, item))

    if not candidates:
        logging.warning("Every STAC item was rejected as outside the AOI.")
        return []

    # One scene per day, chosen deterministically so a re-run reproduces the
    # published number instead of depending on catalogue response order.
    by_day: Dict[date, List[Item]] = {}
    for captured_on, item in candidates:
        by_day.setdefault(captured_on, []).append(item)

    deduped: Dict[date, Item] = {}
    for day, day_items in by_day.items():
        if len(day_items) > 1:
            logging.info(
                "%s: %d overlapping scenes, keeping %s by AOI coverage",
                day.isoformat(),
                len(day_items),
                min(
                    day_items, key=lambda it: _sort_key(it, aoi_bbox, preferred_zone)
                ).id,
            )
        deduped[day] = fix_l1c_hrefs(
            min(day_items, key=lambda it: _sort_key(it, aoi_bbox, preferred_zone))
        )

    ordered = [deduped[key] for key in sorted(deduped)]
    if config.max_tiles:
        ordered = ordered[: config.max_tiles]

    logging.info("Identified %d Sentinel-2 tile(s) to process.", len(ordered))
    return ordered
