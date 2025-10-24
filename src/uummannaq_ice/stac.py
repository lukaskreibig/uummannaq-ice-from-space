"""STAC search helpers."""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List

from pystac import Item
from pystac_client import Client

from .config import RunConfig


def fix_l1c_hrefs(item: Item) -> Item:
    """Ensure Sentinel-2 L1C assets are referenced correctly."""
    for asset in item.assets.values():
        if "sentinel-s2-l2a" in asset.href:
            asset.href = asset.href.replace("sentinel-s2-l2a", "sentinel-s2-l1c")
    return item


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

    deduped: Dict[date, Item] = {}
    for item in items:
        if item.datetime is None:
            logging.warning("Skipping STAC item without datetime: %s", item.id)
            continue
        deduped[item.datetime.date()] = fix_l1c_hrefs(item)

    ordered = [deduped[key] for key in sorted(deduped)]
    if config.max_tiles:
        ordered = ordered[: config.max_tiles]

    logging.info("Identified %d Sentinel-2 tile(s) to process.", len(ordered))
    return ordered
