# Every day, and what each instrument made of it

Ten seasons, 1280 days, and for each of them what the satellites saw. The fill of
a cell is the value the published series carries. The four rules underneath it
say which instruments actually looked that day. Hovering a day opens the scene
and what each instrument made of it; clicking pins it.

Everything below is read from `archive/reprocessed_2026`: `daily_series.csv`,
`summary.csv`, `landsat_season_series.csv`, `thermal_audit.csv` and
`sar_thermal_verdicts.csv`. `scripts/build_site_data.py` joins them by day
without changing a value and without mixing instruments.

<div id="contact-sheet"></div>

## Four layers, and they are not the same thing

The obvious mistake would be to draw them alike. They answer different questions.

**Sentinel-2 is the series.** Everything this project publishes comes from here:
NDSI and NDWI on a 40 m grid, with a brightness gate without which the index
separates nothing over this fjord.

**Landsat is a second opinion, not a second measurement.** Same land mask, same
CRS, same indices, same thresholds, same brightness gate. Only the instrument
changes, and with it the optics, the atmospheric correction and the cloud mask.
Over 82 days both saw, the two series correlate at 0.987 with an RMSE of 0.078.
That makes Landsat a confirmation. It does not make it part of the series, and
the sheet never counts it as one.

**The thermal band answers something no optical sensor can.** Seawater at this
salinity freezes at 271.35 kelvin. If the fjord radiates colder it cannot be
open, whatever the index says. Over the whole record that comparison was run on
226 days; 181 of them fall inside the window this sheet draws.

**Radar decides when the two disagree.** Backscatter separates a closed sheet
from a field of floes, which a thermometer cannot: both radiate equally cold.

## What the sheet shows

**How thin the series really is.** 543 of the 1280 days carry a Sentinel-2 scene
of their own, or 42.4 percent. The rest are gap filled, and those cells are drawn
pale with an empty Sentinel-2 rule. They sit in the published curve, and no
satellite passed over them.

**And how much less thin the record is.** Landsat contributes 545 days, many of
them on days without a Sentinel-2 scene. Across instruments this fjord was
observed on far more days than the published series alone shows.

**Where it turns contested.** The days the thermal band contradicts carry all
four rules and cluster in the later seasons. Those are the days that brought in
radar, and its verdict sits in the panel.

## On the imagery

**Every instrument shows its own picture, in its own row.** Sentinel-2 is the
record and the sheet's fill; Landsat is a second optical opinion; the thermal
band is that same Landsat scene's infrared; Sentinel-1 is radar. Four
instruments, four kinds of picture, and none of them stands in for another.

That rule costs something and is worth the cost. 543 days of the 1280 carry a
Sentinel-2 scene and 545 carry Landsat, but only 241 carry both, so on 304 days
the Landsat picture sits in a row whose Sentinel-2 neighbour still says it has no
scene. Filling that gap with the Landsat image would raise the sheet's apparent
coverage from 42 to 66 percent and quietly make the record look more continuous
than it is. The gaps are a finding.

Each instrument also keeps its own fixed stretch, measured on its own data.
Sentinel-2's white balance is `(0.890, 1.0, 0.885)` and Landsat's is
`(0.915, 1.0, 0.877)`, close in shape because the magenta cast belongs to the
atmosphere, different in value because OLI is not MSI. **The two pictures are
never to be compared on brightness.** They are compared on what they show.

### The classification beside the photograph

The Sentinel-2 row carries two pictures: the scene, and what the classifier made
of it. The second is the pipeline's own output, class ids on the 40 m grid the
decision was actually taken on, 368 by 453 cells under a 1302 by 1600 image, and
it is drawn without smoothing so that coarseness stays visible.

That difference is the honest picture of this method. A sharp photograph with a
coarse grid of judgements laid over it shows exactly how much resolution the
classification really has, which no accuracy figure conveys.

The rasters are the run's own artefacts, not a redrawing: the solid, light, water
and cloud counts in every one of the 617 files match `summary.csv` cell for cell,
and a test refuses any that do not.

### The thermal picture is not a temperature map of the record

Its colour scale is centred on 271.35 K, the freezing point of seawater, rather
than spread across the range the archive covers. The first attempt did spread it,
243 to 283 K, and every frame came out one flat colour. Inside a single winter
scene the whole fjord sits between 255.0 and 263.9 K: **nine kelvin of variation
within a scene against forty between seasons.** So the colour resolution goes
where the question is, blue below the line and amber above it, and a day ten
kelvin below freezing is uniformly deep blue because that is what it was. The
exact median is in the text beside the picture, where a number says it better.

### Radar, on 19 of the 27 adjudicated days

A day can have up to four Sentinel-1 passes, and the verdict was reached on one
of them. Where a single acquisition carries the verdict's `value_db`, that
acquisition is the picture. Where the value came from more than one pass, the row
shows its numbers and no picture, because no single image is the measurement.

Backscatter is roughness and wetness, not brightness. A smooth closed sheet reads
dark and so does calm open water, which is why the analysis separates them on
spread rather than on level.

### Sentinel-2

The quicklooks are computed from bands B04, B03 and B02 of the same L1C scene the
classification read. Not from the ready-made composite and not from the Level 2A
product: the first is seventeen times slower to read over the network, the second
is a different product, and a picture of something adjacent to the measurement
would be the wrong picture here.

**Contrast and white balance are fixed for the whole record.** A per-scene
stretch makes every frame look correctly exposed and in doing so erases what the
archive says loudest: the surface really does get darker. 2023 sits 34 percent
below the ten-season median on days that are certainly frozen. Under an automatic
stretch none of that would survive.

The white balance is measured rather than chosen. Over the brightest quarter of
the frame, on clear days that are certainly frozen, green sits about eleven
percent below red and blue, in every year checked and on both sides of the
baseline 04.00 boundary. It belongs to the atmosphere and the instrument rather
than to a season, and one constant gain removes it everywhere.

That the fixed stretch carries can be measured back off the finished quicklooks.
Averaged over April days that are certainly frozen, 2023 is the darkest season by
a wide margin, with 2025 and 2021 behind it. That is the order
[limitations.md](limitations.md) derives from the reflectances themselves.

## When the picture and the number disagree

**17 April 2021 shows floes and open leads and reports an ice fraction of 1.00.**
That is a class boundary rather than a fault. The published series is
`solid + light`, those leads are classified as light ice, and open water on that
day is 0.0000.

So the panel names all three classes separately. The summed fraction alone,
beside a photograph full of floes, reads as a broken classifier, and that would
be the wrong answer.

## What the sheet does not show

There are no cells before 2017, although the Landsat archive over this fjord
reaches back to 1973. The reason is calibration rather than effort. MSS carries
no shortwave infrared, so NDSI cannot be formed on it at all, and between TM and
its successors there is **not one same-overpass pair** in the whole archive to
carry a threshold across the sensor boundary. Those boundaries fall in 1999 and
2013, exactly where the split of a long record would sit, so an uncalibrated join
would be indistinguishable from the trend it is meant to measure.

The full argument is in
[Landsat cross-check](landsat-crosscheck.md#how-far-back-the-archive-reaches-and-why-that-is-not-how-far-the-record-can).
