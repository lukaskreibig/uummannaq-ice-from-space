# The days the optical series called open water, radar calls ice

An independent check of the Sentinel-2 series against Sentinel-1, run on 2026-08-04.

Reproduce with:

```
python3 scripts/validate_sar.py --dry-run     # the sample, no network
python3 scripts/validate_sar.py               # measure and analyse
```

Results land in `out/archive/sar_validation.csv` and `..._pairs.csv`. Every
number below comes from those two files.

---

## The question changed before the first measurement

This check was commissioned to test cloudy days. `docs/limitations.md` argued
that the cloud mask corrupts the series, citing a correlation of r = -0.42
between reported ice fraction and detected cloud across the 1552 archived
scenes.

That number does not survive being checked. It was computed on the whole-grid
denominator, where a cell classified as cloud can never also be counted as ice,
so more cloud forces less ice by construction and a **perfect** cloud mask would
produce the same negative sign. On the clear-sky denominator, which is what this
project publishes, the same correlation is **+0.058**. February and March,
grouped by detected cloud, make the point without statistics:

| Detected cloud | n | Ice / whole grid | Ice / clear sky |
|---|---|---|---|
| 0.00 to 0.05 | 176 | 0.897 | 0.999 |
| 0.05 to 0.25 | 33 | 0.491 | 0.613 |
| 0.25 to 0.50 | 18 | 0.376 | 0.655 |
| 0.50 to 0.75 | 15 | 0.248 | 0.713 |

The left column collapses, the right one does not. So the headline cloud
artefact was mostly the denominator, and the SAR check would have spent itself
on a problem that a division already solves.

**What it tests instead.** Of the 233 February and March scenes that pass the
30 percent visibility gate, 26 report under 0.15 ice on the clear-sky
denominator **with a median detected cloud of 0.055 and 83 percent of the grid
clear**. No denominator explains those, and this fjord is frozen in February and
March with near certainty. Those are the days worth putting a second instrument
on.

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
essentially full ice. **Water anchors** are August and September days with a
clear sky and essentially no ice, which is when this fjord genuinely opens.

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

62 scenes measured, 58 passing the gates. Four were rejected: three cover only
about one percent of the AOI, and one 2025 acquisition covers 51 percent. Land
contrast over the accepted scenes runs 2.28 to 14.10 dB with a **median of
7.09**, comfortably above the 1.99 that a 1000 m shift produced, so the geometry
holds.

| Group | n | Median gamma0 HH | 95 % CI | Range |
|---|---|---|---|---|
| Ice anchors | 19 | **-17.02 dB** | -18.27 to -15.71 | -21.92 to -14.04 |
| Suspect days | 16 | **-18.30 dB** | -20.57 to -16.80 | -22.83 to -15.40 |
| Water anchors | 23 | **-22.54 dB** | -23.89 to -21.52 | -25.26 to -14.14 |

**The instrument test passes.** Ice and open water separate by 5.52 dB, exact
permutation p < 0.0001, AUC 0.874. So a scale exists. Its resolution is poor:
the two anchor groups overlap across 7.78 dB.

**The suspects sit with the ice.**

- against open water: **p = 0.0023**, they separate, as the hypothesis requires
- against the ice anchors: **p = 0.153**, they do not separate, also as required
- 11 of 16 fall on the ice side of the midpoint between the anchor medians

**Stratified by relative orbit**, which is the check that matters most, because
incidence angle alone could otherwise produce the whole result:

| Orbit | Ice | Suspects | Water |
|---|---|---|---|
| 25 | -18.37 (n=8) | **-18.77 (n=7)** | -23.60 (n=7) |
| 90 | -17.50 (n=7) | **-16.43 (n=6)** | -22.57 (n=11) |
| 171 | -15.41 (n=2) | -19.65 (n=2) | -20.02 (n=4) |

In both well populated orbits the suspects sit within about a decibel of the ice
anchors and four to six decibels from the water. Inside a single orbit the
geometry is held fixed, so that agreement is not an artefact of which orbits
landed in which arm. Orbit 171 goes the other way, and it is reported here
because it does: with two ice anchors and two suspects it carries no weight
either way, but leaving it out would be a choice made after seeing it.

## What this establishes

On the late winter days when the optical pipeline reports a nearly ice free
fjord under a nearly clear sky, Sentinel-1 backscatter over the same water
surface lies in the range of confirmed fast ice and not in the range of confirmed
open water. Those days are therefore **evidence of a failure in the optical
chain, not of ice loss**.

The failure is not the cloud mask. These days were chosen for having clear skies.
The most likely cause is the brightness gate at low winter sun, and this cannot
be settled from the archive, because `sun_elev` was never written to it: all 1552
rows carry 19 of the 22 header columns.

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
  SAR, and 7.78 dB of class overlap does not provide one.
- **It says nothing about the trend.** Nine winters remains the binding
  constraint. The sample is drawn from extreme cases on purpose and is not
  representative, so deriving a correction factor for the seasonal means from it
  would be wrong.
- **The seasons do not match.** Water anchors come from August and September,
  suspects from February and March, because in March this fjord has essentially
  no open water and a season matched water anchor does not exist. The comparison
  therefore carries a seasonal confounder in sea state, wind climate and water
  temperature that cannot be removed at this site.
- **The anchors are labelled by the pipeline under test**, from its clear-sky
  regime. That is defensible, since the error being examined is not a fair
  weather problem, but it is not independent ground truth. Two water anchors
  from late September, at -14.14 and -16.79 dB, sit above the ice median, most
  likely wind roughened water or the first new ice of the season.
- **Five of the sixteen suspects fall on the water side**, four of them in the
  second half of March. Wet snow would put ice bearing days there, and so would
  genuinely open water. This method cannot tell those apart, which is the same
  limitation as the break-up point above.
- **Up to a day separates the two sensors**, and up to ten hours within that day.
  Saying "the same day" assumes the ice held still.

## The honest sentence

*On the late winter days when the optical pipeline reports an almost ice free
fjord under an almost clear sky, Sentinel-1 sees backscatter in the range of
confirmed fast ice, in both well sampled viewing geometries. Those days are a
fault in the optical chain rather than open water. The radar separates ice from
water here only to about seven decibels of overlap, so this holds as a statement
about the group of days and not about any single one.*
