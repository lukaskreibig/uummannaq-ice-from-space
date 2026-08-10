# The days the optical series called open water, radar calls ice

An independent check of the Sentinel-2 series against Sentinel-1, re-run on
2026-08-05 against the reprocessed archive.

Reproduce with:

```
python3 scripts/validate_sar.py --dry-run     # the sample, no network
python3 scripts/validate_sar.py               # measure and analyse
```

Results land in `out/archive/sar_validation.csv` and `..._pairs.csv`, and the
run behind this page is committed as `archive/reprocessed_2026/sar_validation.csv`
and `..._pairs.csv`. Every number below comes from those two files, and the
archive they were selected from is `archive/reprocessed_2026/summary.csv`.

---

## The question changed before the first measurement

This check was commissioned to test cloudy days. `docs/limitations.md` argued
that the cloud mask corrupts the series, citing a correlation between reported
ice fraction and detected cloud.

That argument does not survive being checked, because the correlation is
mechanically forced. It was computed against the whole-grid denominator, where a
cell classified as cloud can never also be counted as ice, so more cloud must
produce less ice by construction and a **perfect** cloud mask would give the
same sign. On the reprocessed archive the whole-grid correlation is **-0.609**
over all 1103 scenes; on the clear-sky denominator, restricted to the scenes
that clear the visibility gate, it is **-0.157**. February and March, grouped by
detected cloud, make the point without statistics:

| Detected cloud | n | Median ice / whole grid | Median ice / clear sky |
|---|---|---|---|
| 0.00 to 0.05 | 144 | 0.890 | 0.976 |
| 0.05 to 0.25 | 21 | 0.687 | 0.918 |
| 0.25 to 0.50 | 32 | 0.346 | 0.590 |
| 0.50 to 0.75 | 33 | 0.179 | 0.616 |

Medians, and the word is load bearing: the same bands taken as means read 0.750,
0.580, 0.308 and 0.180 on the left and 0.805, 0.750, 0.542 and 0.553 on the
right, because a handful of near zero scenes drag the average down without
moving the middle. The conclusion is the same either way, but a reader
recomputing this deserves to know which one is on the page.

The left column falls by a factor of five, the right one by a third. So most of
the apparent cloud artefact was the denominator, and a SAR check aimed at cloudy
days would have spent itself on a problem a division already solves.

**What it tests instead.** February and March days that pass the 30 percent
visibility gate and still report under 0.15 ice on the clear-sky denominator. On
the reprocessed archive there are 28 of them, several under a sky the pipeline
itself calls clear: 2025-02-18 at 0.000 detected cloud, 2025-03-01 at 0.000,
2026-03-06 at 0.026. No denominator explains those, and this fjord is frozen in
February and March with near certainty. Those are the days worth putting a
second instrument on.

## How it is measured

Microsoft Planetary Computer's `sentinel-1-rtc`: gamma0, radiometrically terrain
corrected, on a projected grid, reachable anonymously with a SAS token. Raw GRD
would have meant orthorectifying against a DEM for fjord walls over 1000 m high,
which is a project rather than a check.

Each acquisition is cropped to `assets/landmask.tif`, the optical pipeline's own
mask, EPSG:32622 at 10 m. Most scenes share that CRS exactly, so the crop is a
window read with no resampling; Uummannaq sits near the UTM 21N/22N boundary and
the minority that arrive in EPSG:32621 are warped with nearest neighbour. Each
scene yields one number: the **median gamma0 over the fjord water surface, in
decibels**, across about 2.5 million cells.

HH, because over Greenland the mission flies the polar plan with HH and HV. Not
one VV or VH acquisition exists over this AOI, so no threshold calibrated on VV
in the literature transfers here.

There is no classification and no ice fraction. A fjord median is a weak enough
claim that this data supports it; an ice map is not.

## Three groups, and the two ways this could have produced a clean but empty answer

**Suspects** are the days under test: February and March, clear sky, almost no
ice reported. **Ice anchors** are February and March days with a clear sky and
essentially full ice. **Water anchors** are June and July days with a clear
sky and essentially no ice, which is when this fjord opens: over the reprocessed
archive the June median clear-sky ice fraction is 0.001 and July 0.002. They used
to come from August and September, and moving them closer to the suspects
narrows the seasonal confounder rather than merely working around a shorter
reprocessing window.

**A scene serving two roles would put the same measurement in both arms.** Radar
passes every two to four days here, so a suspect and a nearby anchor frequently
resolve to the same acquisition. The test would run without error and produce a
tidy p value that means nothing. Every scene is assigned at most one role, and
any scene claimed by two roles is withdrawn from both.

**A misaligned land mask is invisible in the answer.** Shifting the mask 1000 m
against the scene of 2021-03-10 moved the fjord median by 0.17 dB, from -18.65
to -18.48, while the contrast between land and fjord fell from 5.75 dB to 1.99.
The number stays entirely plausible and nothing raises. So every scene carries
its land contrast and the whole set is checked against it.

That check is deliberately **not** per scene. The first version of this code
rejected scenes under 3 dB, and measuring showed why that was wrong: a correctly
aligned February ice anchor came in at 2.64 dB, because dry snow on rock is
radar dark in midwinter. The innocent winter range and the misalignment range
overlap, so no per-scene threshold separates them, and one that tries throws
away real observations and biases the sample towards summer.

## What came out

55 scenes measured, 50 passing the gates. The five rejected all cover between 1
and 2 percent of the AOI, which is what a scene that only clips the corner of the
frame looks like. Land contrast over the accepted scenes runs 2.51 to 15.35 dB
with a **median of 7.70**, comfortably above the 1.99 that a 1000 m shift
produced, so the geometry holds.

| Group | n | Median gamma0 HH | 95 % CI | Range |
|---|---|---|---|---|
| Ice anchors | 17 | **-16.98 dB** | -18.50 to -15.44 | -19.76 to -14.15 |
| Suspect days | 14 | **-18.34 dB** | -20.75 to -16.91 | -22.85 to -15.70 |
| Water anchors | 19 | **-22.73 dB** | -24.19 to -21.92 | -26.19 to -15.29 |

**The instrument test passes.** Ice and open water separate by 5.74 dB, exact
permutation p = 0.0001, AUC 0.938, and the two anchor groups overlap across
4.47 dB. Both of those are better than the same test on the previous archive
(AUC 0.874, overlap 7.78 dB), and the reason is the anchors rather than the
radar: June water is cleaner than September water, which can already be carrying
the first new ice.

**The suspects sit with the ice.**

- against open water: **p = 0.0003**, they separate, as the hypothesis requires
- against the ice anchors: **p = 0.261**, they do not separate, also as required
- 9 of 14 fall on the ice side of the midpoint between the anchor medians

**Stratified by relative orbit**, which is the check that matters most, because
incidence angle alone could otherwise produce the whole result:

| Orbit | Ice | Suspects | Water |
|---|---|---|---|
| 25 | -18.43 (n=9) | **-17.30 (n=5)** | -25.95 (n=5) |
| 90 | -17.04 (n=5) | **-16.58 (n=5)** | -22.32 (n=11) |
| 171 | -14.15 (n=1) | -19.69 (n=2) | -21.92 (n=3) |

In both well populated orbits the suspects sit at or above the ice anchors and
five to nine decibels from the water. Inside a single orbit the viewing geometry
is held fixed, so that agreement is not an artefact of which orbits landed in
which arm. Orbit 171 goes the other way and is reported here because it does:
with one ice anchor and two suspects it carries no weight either way, but leaving
it out would be a choice made after seeing it.

Split by month rather than orbit, February is the sharpest case: ice anchors at
-17.29 dB and suspect days at -17.30, which is the same number. In March the
suspects fall to -18.84 against -16.98 for the anchors, which is the direction
wet snow pushes and therefore the conservative direction.

## What this establishes

On the late winter days when the optical pipeline reports a nearly ice free
fjord under a nearly clear sky, Sentinel-1 backscatter over the same water
surface lies in the range of confirmed fast ice and not in the range of confirmed
open water. Those days are therefore **evidence of a failure in the optical
chain, not of ice loss**.

The failure is not the cloud mask. These days were chosen for having clear skies.
The likeliest cause is the brightness gate at low winter sun, and the reprocessed
archive can be asked directly, because it writes `sun_elev` to every one of its
1103 rows. An earlier version of this page said the column had never been written
and quoted the legacy archive's 1552 rows; that was true of the run this one
replaced.

Asked, it answers in the expected direction. Over the 219 February and March
scenes that clear the visibility gate, the 28 suspects sit at a median sun
elevation of **12.60 degrees against 16.34** for the rest, a difference of 3.74
degrees at a one-sided permutation p of 0.009. Sun elevation climbs steadily
through the window, so the test that matters is within a month, and there the
effect survives: February 8.36 against 10.06 (p = 0.023), March 13.53 against
18.38 (p = 0.0001).

**It points, it does not settle.** Twelve of the 28 come from 2025, and 2025 is
the one season in the record that genuinely froze late, so some of its February
suspects may be open water rather than a gate failure. Drop that season and the
effect falls to 3.09 degrees at p = 0.059, which is no longer significant at any
conventional level. What the archive supports is that the anomalies concentrate
at low sun; what it cannot do is separate a dim scene from a season that started
late.

## What this does not establish

- **It does not validate the ice fraction.** The comparison is frozen against
  open at fjord level. There is no calibration, no RMSE, no agreement statistic
  on the continuous value. Reading this as "the series is correct" reads
  something in that is not there.
- **It does not validate the break-up date**, which is the limitation that hurts
  most, because the story runs towards break-up. Break-up falls exactly in the
  window where wet snow and melt ponds depress C band backscatter, and radar and
  optical both read melt water on ice as water. There they are not independent
  and err in the same direction.
- **It does not correct the archive.** It bounds an error, it does not repair a
  time series. A correction would need a trustworthy per scene ice fraction from
  SAR, and 4.47 dB of class overlap does not provide one.
- **It says nothing about the trend.** Nine winters remains the binding
  constraint. The sample is drawn from extreme cases on purpose and is not
  representative, so deriving a correction factor for the seasonal means from it
  would be wrong.
- **The seasons still do not match.** Water anchors come from June and July,
  suspects from February and March, because in March this fjord has essentially
  no open water and a season matched water anchor does not exist anywhere in the
  record. Four months is better than the six the previous run carried, and it is
  not zero: the comparison keeps a seasonal confounder in sea state, wind
  climate and water temperature that cannot be removed at this site.
- **The anchors are labelled by the pipeline under test**, from its clear-sky
  regime. That is defensible, since the error being examined is not a fair
  weather problem, but it is not independent ground truth. One water anchor of
  the nineteen, 2018-06-27 at -15.30 dB, sits above the ice median, most likely
  wind roughened water. An earlier version of this page named two anchors from
  late September at -14.14 and -16.79 dB; those belong to the run whose water
  anchors came from August and September, and neither value appears in the
  committed measurements.
- **Five of the fourteen suspects fall on the water side**, and they are the
  later ones. Wet snow would put ice bearing days there, and so would
  genuinely open water. This method cannot tell those apart, which is the same
  limitation as the break-up point above.
- **Up to a day separates the two sensors**, and up to ten hours within that day.
  Saying "the same day" assumes the ice held still.

## The honest sentence

*On the late winter days when the optical pipeline reports an almost ice free
fjord under an almost clear sky, Sentinel-1 sees backscatter in the range of
confirmed fast ice, in both well sampled viewing geometries, and in February the
two medians are the same number. Those days are a fault in the optical chain
rather than open water. The radar separates ice from water here only to about
four and a half decibels of overlap, so this holds as a statement about the
group of days and not about any single one.*
