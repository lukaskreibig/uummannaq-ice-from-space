# What a second optical instrument sees on the same day

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
