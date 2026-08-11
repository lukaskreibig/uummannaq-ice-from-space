# What a second optical instrument sees on the same day

This page grew in four parts, written in the order they were measured, and the
last two matter most. If you are reading it to find the weak point, start at
part three.

| | question | answer |
|---|---|---|
| **Part one** | does a second optical sensor see the same fjord on the same day? | yes, to an RMSE of 0.026 on days whose answer was not in doubt, and it reads the contested April days as wetter still |
| **Part two** | and at low winter sun, where Level 2 cannot go? | yes, and CFMask discards 83 percent of a frozen fjord, which is a statement about optical cloud detection over ice rather than about one checkpoint |
| **Part three** | did the record begin on an unusually icy stretch? | no, but asking cost a hypothesis: the fjord is frozen on 36 days the chain calls open, twice as often after 2021 |
| **Part four** | closed ice the chain misread, or floes it read correctly? | mostly neither, and placing the days where radar puts them halves the Landsat decline |

What part four costs the number this project publishes is computed in
[limitations.md](limitations.md#and-carried-onto-the-published-series-it-costs-three-points):
22.6 percent becomes about 19.5.

The first comparison of this series against another optical sensor, run on
2026-08-11 against the reprocessed archive.

Reproduce with:

```
python3 scripts/landsat_crosscheck.py
```

The run behind this page is committed as
`archive/reprocessed_2026/landsat_crosscheck.csv`. Every number below comes from
that file.

---

## What is being compared, and what makes it a check

Landsat 8 and 9, Collection 2 Level 2, over the same land mask, in the same CRS
(EPSG:32622, so the imagery is never warped), with the **same** indices, the
**same** thresholds and the **same** brightness gate the Sentinel-2 pipeline
uses. Only the instrument changes.

Three things make an agreement here mean something:

- **Different optics.** OLI is not MSI: other band passes, other detectors,
  another orbit, and here an overpass usually within two hours of Sentinel-2's.
- **Different atmosphere.** Landsat Collection 2 Level 2 is surface reflectance
  from LaSRC. The pipeline reads Sentinel-2 L1C, which is top of atmosphere.
  The two corrections share nothing.
- **Different cloud mask.** CFMask in the QA_PIXEL band against a UNetMobV2
  trained on CloudSEN12.

82 pairs survive, spanning all ten seasons, at Landsat sun elevations of 14.3 to
42.5 degrees. Over all of them the two series correlate at **0.987** with an
RMSE of 0.078.

## The gate that had to be measured rather than chosen

The scene-level cloud percentage is nearly useless here. It covers a 185 km
Landsat tile, and this fjord is 15 km across. The two controls that disagree
worst, 2025-04-19 at -0.37 and 2025-04-09 at -0.12, both pass a 20 percent
scene-cloud filter comfortably.

Sorting the controls by the share of the fjord Landsat actually **classified**
separates them at once:

| Landsat classified share | n | control RMSE | worst |
|---|---|---|---|
| below 0.60 | 4 | 0.183 | 0.366 |
| 0.60 to 0.80 | 6 | 0.002 | 0.005 |
| 0.80 to 0.95 | 5 | 0.055 | 0.123 |
| 0.95 and above | 19 | 0.004 | 0.017 |

So the gate is on the classified share, at 0.90, and it is the same kind of gate
the pipeline already applies to itself. An earlier version of this run had no
such gate and reported a control RMSE of 0.066 with a worst case of 0.366, which
would have made every finding below unreadable.

A second thing had to be fixed before the numbers were trustworthy. The first
version signed every asset separately, four requests per scene, and the signing
endpoint answered 429 for 139 of 617 days. The run completed and reported a
**tighter** agreement than it had earned, because the days it lost were not
random. It now takes one collection token and reports what it dropped.

## What came out

With the gate, mean values per group, and the sign is Landsat minus Sentinel-2:

| Group | n | Sentinel-2 | Landsat | bias | RMSE |
|---|---|---|---|---|---|
| April anchor, control | 15 | 0.9966 | 0.9877 | -0.0089 | 0.0320 |
| July anchor, control | 8 | 0.0030 | 0.0029 | -0.0001 | 0.0003 |
| **April anchor, outlier** | **4** | **0.6648** | **0.5072** | **-0.1576** | **0.1594** |
| winter, ordinary | 20 | 0.9870 | 0.9459 | -0.0411 | 0.1331 |
| season, ordinary | 35 | 0.3966 | 0.3890 | -0.0076 | 0.0257 |

**The controls are the load-bearing row.** Across the 23 days whose answer was
never in doubt, a closed fjord in early April and an open one in July, the two
instruments agree with a bias of -0.006 and an **RMSE of 0.026**. On July water
alone the RMSE is 0.0003. Two sensors, two atmospheric corrections and two cloud
masks landing that close is what makes the rest of the table readable, and it is
also the first evidence in this project that the thresholds are not overfitted
to Sentinel-2.

**The April outliers are not a Sentinel-2 artefact.** These are the days
[limitations.md](limitations.md#melt-ponds-bias-break-up-early-and-now-there-is-a-number)
identifies, where the pipeline reports half a fjord of open water three to six
weeks before that season has ever broken up. Landsat sees the same surface, and
reads it as **wetter still**:

| Day | Sentinel-2 | Landsat | difference | against a noise floor of 0.026 |
|---|---|---|---|---|
| 2023-04-12 | 0.5207 | 0.3756 | -0.1451 | 6 times |
| 2023-04-11 | 0.5952 | 0.4158 | -0.1794 | 7 times |
| 2025-04-17 | 0.7128 | 0.5876 | -0.1252 | 5 times |
| 2025-04-18 | 0.8305 | 0.6498 | -0.1808 | 7 times |

Four for four, in the same direction, at five to seven times the control noise.
The fifth outlier with a Landsat partner, 2023-04-14, classified only 0.61 of
the fjord on the Landsat side and is excluded by the gate rather than quietly
kept; it read -0.377, in the same direction.

## What this establishes

On the April days where the pipeline reports far less ice than a fjord that has
never once been open at that date could hold, a second optical instrument, with
an independent atmospheric correction and an independent cloud mask, sees the
same thing and slightly more of it. Whatever those surfaces were on those days,
they read as water to two satellites.

That removes one worry and sharpens another. The worry it removes is that the
Sentinel-2 chain has a defect that fires preferentially in 2023 and 2025, the
seasons carrying the measured decline. It does not: the surface really did look
like that.

## What this does not establish

- **It does not show the fjord was open.** Both instruments are optical, and
  liquid water on ice absorbs in the near infrared whichever satellite is
  looking. Two optical sensors agreeing that a surface reads as water establishes
  that it read as water. Separating wet ice from open water needs radar, which
  has its own wet-surface problem, and that is the same wall the break-up date
  runs into.
- **It does not calibrate the series.** There is no reference truth here. Both
  sides are model output, and agreement between two models is consistency, not
  accuracy.
- **The systematic offset on wet days is unexplained.** Landsat reads 0.16 lower
  than Sentinel-2 on the outlier days and 0.006 lower on the dry controls. A hard
  threshold is the likely mechanism, because near NDWI 0.20 a small radiometric
  difference moves a great deal of area, and it is the strongest argument in this
  project for a sub-pixel treatment that reports a fraction instead of a class.
  That argument has since been tested and lost:
  [unmixing-feasibility.md](unmixing-feasibility.md) finds the arithmetic sound
  and the anchor unusable, because the pure ice spectrum moves by a factor of
  1.7 across days that are all unambiguously frozen.
- **The winter row is not clean.** Ordinary winter days sit at a bias of -0.041
  with an RMSE of 0.133, and three of the 20 disagree by more than 0.1. Winter is
  where low sun, long shadows from 1000 m walls and thin cloud all bite hardest,
  and this comparison does not resolve them.
- **One anomaly is not a sample, and the reason is structural.** Only a single
  February or March anomaly had a clear Landsat partner here, 2025-03-15, where
  Sentinel-2 reports 0.0032 ice and Landsat 0.0029. Both call that fjord open.
  That scarcity is not bad luck: Collection 2 Level 2 surface reflectance is not
  produced above a solar zenith of 76 degrees, so these 82 pairs span sun
  elevations of 14.3 to 42.5 degrees, and the 28 clear-sky winter anomalies all
  sit below that floor. **This page therefore cannot speak about the one regime
  where the pipeline is unexplained.** Level 1 has no such floor and is also the
  closer product, since the pipeline reads top-of-atmosphere itself. Over this
  fjord it holds 865 daylight Landsat 8 and 9 scenes in the window, 320 of them
  below the Level 2 floor, and **55 same-day pairs with Sentinel-2 in February or
  March**. Reaching the pixels needs a credential this repository does not have;
  `scripts/landsat_l1_inventory.py` counts what is there and documents both
  routes.

## The tension worth stating

That last line contradicts the radar. [sar-validation.md](sar-validation.md)
concludes that on the late winter days when the optical chain reports an almost
ice free fjord under an almost clear sky, Sentinel-1 backscatter sits in the
range of confirmed fast ice. For 15 March 2025, a second optical instrument
instead agrees with the first that the fjord is open.

Both can be true. 2025 is the one season in the record that genuinely froze
late, so an open fjord in mid March is possible there, and two optical sensors
sharing a failure mode is exactly what the radar check was built to catch. What
is not defensible is picking whichever of the two checks suits the argument. One
day is one day, and the honest reading is that the two cross-checks disagree on
the only case where both have something to say.

## The honest sentence

*On the April days where this pipeline reports a half open fjord weeks before
that season has ever broken up, Landsat sees the same surface and reads it as
wetter still, four times out of four, at five to seven times the agreement noise
measured on days whose answer was not in doubt. The reading is not a Sentinel-2
defect. Whether those surfaces were wet ice or open water is a question no
optical instrument can answer.*

---

# Part two: the same question at low sun, on Level 1

Everything above runs on Collection 2 Level 2, and Level 2 has a floor. Surface
reflectance is not produced above a solar zenith of 76 degrees, so those 82 pairs
span sun elevations of 14.3 to 42.5 degrees and cannot speak about the February
and March scenes that report almost no ice under a sky the pipeline calls clear.
Those are the sharpest open question this project has.

Collection 2 Level 1 has no such floor and is the closer product besides: the
pipeline reads Sentinel-2 L1C, which is top of atmosphere, so a Level 1
comparison changes the sensor and nothing else. Run on 2026-08-11 over the USGS
landsatlook catalogue, committed as
`archive/reprocessed_2026/landsat_l1_winter.csv`.

```
python3 scripts/landsat_l1_crosscheck.py --regime winter
```

## The factor of seven, stated before any result

Sentinel-2 L1C reflectance is already divided by the cosine of the solar zenith
angle. **Landsat Level 1 is not.** The MTL coefficients give reflectance without
that division and it has to be applied by hand. At a sun elevation of 7.75
degrees the factor is 7.4, and measured on 2019-02-19 fast ice reads 0.081 in
green uncorrected against 0.601 corrected, where Sentinel-2 over fast ice sits at
0.44 to 0.74.

Skipping it would not have produced an obvious error. It would have put every
February scene below the 0.10 brightness floor, Landsat would have reported no
ice all winter, and that would have read as a triumphant confirmation of the very
anomalies this comparison exists to test.

## What the two instruments agree on

55 same-day pairs in February and March, all below the Level 2 floor. **15 clear
the same 0.90 classified-share gate** the Level 2 run established, at sun
elevations of **6.11 to 13.47 degrees**.

| | bias | RMSE |
|---|---|---|
| all 15 | -0.0105 | 0.0602 |
| the 13 that agree within 0.05 | -0.0009 | **0.0123** |

Two pairs carry the whole spread, 2022-02-21 at +0.072 and 2022-02-28 at -0.217,
both under moderate scene cloud of 11 and 17 percent.

**And the load-bearing rows are the low ones.** These are the days this project
has been carrying as unexplained: a fjord reporting almost no ice in February or
early March, under a sky the pipeline's own mask calls clear.

| Day | sun | Sentinel-2 | Landsat L1 | difference |
|---|---|---|---|---|
| 2025-02-19 | 7.95 | 0.014 | 0.013 | -0.001 |
| 2025-02-20 | 8.30 | 0.013 | 0.014 | +0.001 |
| 2025-03-01 | 11.66 | 0.072 | 0.086 | +0.013 |
| 2026-02-14 | 6.11 | 0.279 | 0.274 | -0.004 |
| 2026-03-04 | 12.72 | 0.060 | 0.051 | -0.009 |

Bias **-0.0001**, RMSE **0.0076**. 2025-03-01 is one of the three scenes
[limitations.md](limitations.md#cloud-detection-is-unreliable-and-the-denominator-mattered-more)
names by date as a clear-sky anomaly.

**So the low winter readings are not a Sentinel-2 defect.** A second instrument,
with its own radiometry, its own orbit and its own cloud mask, standing in the
same low sun on the same day, reads the same nearly open fjord. What the optical
chain reported, it reported correctly.

## And the half nobody was looking for

CFMask is the operational cloud mask behind every Landsat Level 2 product in the
world. Over this fjord it discards the scene in near-perfect proportion to how
much ice is in it:

| Sentinel-2 ice | n | median share of the fjord Landsat classified |
|---|---|---|
| under 0.30 | 9 | 0.91 |
| 0.30 to 0.70 | 10 | 0.78 |
| 0.70 to 0.95 | 10 | 0.60 |
| **0.95 and above** | **20** | **0.17** |

On a fjord that is frozen shore to shore, an independent, mature, operational
cloud mask throws away **83 percent of it**. On 19 of the 55 pairs it discards
the fjord entirely, and the median Sentinel-2 ice fraction on those days is
1.000. On 2019-02-19, at 7.75 degrees, CFMask flags 100 percent of the fjord as
cloud while the same pixels read 0.606 in green and 0.804 in the near infrared.

This page opened by saying that ice and cloud are both white and bright and that
no threshold solves it. That was an assertion about this pipeline's own model.
It is now a measured property of a second, unrelated cloud mask, which makes it a
statement about optical cloud detection over the cryosphere rather than about
one checkpoint.

## What this part does not establish

- **The 15 surviving pairs are selected toward low ice**, precisely because
  CFMask keeps more of a dark fjord than a bright one. The comparison is
  therefore conditioned on the days it can see. That conditioning happens to
  favour the question being asked, since the anomalies are low-ice days, but it
  means the bias and RMSE above are not a general accuracy for winter.
- **Confirming the reading is not confirming the fjord was open.** Both
  instruments are optical and share the same physics. What is established is that
  the surface reported as water read as water to two independent radiometers, not
  that there was no ice under it. That is the same wall
  [sar-validation.md](sar-validation.md) runs into from the other side.
- **40 of 55 pairs were dropped**, 19 of them because CFMask left nothing. A
  comparison that discards three quarters of its sample is a bound, not a survey.


# Part three: the seasons before Sentinel-2, and what asking for them found

Both parts above compare two instruments on the same day. This part set out to
ask the one question a ten-season record cannot ask about itself, **did the
record begin on an unusually icy stretch**, and ended up answering a different
and more uncomfortable one. Both answers are below, in the order they arrived,
because two of the three things this section originally claimed were wrong and
the way they broke is the useful part.

```
python3 scripts/landsat_l1_inventory.py --reach
python3 scripts/landsat_season_series.py --seasons 2013-2026
python3 scripts/commissioning_check.py
python3 scripts/thermal_audit.py
```

## How far back the archive reaches, and why that is not how far the record can

Committed as `archive/reprocessed_2026/landsat_reach.csv`.

| instrument | SWIR | seasons | first | last | scenes | median per season |
|---|---|---|---|---|---|---|
| MSS | **no** | 19 | 1973 | 1993 | 343 | 24 |
| TM | yes | 17 | 1985 | 2013 | 291 | 18 |
| ETM+ | yes | 16 | 2000 | 2019 | 216 | 15 |
| OLI | yes | 14 | 2013 | 2026 | 1028 | 60 |

From 1990 the archive holds 36 seasons over this fjord, at a median of 31 scenes
inside the window and a range of 9 to 120. MSS carries no shortwave infrared, so
NDSI cannot even be formed on it, but TM, ETM+ and OLI could all in principle run
this pipeline.

What is missing is any way to join one to the next. Carrying a fixed threshold
across a sensor boundary needs same-overpass pairs to anchor it, and over this
AOI, in the whole archive, there are **zero** between TM and ETM+ and **zero**
between TM and OLI. The boundaries fall in 1999 and 2013, exactly where an
early-late split of a long record would sit, so an uncalibrated join would be
indistinguishable from the trend it is meant to measure.

ETM+ against OLI has two, and both are worth naming.

```
2013-03-30   ETM+  15h UTC  sun 23.0  cloud 1.0
2013-03-30   OLI   15h UTC  sun 23.0  cloud 0.8

2019-06-06   OLI   00h UTC  sun 10.0  cloud 1.2
2019-06-06   ETM+  23h UTC  sun 10.7  cloud 0.0
```

The second is real but useless here: 6 June, midnight sun at 10 degrees, an hour
apart, over ice already breaking up. The first is as clean as could be asked for,
and what it shows is the subject of the next section. What it cannot do is
calibrate: one pair fixes the relationship at ONE surface state, and a gain and
an offset across the dynamic range cannot be fitted from a single point.

Steiro et al. (2021) did reach back to 1985 on this fjord, by setting thresholds
per image from histogram analysis. That sidesteps calibration by putting an
analyst inside every measurement. That is a study; this is a pipeline. So the
extension refuses the boundary instead of crossing it: **Landsat 8 and 9 alone**,
one instrument family, four seasons before Sentinel-2 rather than thirty.

## The detour: a hypothesis that did not survive its own test

The 2013 season looked broken. Four scenes in March and early April are nearly
cloud free over a fjord every other year calls frozen and still read 5, 10, 15
and 15 percent ice. On 22 March the whole fjord measures green 0.206 and near
infrared 0.090, where fast ice sits between 0.44 and 0.74, so every cell fails
the brightness gate and falls through to water. All four are Tier 1, so it is not
a catalogue flag.

The obvious suspect was the satellite. Landsat 8 launched on 11 February 2013 and
reached its operational WRS-2 orbit on 11 April, all four scenes are earlier, and
the first usable scene after that boundary reads 0.83. An earlier version of this
page cut the record at that published mission date and called the matter settled.

It was not. The 2013-03-30 pair above is exactly the test that hypothesis needed,
and running both scenes through this pipeline gives:

| | sun | cloud | classified share | ice | green | NIR | SWIR |
|---|---|---|---|---|---|---|---|
| OLI | 23.0 | 0.8 | 1.00 | 0.098 | 0.226 | 0.115 | 0.016 |
| ETM+ | 23.0 | 1.0 | 0.71 | 0.112 | 0.223 | 0.120 | 0.009 |

ETM+ had been in normal operations for fourteen years and reads the same surface
to within a hundredth. **The radiometry was never the problem.** The lower ETM+
share is the scan line corrector failure of 2003, whose wedge gaps arrive as fill
and cost coverage rather than accuracy.

## What the thermal band said instead

Reflectance cannot separate dark ice from open water, because both are dark. A
thermometer can, because seawater at this salinity freezes near 271.35 K and open
water cannot radiate colder than that. Both satellites carry one. Every control
below comes from 2013 itself, so no difference between years can be mistaken for
the answer.

| day | reported ice | kelvin | celsius |
|---|---|---|---|
| 2013-03-22 | 0.052 | 265.5 | -7.6 |
| 2013-03-30 | 0.098 | 263.7 | -9.5 |
| 2013-03-30 (ETM+) | 0.112 | 264.2 | -8.9 |
| 2013-04-04 | 0.151 | 265.8 | -7.3 |
| 2013-04-09 | 0.148 | 267.7 | -5.5 |
| 2013-04-23, control, frozen | 0.827 | 260.0 | -13.2 |
| 2013-05-29, control, open | 0.001 | 272.7 | -0.4 |
| 2013-06-12, control, open | 0.001 | 278.3 | +5.2 |

All four questioned days sit four to eight kelvin below the point at which
seawater is still liquid, and the two days the chain calls open sit above it.
**The fjord was frozen and the chain read it as water**, because the surface was
too dark for the brightness gate. That is the failure
[limitations.md](limitations.md) already documents on twelve wet April days,
here across a whole early season, and it is a property of the classifier rather
than of 2013 or of Landsat 8. So the mission-date cut is gone, 2013 is treated
like every other season, and the error is measured uniformly instead.

## Measured uniformly: 226 days with a thermometer held to them

`archive/reprocessed_2026/thermal_audit.csv`. Frozen share is the fraction of
fjord cells radiating below 271.35 K, which is a number of the same kind as the
ice fraction and can be set beside it.

| chain reports | n | median K | frozen share | gap |
|---|---|---|---|---|
| ice 0.90 and above | 109 | 259.9 | 1.000 | +0.003 |
| ice 0.50 to 0.90 | 33 | 268.4 | 0.999 | +0.179 |
| ice 0.10 to 0.50 | 25 | 268.0 | 1.000 | +0.657 |
| ice under 0.10 | 59 | 274.6 | 0.000 | -0.001 |

At both ends the two agree to three decimals. In between they do not agree at
all: where the chain reports a tenth to a half of the fjord frozen, the thermal
band reports all of it. Over this fjord the thermometer sees essentially two
states, frozen or not, and the chain's intermediate readings have no counterpart
in it.

Counting a day as CONTRADICTED when the chain calls the fjord mostly open while
more than half of it radiates below freezing, 36 of 226 days qualify, and they
are not spread evenly:

```
early seasons   9 of  91   0.10
late seasons   27 of 135   0.20
```

2021 at 0.58, 2025 at 0.32, 2023 at 0.27 and 2026 at 0.26 against zero in 2015,
2017, 2018, 2019 and 2022. **An error twice as common in the later period, always
in the same direction, is part of the measured decline rather than noise around
it.**

And Sentinel-2 makes it too. On the 23 contradicted days both satellites saw,
Landsat reads a median 0.160 and Sentinel-2 0.176, correlated at r = +0.986. This
is not a Landsat problem to be noted and set aside; it is in the published series.

## How much of the decline is it

The honest answer is a range, and the width of the range is the result.

| | contradicted days | Landsat decline as measured | with those days handed a frozen fjord |
|---|---|---|---|
| threshold at 271.35 K | 36 | 20.6 % | 0.8 % |
| 2 K safety margin | 22 | 20.6 % | 13.2 % |
| 4 K safety margin | 15 | 20.6 % | 16.4 % |
| 5 K safety margin | 13 | 20.6 % | 19.0 % |

Neither end of the repaired column is an estimate. It hands every contradicted
day a completely frozen fjord, which no thermal reading supports, and at zero
margin it accepts days a tenth of a kelvin under the line. The margin exists
because brightness temperature is not surface temperature: there is no emissivity
or atmospheric correction here, and both push the reading low, which is the
direction that manufactures contradictions rather than hiding them.

What survives every margin is the asymmetry. The failure is rarer early than
late, so it inflates the measured decline; how much is not settled by this page.

## The series, and the question it was built for

Season means over day 45 to 180, as the mean over nine fifteen-day bins with
interior gaps interpolated. A season that never sampled the break-up is dropped
rather than reported, because a mean over February to mid May is a different
quantity from a mean over the whole window: across this record the per-bin means
run 0.65, 0.63, 0.93, 0.97, 0.84, 0.75, 0.49, 0.18, 0.00. `bins` counts bins
actually observed out of nine.

| season | Landsat days | bins | Landsat | bins | Sentinel-2 |
|---|---|---|---|---|---|
| 2013 | 7 | 5 | 0.244 | . | . |
| 2014 | 14 | 7 | 0.824 | . | . |
| 2015 | 9 | 7 | 0.926 | . | . |
| 2016 | 9 | 7 | 0.452 | . | . |
| 2017 | 11 | . | dropped | 8 | 0.864 |
| 2018 | 16 | 8 | 0.745 | 9 | 0.774 |
| 2019 | 12 | 7 | 0.603 | 9 | 0.612 |
| 2020 | 13 | 8 | 0.659 | 9 | 0.668 |
| 2021 | 12 | 8 | 0.246 | 9 | 0.434 |
| 2022 | 26 | 9 | 0.765 | 9 | 0.797 |
| 2023 | 22 | 7 | 0.479 | 9 | 0.454 |
| 2024 | 30 | 8 | 0.755 | 9 | 0.714 |
| 2025 | 22 | 9 | 0.330 | 9 | 0.371 |
| 2026 | 23 | 9 | 0.457 | 9 | 0.492 |

Landsat 2017 samples February to mid May and nothing after, so it has no season
mean. It is still in the agreement table below, on the six bins both sensors
filled, because comparing two instruments and describing a season are different
questions.

**Agreement, over the bins both sensors filled: bias -0.0253, RMSE 0.0549,
r = +0.983.** Over whichever bins each sensor happened to fill it reads bias
-0.0307 and RMSE 0.0687, and over the raw days each holds, bias -0.0404 and RMSE
0.0972. Only the first compares instruments; the other two also compare the parts
of the season each of them sampled, and the RMSE falls by a third from the
loosest of the three to the strictest.

Then the question this section was built for:

```
early mean over the seasons Sentinel-2 also sees    0.6694
early mean once the four earlier seasons join it    0.6363
the shift reaching further back buys               -0.0331
```

Reaching back **lowers** the early baseline rather than raising it, by 0.033. So
the record did not begin on an unusually icy stretch; if anything the seasons
before it were slightly less icy, which makes the published decline conservative
rather than flattered.

That conclusion is worth exactly as much as 2013 is, and 2013 is the season the
thermal band contradicts on four of its seven days. Without it the shift is
+0.032 in the other direction, on three added seasons instead of four. **The
direction of this test is not stable and the honest reading is that four extra
seasons do not settle where the record began.** What they do settle is that the
answer is not large: every treatment puts the shift inside 0.04, against a
between-season spread of 0.25.

## What this part does not establish

- **A frozen surface is not a closed one.** Ice broken into floes with leads
  narrower than the thermal band can resolve would read frozen to the thermometer
  and open to the classifier, and both would be right. This bounds the reading of
  dark ice as water; it does not measure ice fraction, and it cannot tell that
  case from the one it is aimed at.
- **The thermal band is coarser than the reflective ones**, 100 m data delivered
  on a 30 m grid, so a partly frozen fjord averages towards the middle. That
  blunts the test on mixed days and leaves the clear cases clear.
- **It is still the same physics twice.** OLI and MSI are both optical, both read
  melt water on ice as water, and both were told the same thresholds. The thermal
  band is a genuinely different measurement and it is the reason this section
  concludes anything; the reflective comparison alone could not.
- **The added seasons are Landsat only.** Nothing cross-checks 2013 to 2016, so
  they inherit whatever OLI does on this fjord without a second opinion.
- **Nine to thirty days a season is thin.** The bins fix the weighting and the
  interpolation fills gaps inside the sampled range; neither creates coverage.

# Part four: radar on the contradicted days

Part three left one question open and it is the one that decides the size of the
correction. A thermometer says a surface is frozen. It cannot say whether that
surface is one closed sheet the classifier misread, or a field of floes with
leads between them that the classifier read correctly, because floe tops radiate
exactly as cold as a closed sheet and leads narrower than 100 m average away.

Sentinel-1 can separate them, and it was asked about all 36 days.

```
python3 scripts/sar_thermal_days.py --window 2 --ref-window 5
```

`archive/reprocessed_2026/sar_thermal_days.csv` and `sar_thermal_verdicts.csv`.

## What could not be asked

Sentinel-1A launched in April 2014 and the archive over this fjord is thin before
2016, so **seven of the 36 days cannot be reached at all**: four in 2013 and
three in 2014. Those are seven of the nine EARLY ones. What is left is 2 early
days against 27 late. This part can therefore characterise the late period, where
the failure concentrates and where it moves the decline, and it cannot test the
early-late asymmetry itself. That asymmetry rests on the thermal count.

Sentinel-1B failed in December 2021 and the revisit halved, which is why 2023 and
2024 hold six acquisitions each where 2026 holds 33, and why the reference window
had to be widened to five days either side. That widening applies to references
only: midwinter fast ice and post-break-up open water are stable over days, while
a suspect day's state is the question.

## The discriminant that was announced, and did not work

The prediction written into the script before the run was that SPREAD would
separate a closed sheet from a broken field: one surface is narrow, floes and
leads together are wide. Measured on the two classes whose answer is known, it
separates them at an AUC of **0.81**, against **0.92** for the plain median and
**0.96** for the p95.

The likely reason is grounded icebergs. This fjord carries them all year and they
are extremely bright in C band, so the spread over the fjord is wide whatever the
sea ice is doing and cannot be read as a count of surfaces. The classification
below therefore uses the level, which is what measurably separates known ice from
known water here, and the spread is printed beside it as description rather than
evidence. The prediction was wrong; the instrument test is why it is not in the
result.

## What radar says

Each day is placed between its own season's fast ice (1.00) and its own season's
open water (0.00), same relative orbit wherever one exists. 27 of the 29
reachable days could be placed.

| verdict | total | early | late |
|---|---|---|---|
| reads like its own fast ice | 8 | 1 | 7 |
| between the two | 13 | 0 | 13 |
| reads like open water | 6 | 1 | 5 |

**Median position 0.43, mean 0.38, against a median of 0.17 that the optical
chain reported on the same days.**

Both extremes are refused. Only 8 of 27 look like the closed fast ice that the
most generous repair assumed for all of them, so **the 0.8 percent scenario in
part three is refuted**. Only 6 look like open water, so the chain was not simply
right either. The fjord on the median contradicted day held more ice than the
chain reported and much less than a closed sheet.

## What that costs the decline

| | early | late | decline |
|---|---|---|---|
| as measured | 0.6363 | 0.5052 | 20.6 % |
| every contradicted day handed a frozen fjord | 0.7200 | 0.7141 | 0.8 % |
| **radar-placed days set to their radar position** | **0.6376** | **0.5678** | **10.9 %** |
| and the unreachable days set to the median position | 0.6538 | 0.5759 | 11.9 % |
| only the 8 days that read like fast ice set to 1.00 | 0.6421 | 0.5344 | 16.8 % |

**A radar-informed correction roughly halves the measured Landsat decline, from
about 21 percent to about 11.** That is the number this chain of measurements
produces, and it is the first estimate in this project that is neither the raw
reading nor a bound.

## What part four does not establish

- **A radar position is not an ice fraction.** Backscatter in decibels does not
  mix linearly across a partly frozen fjord, so placing a day between two
  endpoints of its own season is an interpolation and a proxy. It is a better
  proxy than either extreme and it is not a measurement of area.
- **Only contradicted days are corrected.** If the same bias operates more weakly
  on days that passed the thermal test, this correction is incomplete and in the
  same direction.
- **The correction is measured on Landsat, and the story publishes Sentinel-2.**
  Part three showed the two agree on these days to r = +0.986, so the failure is
  in both, but the size of the correction has not been recomputed on the
  published series and should not be assumed to transfer unchanged.
- **Two early days cannot carry a period.** Every statement here about the early
  side of the split is weak, by construction, because radar could not look.
- **This is not yet a correction of the published figure.** Everything here is
  measured on the Landsat series. Carrying it onto the Sentinel-2 series the
  story publishes is done in
  [limitations.md](limitations.md#and-carried-onto-the-published-series-it-costs-three-points),
  where the same correction costs three points rather than half, because
  Sentinel-2 holds three to five times as many usable days a season and its
  published figure is smoothed and gap filled.
