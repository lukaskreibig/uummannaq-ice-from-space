# Investigation log

How the current version of this pipeline was arrived at, written down because the
route is more instructive than the destination.

The pipeline had been producing a plausible time series for years. It contained
four systematic errors, none of which raised an exception, logged a warning or
produced an obviously wrong picture. Every one of them was found by checking a
number against something outside the code: a physical expectation, a published
convention, an independent measurement, or an image looked at with human eyes.

That is the thread running through all of it. **A quiet error cannot be found by
running the code again.**

---

## The seasonal loss that was a mean of ratios

*Found by: recomputing a published figure from the raw data.*

The story quoted 11.9 percent less ice between the early and late period. The
estimator averaged the per-day ratio `late/early` across the season. In late June
the early-period mean falls to about 0.008, so single days produced terms as
extreme as -2.62 and dragged the headline down.

The correct estimator is the ratio of the two period means. Recomputed: **32.4
percent**, roughly three times the published figure.

**Why it survived:** 11.9 percent is a plausible number. Nothing about it invites
a second look.

## The offset that was holding up the classification

*Found by: reading the ESA product specification against the code.*

ESA introduced `RADIO_ADD_OFFSET = -1000` with processing baseline 04.00 on 25
January 2022, so reflectance became `DN/10000 - 0.1`. The code instead **added**
0.1 to everything older and subtracted nothing from anything newer. Both eras
therefore sat 0.1 above true reflectance.

Confirmed three ways: against the SentiWiki specification, against the product
metadata of this AOI's own granules, and against a control pair, the same 2019
acquisition published twice under baselines 02.08 and 05.00.

**Why it survived:** the bias was identical on both sides of the 2022 boundary,
so there was no step in the time series to notice. The author's own comment in an
archived script reads `# pre-2022 tiles: still missing +0.1`, which is a precise
statement of the misunderstanding.

**And then the interesting part.** Fixing the sign alone made things much worse.
Measured on the open summer fjord of 2023-08-18, the ice fraction went from 0.004
to **0.584**: the classifier called 58 percent of open water ice.

The reason is physics, and it is checkable on paper:

| Surface | green | SWIR | true NDSI | NDSI with +0.1 |
|---|---|---|---|---|
| April fast ice | 0.697 | 0.112 | 0.723 | 0.580 |
| Open water | 0.010 | 0.001 | **0.818** | 0.043 |

**Open water has a higher NDSI than fast ice.** It is nearly black at 1.6 µm, so
the normalised difference is large. Adding a constant to both terms of a
normalised difference destroys its scale invariance and compresses dark pixels far
more than bright ones. The bug had turned NDSI into a brightness proxy, and the
brightness proxy was doing the classification.

The fix is the classic Dozier construction the MODIS lineage uses: NDSI paired
with brightness floors in the visible and near infrared. The fields
`vis_bright_min` and `nir_bright_min` had been sitting unused in the
configuration the whole time.

**What generalises:** when a correction makes results worse, the bug was probably
load-bearing. Find out what work it was doing before removing it.

## The denominator that measured the weather

*Found by: asking what else differs between the two periods being compared.*

The ice fraction divided by the whole grid, cloud included. Cloud cells can never
be ice, so a cloudy day mechanically reports less ice regardless of what lies
underneath.

Cloud is not evenly distributed over this record: 21.3 percent in the 2017 to
2020 seasons against 29.7 percent in 2021 to 2025. Recomputed on the published
archive:

| Denominator | Early-to-late loss |
|---|---|
| whole grid | 35.7 % |
| clear cells only | 22.7 % |

**About a third of the headline was weather.**

Two independent confirmations followed. A dose-response check: tightening the
visibility floor from none to 30, 50 and 70 percent gives 20.4, 19.1, 18.9 and
15.5 percent, monotonically decreasing as the data get cleaner. And a direct one:
in February and March, days reporting under 0.15 ice have a **median cloud cover
of 0.72** while the rest have **0.00**. In the depth of winter, on a fjord that
is certainly frozen, the pipeline reports "no ice" precisely when it is cloudy.
Across all scenes, ice fraction and cloud correlate at **r = -0.42**.

**Why it survived:** every individual number was inside its plausible range.

## The land mask that covered a fraction, not a place

*Found by: overlaying it on an image and looking.*

A 512 by 512 painted PNG resized with nearest-neighbour onto whatever grid each
scene produced. It therefore covered the same **share** of the frame rather than
the same ground: exactly 9.00 percent of every scene, whichever tile, whichever
grid size, including for two scenes that turned out to be from West Africa and
the North Pacific.

Rendered over a summer scene it was obvious in one look: the island was roughly
covered, and a diagonal band of mask sat over open water.

Replaced by a mask derived from the imagery. Land is what stays above 0.06 in the
75th percentile of near-infrared reflectance across eight clear August scenes
spanning 2019 to 2024, since open water is nearly black there (median 0.021) and
rock is not (0.141), and drifting ice cannot hold a pixel across four years. The
result is a GeoTIFF with its own CRS, reprojected per scene.

Actual land share: **5.15 percent**. The painted mask had covered nearly twice
the island.

Two refinements came out of looking again. The 75th percentile rather than the
median, because at 70 degrees north the mountain shadows its own eastern face and
a shadowed slope is as dark in the near infrared as water. And filling enclosed
holes, because the island's lakes and ponds are dark too, and ice on them is lake
ice, not sea ice.

## The scenes from other continents

*Found by: counting MGRS tiles in the published archive.*

1264 scenes from 22WDD, 286 from 21WXU, one from **30QUL** (off West Africa) and
one from **60UXB** (North Pacific). Both reported 0.0 for everything, and the
West Africa scene was the only one for 13 March 2020, so one day of the published
record was an image of the wrong continent.

The first fix, rejecting items that cover too little of the AOI, did not work:
60UXB crosses the antimeridian, so its catalogue bounding box is
`[-180, 51.06, 180, 90]`, which covers every AOI on Earth perfectly and scored
1.0. The working test is a plausibility check on footprint size, since a granule
is about 3.2 by 1.0 degrees here and nothing legitimate spans 360.

The same investigation surfaced a reproducibility defect. Scene deduplication was
`deduped[date] = item` over raw search results, so on a day with two overlapping
tiles the winner was whichever the API returned last, and the published number
for that day could change between runs with no code change.

## The tile choice that was made by the alphabet

*Found by: a reviewer running the fixed selection and comparing the result.*

Making deduplication deterministic was not enough. Both neighbouring tiles cover
this AOI completely and score 1.0, so the id tiebreak decided, and 21WXU sorts
before 22WDD. The corrected run would have been 1776 of 1804 scenes on 21WXU
where the published archive is 81 percent 22WDD, a change nobody chose, stacked
on one that was deliberate.

The AOI centre is 52.1 degrees west, which is **UTM zone 22**, and 22WDD is in
zone 22. Preferring the tile from the AOI's own zone is both principled, since it
needs the least reprojection, and happens to reproduce the archive's dominant
choice.

## The band that came back as zeros

*Found by: running the same ten scenes four times and comparing.*

After the loader was rewritten for speed, the same scenes produced different
numbers between runs:

```
S2A_21WXU_20210327   0.8947   0.0000   0.8289   0.0084
S2A_21WXU_20210330   0.0120   0.9094   0.0000   0.6523
```

Under concurrent loading, a COG read fails inside GDAL (`curl_multi_poll()
failed`), the band comes back as zeros, odc fills it, and **no Python exception
is raised**. The scene is written as a perfectly plausible open-water day. The
downstream signature is exact: with NIR zeroed, NDWI = (green - 0)/(green + 0) =
1.0.

Two guards now exist: the loader rejects a scene where one band is over 95
percent fill while the median band is under 50, which resampling can never
produce, and the post-run validator fails on any scene whose mean NDWI is exactly
1.0. Both were needed, because that value sits inside every other range check.

## Two errors of my own, worth recording

Neither of these was in the original pipeline. Both were introduced while fixing
something else, and both are the same shape as the errors they were fixing.

**A tolerance too tight.** The first version of the corrupted-read guard used a
one percentage point spread rule across the 13 bands. It would have discarded an
estimated hundred real observations, because the bands have three native
resolutions and resample with genuinely different fill fractions at a swath edge.
Replaced by the signature of the failure rather than a tolerance.

**A grid scale forgotten.** The georeferenced land mask is derived at 10 m but
applied on the 4 by 4 pooled 40 m grid. Reprojecting without scaling the
transform put the mask in the top-left corner of the frame. The land share read
0.0001 instead of 0.05, and every number downstream still looked plausible.
Caught only because the printed land share was compared against the previous
value.

---

## What the record actually supports

After all of this, the honest position is narrower than the one the project
started with.

- Direction: the later seasons have less spring ice than the earlier ones,
  by about **20 percent** on the cloud-independent metric.
- Confidence: **p = 0.056** over nine seasons. Below the conventional threshold.
  A monotone trend is not detectable at all.
- Interannual variability is nearly as large as the difference between periods.

That is a weaker claim than "32 percent less ice", and it is the one the data
support. It also happens to match what the residents describe, which is not a
steady decline but a loss of reliability.

## Working notes

Things that repeatedly turned out to be worth the time:

1. **Recompute every published number from the raw data.** Three of the errors
   above were found this way, and the recomputation is usually minutes.
2. **Render the intermediate steps and look at them.** The land mask defect was
   invisible in every statistic and obvious in one image.
3. **Compare against something outside the system.** ESA's own cloud cover,
   the product specification, physical reflectance expectations.
4. **Ask what else differs between the groups being compared.** The cloud
   imbalance was not hiding; nobody had asked.
5. **When a fix makes things worse, the bug was load-bearing.**
6. **Test the statistic, not just the pipeline.** Nine seasons had never been
   subjected to a significance test, and that turned out to change the
   conclusion.
7. **Have someone adversarial re-run the numbers.** Several claims in this
   document, including two of my own, did not survive independent reproduction
   the first time.
