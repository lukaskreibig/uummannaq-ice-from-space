"""Per-scene artefacts for a viewer, as opposed to per-scene artefacts for a human.

The pipeline already writes two pictures per scene. The panel is six matplotlib
axes with titles, which is the right thing to open when you want to judge a
classification by eye and the wrong thing to build an interface on. The overlay
is the class colours already blended into the true-colour image, which looks
good and cannot be taken apart again: you cannot fade between the photograph and
the decision, cannot hide one class, cannot read a class back out of a blended
pixel.

So this module writes the two things a viewer actually needs, and one of them
cannot be recovered later at any price short of running the whole archive again:

**The class raster.** One byte per analysis cell, on the 40 m grid the decision
was actually made on, as a paletted PNG. Exact class ids, not colours, so a
viewer can recolour it, toggle classes, count cells and get the same numbers the
CSV reports. It is also tiny, a few kilobytes, because a six-value image
compresses to almost nothing.

**The scene in true colour**, clean, no chrome, at the resolution the sensor
gives rather than the resolution the decision was made at. That difference is
the honest picture of this method: a sharp photograph with a coarse grid of
judgements laid over it, and a viewer that shows both at once shows the reader
exactly how much resolution the classification really has.

Plus a small JSON alongside, because a picture with no coordinates, no date and
no scene id is decoration rather than evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import numpy as np
from PIL import Image

# The order is the priority order used when a cell qualifies for more than one
# mask, and it matches how summarise_masks resolves them. Value 0 is reserved
# for "no class won", which the CSV counts as unknown.
CLASS_VALUES: tuple[tuple[str, int], ...] = (
    ("nodata", 1),
    ("land", 2),
    ("cloud", 3),
    ("ice_solid", 4),
    ("ice_light", 5),
    ("water", 6),
)

# Deliberately the same hues the quicklook overlay uses, so the two agree, and
# deliberately in the file rather than in the viewer, so a reader who opens the
# PNG on its own sees the same thing the story shows.
CLASS_COLOURS: dict[int, tuple[int, int, int]] = {
    0: (40, 40, 40),  # unclassified
    1: (0, 0, 0),  # no data
    2: (150, 105, 80),  # land
    3: (215, 215, 225),  # cloud
    4: (235, 235, 60),  # solid ice
    5: (120, 200, 255),  # light ice
    6: (30, 40, 200),  # water
}

CLASS_NAMES: dict[int, str] = {
    0: "unclassified",
    1: "nodata",
    2: "land",
    3: "cloud",
    4: "ice_solid",
    5: "ice_light",
    6: "water",
}


@dataclass(frozen=True, slots=True)
class SceneExport:
    """Where the three files for one scene ended up."""

    classes_path: Path
    scene_path: Path
    meta_path: Path


def class_raster(masks: Mapping[str, np.ndarray]) -> np.ndarray:
    """Collapse the per-class boolean masks into one byte per cell.

    Later entries in CLASS_VALUES overwrite earlier ones, so the order is the
    decision order and not an accident of dictionary iteration.
    """

    first = next(iter(masks.values()))
    raster = np.zeros(first.shape, dtype=np.uint8)
    for name, value in CLASS_VALUES:
        mask = masks.get(name)
        if mask is None:
            continue
        raster[np.asarray(mask, dtype=bool)] = value
    return raster


def _palette() -> list[int]:
    palette: list[int] = []
    for index in range(256):
        red, green, blue = CLASS_COLOURS.get(index, (0, 0, 0))
        palette.extend((red, green, blue))
    return palette


def write_scene_export(
    scene_id: str,
    timestamp: str,
    masks: Mapping[str, np.ndarray],
    rgb: Image.Image,
    classes_dir: Path,
    scenes_dir: Path,
    *,
    bounds: Optional[Sequence[float]] = None,
    crs: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
    indices: Optional[Mapping[str, np.ndarray]] = None,
    scene_quality: int = 82,
) -> SceneExport:
    """Write the class raster, the true-colour scene, the indices and metadata.

    `indices` is NDSI and NDWI per analysis cell. They are the two numbers the
    whole classification turns on, they cannot be recovered from anything else
    the run writes, and at float16 over a 368 by 453 grid they cost a few
    hundred kilobytes. float16 rather than float32 because an index lives in
    [-1, 1] and its third decimal is already below the noise of the reflectance
    it came from.
    """

    classes_dir.mkdir(parents=True, exist_ok=True)
    scenes_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{scene_id}_{timestamp}"

    raster = class_raster(masks)
    image = Image.fromarray(raster, mode="P")
    image.putpalette(_palette())
    classes_path = classes_dir / f"{stem}_classes.png"
    # optimize costs a little time and roughly halves a file that is already
    # small; over 1100 scenes it is still worth having.
    image.save(classes_path, optimize=True)

    scene_path = scenes_dir / f"{stem}_scene.jpg"
    rgb.convert("RGB").save(scene_path, quality=scene_quality, optimize=True)

    values, counts = np.unique(raster, return_counts=True)
    meta: dict[str, Any] = {
        "scene_id": scene_id,
        "timestamp": timestamp,
        "class_grid": {"width": int(raster.shape[1]), "height": int(raster.shape[0])},
        "scene_image": {"width": rgb.width, "height": rgb.height},
        "classes": {
            CLASS_NAMES.get(int(v), str(int(v))): int(c)
            for v, c in zip(values.tolist(), counts.tolist(), strict=True)
        },
        "palette": {
            CLASS_NAMES[k]: v for k, v in CLASS_COLOURS.items() if k in CLASS_NAMES
        },
    }
    if bounds is not None:
        meta["bounds"] = [float(b) for b in bounds]
    if crs is not None:
        meta["crs"] = str(crs)
    if extra:
        meta.update(dict(extra))

    if indices:
        arrays = {
            name: np.asarray(values, dtype=np.float16)
            for name, values in indices.items()
        }
        with (classes_dir / f"{stem}_indices.npz").open("wb") as handle:
            # The numpy stub declares the second positional parameter as a bool,
            # so it reads a **kwargs expansion as that flag. The call is correct;
            # only the stub cannot express "any number of named arrays".
            np.savez_compressed(handle, **arrays)  # type: ignore[arg-type]
        meta["indices"] = sorted(indices)

    meta_path = classes_dir / f"{stem}_classes.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")

    return SceneExport(
        classes_path=classes_path, scene_path=scene_path, meta_path=meta_path
    )
