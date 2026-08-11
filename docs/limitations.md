# Limitations

What this method cannot do, quantified where it can be. Written to be read by
someone looking for the weak points, because that is the useful way to read it.

Ordered by how much they could change a conclusion.

---

## The short version

The published result is a **22.6 percent** decline in spring ice fraction between
2017 to 2020 and 2021 to 2026, at an exact permutation p of **0.119**.

Everything below is an attempt to break that number. Where an attempt could be
turned into a measurement, this is what it cost:

| What was tested | How far it moves the result | Where |
|---|---|---|
| Ten seasons is a short record | p never falls below 0.10, in any of ten combinations of period boundary and window | [below](#the-record-is-ten-seasons-and-that-is-short) |
| Period boundary and season window | decline runs 13 to 26 percent across defensible choices | [below](#the-result-depends-on-three-analysis-choices) |
| Where the brightness gate sits | 19.4 to 23.0 percent across a gate range wider than anyone would defend; **20.3 percent** if the gate tracks each season's own ice brightness | [below](#and-the-third-choice-where-the-brightness-gate-sits) |
| The twelve wet April scenes | 22.6 to **21.6 percent** if every one of them is handed back a frozen fjord | [below](#melt-ponds-bias-break-up-early-and-now-there-is-a-number) |
| Accuracy on days whose answer is known | median scene wrong by 0.0025 on open water and 0.0019 on fast ice, in both directions | [below](#melt-ponds-bias-break-up-early-and-now-there-is-a-number) |
| A second optical instrument, same day | Landsat agrees to an RMSE of **0.026** over 23 days whose answer was not in doubt | [landsat-crosscheck.md](landsat-crosscheck.md) |
| Radar on the contested days | Sentinel-1 puts them within about **2 dB** of their own winter fast ice | [sar-validation.md](sar-validation.md) |
| Can a sub-pixel fraction replace the class | no, the pure ice spectrum moves by a factor of **1.7** across days that are all unambiguously frozen | [unmixing-feasibility.md](unmixing-feasibility.md) |
| Cloud detection | 28 of 219 winter scenes still read anomalously low under a sky the pipeline calls clear, and Landsat Level 1 confirms five of them to an RMSE of **0.0076** | [below](#cloud-detection-is-unreliable-and-the-denominator-mattered-more) |
| The resolution the cloud mask is computed at | up to 0.209 of ice fraction on one scene, **0.2 points** on the decline | [below](#the-resolution-the-mask-is-computed-at-is-worth-more-than-the-grid-itself) |
| The 40 m analysis grid | 0.0015 across grids from 10 to 80 m | [below](#the-resolution-the-mask-is-computed-at-is-worth-more-than-the-grid-itself) |
| Uneven sampling | a season's sampling error is 0.054, against a between-season spread of 0.104 to 0.170 | [below](#sampling-is-uneven-and-2017-is-thin) |
| **How break-up is defined** | direction unanimous across 30 definitions, but the shift spans **-0.7 to -53 days** against a published -10.2 | [below](#smoothing-shifts-break-up-earlier-and-the-definition-shifts-it-much-more) |

**Three readings of that table, and all three belong here.** Separate the two
kinds of entry first, because they are not the same thing. Correcting a bias
that was measured costs the headline at most **2.3 points**, the largest being
the gate that tracks each season's ice, and the significance does not move under
any of them. Redefining the analysis rather than correcting a bias moves it much
further: the period boundary alone spans 13 to 26 percent, and that range is a
choice about what question to ask, not an error to be fixed. And nothing on the
table rescues the significance, because with ten seasons the test has too little
power to reach any conventional threshold, which is the honest ceiling on what
this record can settle.

The one bias that is not symmetric is melt water read as open water. It pushes
the ice fraction **down** on wet spring days, it concentrates in the seasons that
carry the decline, and it therefore points the same way as the published result.
Its size is bounded above.

---

## The record is ten seasons, and that is short

Spring means (day of year 53 to 180) per season, from the reprocessed archive:

```
2017 0.738   2018 0.756   2019 0.611   2020 0.631   2021 0.431
2022 0.766   2023 0.440   2024 0.667   2025 0.389   2026 0.484
```

- Early (2017 to 2020) mean 0.684, late (2021 to 2026) mean 0.529, a decline of
  **22.6 percent**.
- Exact permutation test over all 210 splits: **p = 0.119**.
- Mann-Kendall for a monotone trend: **p = 0.210**.

The permutation test is worth stating concretely, because the number is easier
to trust than the letter. It walks all 210 ways of cutting the ten seasons into
a group of four and a group of six and asks how often chance alone opens a gap
at least as wide as the real one. The real, chronological split gives 0.155.
**25 of the 210 manage it too**, which is where the 0.119 comes from: about one
arbitrary split of these ten winters in eight looks like ours. The widest gap of
all, 0.259, belongs to 2021, 2023, 2025 and 2026 taken together, which is no
chronology at all.

So the early-to-late difference does not reach significance at any conventional
level, and a monotone trend is not detectable at all. The interannual spread
(standard deviation 0.073 early, 0.151 late) is as large as the difference
between the period means (0.155), and 2022 at 0.766 sits above all four early
seasons.

A p above 0.10 is not evidence against the decline, and should not be read as
one. With ten values the test has very little power, so a real decline of this
size would often land above 0.10 as well. Absence of proof is not proof of
absence; it is what a ten-year record can and cannot settle.

**The direction is consistent. The certainty is not there, and ten winters is
why.**

## The result depends on three analysis choices

None is wrong, but all three are choices, and all three belong on the page.

| Period boundary | Loss | p | | Season window (doy) | Loss | p |
|---|---|---|---|---|---|---|
| from 2019 | 26.0 % | 0.133 | | 45 to 180 | 22.6 % | 0.119 |
| **from 2021** | **22.6 %** | **0.119** | | **53 to 180** | **22.6 %** | **0.119** |
| from 2022 | 13.3 % | 0.413 | | 53 to 151 | 23.2 % | 0.100 |
| from 2024 | 17.8 % | 0.292 | | 74 to 180 | 18.2 % | 0.176 |

The window row is worth reading twice: **day 45 and day 53 now give the same
answer to three digits.** They did not before. The gate that asks how much of
the fjord a scene actually classified, rather than how much of it the scene
could see, rejects the February scenes the wider window used to admit, so the
window start stopped carrying weight of its own. A choice that no longer changes
the result is no longer a choice worth defending.

The 2021 boundary has a substantive justification, but the range across
defensible choices runs from 13 to 26 percent and that belongs on the page.
Across the ten combinations tested, p runs from 0.10 to 0.41. **Not one falls
below 0.05, and not one below 0.10.** An earlier version of this page reported
one below 0.05 out of eleven and noted that one in eleven is what chance alone
produces; with the denominator and the gate corrected there is no longer even
that one.

### And the third choice: where the brightness gate sits

[unmixing-feasibility.md](unmixing-feasibility.md) showed that the ice this
pipeline gates is 34 percent darker in 2023 than the ten-season median, so a
fixed cut at near infrared 0.17 does not sit in the same place relative to the
ice from one season to the next. That makes the gate an analysis choice like the
other two. Reproduce with:

```
python3 scripts/gate_sensitivity.py
```

Eighty scenes, eight per season, spread evenly across the season window rather
than picked for coverage, each loaded once and classified at five gates. At the
published gate the run reproduces the archive's own ice fractions **exactly**,
to six decimals, which is what makes the other four columns readable.

**The mechanism is confirmed.** How far a season moves when the gate moves
correlates with how bright its ice is at **r = -0.675**. The two darkest
seasons, 2023 and 2025, span 0.140 and 0.124 of ice fraction across the sweep;
the two brightest, 2018 and 2022, span 0.016 and 0.017. 2017 is the exception,
bright ice and a span of 0.114, and it is also the thinnest season in the record.

**The headline barely moves.** Applying the measured per-season shifts to the
published season means:

| NIR gate | decline | permutation p | false ice | closed cover |
|---|---|---|---|---|
| 0.09 | 19.4 % | 0.105 | 0.0081 | 0.9983 |
| 0.13 | 21.9 % | 0.105 | 0.0051 | 0.9951 |
| **0.17 (published)** | **22.6 %** | **0.119** | **0.0036** | **0.9926** |
| 0.21 | 22.8 % | 0.124 | 0.0027 | 0.9920 |
| 0.25 | 23.0 % | 0.129 | 0.0020 | 0.9919 |

The last two columns are the price of each gate on days whose answer is not in
doubt: false ice over 9 certainly open days after 20 June, and how much of a
closed cover survives over 29 certainly frozen days before mid April.

Three things follow. The published gate sits just past a knee, not on a cliff:
everything above it changes the decline by at most 0.4 points. Below it the
decline falls, to 19.4 percent at a gate of 0.09, which is the only value in the
sweep that moves the answer materially. And that value is not free, because it
roughly doubles the false ice, though both rates stay under one percent, so
these anchors do not sharply prefer 0.17 over 0.13. The primary justification
for 0.17 therefore stays with `derive_thresholds.py`, which works from eighteen
scenes whose labels were confirmed one by one.

The whole gate range, 19.4 to 23.0 percent, sits **inside** the 13 to 26 percent
this page already reports for the other two choices, so it widens nothing.

**And the counterfactual that actually matters.** Moving the gate by the same
amount in every season is not the right question. If the ice of 2023 is a third
darker, a fixed cut sits higher relative to *that* season's surface and lower
relative to a bright one, so the correction is to move the cut only where the
ice moved. Sweeping every season together even understates it, because it lifts
the bright seasons too.

Putting the gate at 0.17 times each season's own measured brightness, which
holds it in the same place relative to the ice it is cutting:

| Season | brightness | its gate | ice, fixed | ice, tracking | difference |
|---|---|---|---|---|---|
| 2017 | 1.02 | 0.173 | 0.723 | 0.720 | -0.002 |
| 2018 | 1.00 | 0.170 | 0.738 | 0.738 | +0.000 |
| 2019 | 1.06 | 0.180 | 0.515 | 0.511 | -0.004 |
| 2020 | 0.98 | 0.166 | 0.686 | 0.687 | +0.001 |
| 2021 | 0.96 | 0.164 | 0.343 | 0.345 | +0.002 |
| 2022 | 1.06 | 0.181 | 0.734 | 0.734 | -0.001 |
| **2023** | **0.66** | **0.112** | **0.373** | **0.437** | **+0.064** |
| 2024 | 1.02 | 0.174 | 0.712 | 0.711 | -0.001 |
| 2025 | 0.90 | 0.153 | 0.363 | 0.379 | +0.016 |
| 2026 | 0.89 | 0.151 | 0.431 | 0.441 | +0.010 |

| | decline | permutation p |
|---|---|---|
| fixed at 0.17 | 22.6 % | 0.119 |
| tracking the ice | **20.3 %** | **0.119** |

**That is the bound the brightness finding was asking for.** Correcting the gate
for the darkness of each season's own ice costs the headline 2.3 points and
moves the significance not at all. One season does nearly all of it: 2023 gains
0.064 of ice fraction, 2025 and 2026 gain 0.016 and 0.010, and the remaining
seven move by 0.004 or less.

The proportional scaling is an assumption, and the plainest one available: a
surface uniformly darker by a third crosses a cut set a third lower at the same
place. It is not derived from anything, and a real implementation would derive
the gate per scene rather than per season.

Three limits on all of the above. Only 49 of the 80 sampled scenes move at all
when the gate moves; the rest are a frozen fjord or an open one, where every
cell sits far from the cut. That is a property of this fjord and the published
daily series is composed the same way, but it means a season's row can rest on
as few as two informative scenes. The decline columns are estimates: the
measured shifts are applied to the published means rather than the series being
rebuilt, because an exact answer means reclassifying all 1103 scenes five times.
And the tracking gate reads each season's curve by interpolating between the
five measured points.

## Melt ponds bias break-up early, and now there is a number

Melt water sits on top of ice and reads as open water in the optical bands, so
the measured break-up is earlier than the physical one. The bias points the same
way as the headline result and grows in warm springs, which is the uncomfortable
direction. SAR shares this failure mode for wet surfaces, so a radar cross-check
bounds it only partially.

This page used to say the bias was not quantified. It is now, and the way it was
measured cost nothing, because the archive had been carrying the answer at both
ends of the season and the published window threw it away.

**The two anchors.** This fjord is open in July with near certainty: the latest
break-up in the record is 8 June 2024, and the July median clear-sky ice
fraction is 0.002. So on a July scene the true ice fraction is zero, and
whatever the pipeline reports instead is its false ice rate. Symmetrically, the
earliest break-up in the record is 30 April 2021, day 120, so a window from
1 to 20 April sits at least ten days before this fjord has ever opened in any of
the ten seasons. There the true fraction is one, and the shortfall is the false
water rate. Neither anchor needs a label, a second instrument or a field season.
Reproduce with `python3 scripts/season_end_calibration.py`.

| Direction | Basis | Median | 95 % CI | Worst scene |
|---|---|---|---|---|
| False ice on open water | 51 July scenes, 10 seasons | 0.0025 | 0.0020 to 0.0032 | 0.0118 |
| False water on fast ice | 102 April scenes, 10 seasons | 0.0019 | 0.0010 to 0.0027 | 0.4793 |

**Read the medians together and the tails separately.** The median scene is
accurate to about two parts in a thousand in both directions, which is better
than this page previously implied. The tails are not symmetric at all. Not one
July scene reports above 0.05 ice, so open water is essentially never called
ice. But 12 of the 102 April scenes fall below 0.90, down to 0.52, on days when
this fjord has never once been open.

The mechanism follows from the accounting. A cell that fails the brightness gate
leaves the denominator rather than becoming water, so a scene cannot reach a low
ice fraction that way. It can only get there by having cells pass NDWI. On a
fjord that is certainly frozen, that is melt water or wet snow being read as
open water. This is the melt-pond bias, caught in the act, on days where the
right answer is known.

**They are not a slow degradation, they are a switch.** An April scene either
reads about 0.999 or it drops to around 0.5, with little in between, and the
cells do not pass through the light ice class on the way: on 12 April 2023 the
scene holds 61,170 solid cells, 234 light and 56,520 water. That is 121 km2 of a
253 km2 fjord called open water in one step. A clean April scene for comparison,
20 April 2018, has 157,730 solid cells and 103 water.

**Ten of the twelve cannot be the fjord opening early.** Measured against each
season's own break-up rather than against the record's earliest, the picture
splits. The two 2021 scenes sit 10 and 11 days before that season's break-up on
30 April, which is close enough that a low reading might be the real thing. The
other ten sit 24 to 41 days before theirs: 2023 and 2025 both broke up on 14 May,
and 2020 on 26 May. Three to six weeks before break-up, half a fjord of open
water is not an early thaw.

**And the part that is uncomfortable.** The 12 outliers are not spread evenly
across the record. Five fall in 2025, four in 2023, two in 2021, one in 2020,
and none at all in the remaining six seasons. Dealt out at random across the
same scenes, holding each season's count fixed, that concentration or worse
comes up with a permutation p of 0.0018.

2021, 2023 and 2025 have spring means of 0.431, 0.440 and 0.389, the three
lowest in the record, and all three sit in the late period. So the failure mode
concentrates in exactly the seasons that carry the measured decline.

Two readings fit, and this measurement cannot separate them. Either the
classifier reads wet ice as water more often in those seasons, in which case
part of the measured decline is a reading error rather than ice loss. Or those
springs genuinely were wetter and their April ice genuinely was closer to
melting, in which case the low readings are signal. Wet April ice is itself a
symptom of a warmer spring, so the second reading is not a rescue: it says the
series is measuring something real, but that the thing it measures is
"how much of the fjord looks like open water from above" rather than
"how much of the fjord is covered by ice".

**The brightness measurement introduced in the section above speaks to that
fork, and it leans toward the second reading.**
[unmixing-feasibility.md](unmixing-feasibility.md) measured the spectrum of the
ice itself on 17 days that the archive scores at 0.99 ice or better, two per
season across all ten seasons. The 2023 days are **34 percent
darker** than the ten-season median, 2025 and 2026 are 10 and 11 percent darker,
and every other season sits within 6 points of it. That difference is not the
sun, which explains 7 percent of the variance, and it is not the January 2022
radiometric offset, since post-offset seasons span the whole range: 2022 reads
1.06 of the median and 2023 reads 0.66. On days when this fjord was
unambiguously frozen, the ice of 2023 really did look different.

That also names the mechanism for the first reading. The brightness gate is a
pair of fixed cuts, green above 0.10 and near infrared above 0.17, applied to a
surface whose brightness moves by a third between seasons. The two 2023 anchor
days read NIR 0.47 and 0.52 against a ten-season median of 0.76, so more of the
distribution sits near the gate and more of its lower tail crosses. The two
readings are therefore not alternatives. The springs were darker, and a fixed
gate turns a darker spring into a larger reading error, in the same direction.

**So how much of the headline rests on those twelve days?** The question has an
answer, and it is the answer a reader will ask for first. Reproduce with:

```
python3 scripts/wet_day_sensitivity.py
```

The same raw archive is pushed three times through the story's own cleaning
implementation, `clean_series` in `refresh_fjord_season.py`, rather than through
a second copy of it. Rebuilt untouched it returns the published numbers to four
decimals, which is what makes the other two rows comparable.

| Variant | early | late | decline | permutation p | Mann-Kendall p |
|---|---|---|---|---|---|
| **published** | 0.6839 | 0.5296 | **22.6 %** | 0.119 | 0.210 |
| suspect scenes dropped | 0.6843 | 0.5352 | 21.8 % | 0.119 | 0.210 |
| suspect scenes forced fully frozen | 0.6844 | 0.5365 | **21.6 %** | 0.119 | 0.210 |

The third row is the bound. Hand every one of the twelve back a completely
frozen fjord, which is the most generous assumption available and certainly
wrong in the generous direction, and the decline goes from 22.6 to 21.6 percent.
**96 percent of it survives**, and neither p moves at all. The season means move
by 0.009 in 2021, 0.016 in 2023, 0.018 in 2025 and 0.002 in 2020, against a gap
between the periods of 0.154.

**What that does not bound.** Only the days that crossed 0.90 are tested. The
brightness shift behind them runs through a whole season, not through twelve
days, so a milder version of the same error can sit on every day of 2023 and
2025 without any single one falling far enough to be caught here. That version
has no anchor: outside the April window and before July there is no day in this
fjord whose answer is certain, so there is nothing to measure it against. The
table bounds the identified days, not the mechanism.

**A second optical instrument has since been asked, and it answers half of
this.** On four of these days Landsat 8 or 9 passed over the fjord within about
two hours, and running the same thresholds on its surface reflectance gives
0.3756, 0.4158, 0.5876 and 0.6498 against Sentinel-2's 0.5207, 0.5952, 0.7128
and 0.8305. Four for four in the same direction, at five to seven times the
0.026 agreement noise measured on days whose answer was not in doubt. So the
surface really did read as water to two instruments with independent
atmospheric corrections and independent cloud masks, and the concentration in
2023 and 2025 is not a Sentinel-2 defect.

**And radar has since answered the half that optics cannot.** On those same
April days Sentinel-1 gamma0 HH over the fjord sits within about 2 dB of that
season's own February and March fast ice, and 4.5 to 6.2 dB above the record's
open water anchor. The ice was still there, under a wet surface, and the optical
chain read the meltwater as open water.

So the melt-pond bias is no longer a footnote in any sense. It has a magnitude
from the season-end anchors, a confirmation from a second optical instrument, and
now a third instrument saying the ice underneath was physically present. It also
means the ice fraction on wet spring days is biased LOW, in the same direction as
the headline, which is the uncomfortable direction and is stated here rather than
buried.

Three independent radar looks cover the four days, since two of them share an
acquisition, and one of the four sits 2.12 dB below its winter ice, which is the
direction wet snow pushes and therefore the weakest of the set. See
[landsat-crosscheck.md](landsat-crosscheck.md) and
[sar-validation.md](sar-validation.md#the-wet-april-days-asked-separately-and-answered).

## Cloud detection is unreliable, and the denominator mattered more

The CloudSEN12 checkpoint does not reliably find cloud over this fjord, and the
error runs in **both** directions, so it cannot be calibrated away with an offset.
That much holds. What does not hold is the size this page previously gave it:
measured properly, most of the apparent cloud artefact was the whole-grid
denominator rather than the cloud mask, and the correction is worked through
below.

Two scenes from the reprocessed archive, where ESA's tile-level figure and the
model's figure over this AOI disagree in opposite directions:

| Scene | ESA `eo:cloud_cover` (tile) | Model, over the AOI |
|---|---|---|
| 2023-04-20 | 13.4 % | 0.0 % |
| 2023-02-25 | 25.7 % | 51.0 % |

An earlier version of this page carried four rows including two August scenes,
taken from interactive runs during the cloud investigation and never written to
an artefact. They could not be reproduced from any stored result, which is not a
defensible state for a limitations page, so they are replaced by rows that come
straight out of `out/archive/summary.csv`. The two August scenes are gone rather
than corrected: the reprocess covers 1 February to 15 July and does not contain
them.

The disagreement runs both ways, so it cannot be calibrated away with an offset.
And the tile figure is not ground truth either: it covers 110 by 110 km while
this AOI is 15 by 18, so the two can legitimately differ. What the pair shows is
that neither can be trusted to arbitrate the other.

**An earlier version of this page argued the consequence from a number that does
not support it, and the correction matters more than the original claim.** It
reported that ice fraction correlates with detected cloud at r = -0.42, and read
that as proof of a cloud artefact. The correlation is real and it is also
**mechanically forced**. It was measured against the whole-grid denominator,
where a cell classified as cloud can never also be counted as ice, so more cloud
must produce less ice by construction, and a perfect cloud mask would produce
the same negative sign. On the reprocessed archive the whole-grid correlation is
**-0.609** across all 1103 scenes, and on the clear-sky denominator, over the
694 scenes that clear the visibility gate, it is **-0.157**. The number proved
nothing, and it was the first thing a reviewer would check.

**What the archive does show, on the clear-sky denominator.** February and March,
313 scenes, a fjord that is frozen with near certainty:

| Detected cloud | n | Median ice / whole grid | Median ice / clear sky |
|---|---|---|---|
| 0.00 to 0.05 | 144 | 0.890 | 0.976 |
| 0.05 to 0.25 | 21 | 0.687 | 0.918 |
| 0.25 to 0.50 | 32 | 0.346 | 0.590 |
| 0.50 to 0.75 | 33 | 0.179 | 0.616 |

Medians, not means. Taken as means the same bands read 0.750, 0.580, 0.308 and
0.180 on the left and 0.805, 0.750, 0.542 and 0.553 on the right, because a few
near zero scenes pull the average without moving the middle. The conclusion is
the same either way; the label is there so a reader recomputing it knows which.

The whole-grid column falls by a factor of five across those bands, the clear-sky
column by a third. So most of the apparent cloud artefact is **the denominator**,
and switching denominators is the fix rather than a mitigation.

**What survives is smaller, sharper and not a cloud problem.** Of the 219
February and March scenes that pass the visibility gate, **28 report under 0.15
ice on the clear-sky denominator**, and several of those sit under a sky the
pipeline itself calls clear: 2025-02-18 and 2025-03-01 at 0.000 detected cloud,
2026-03-06 at 0.026. Cloud does not explain those. The most plausible cause is
the brightness gate at low winter sun, and the reprocessed archive can finally
be asked, because `sun_elev` is now written to every row. It was empty in the
previous archive, where the data lines carried 19 of the 22 header columns.

These clear-sky anomalies, not the cloudy days, are the sharper target for the
SAR cross-check, because no change of denominator can explain them away.

**And another team met the same wall on this fjord and stepped around it.** Steiro
et al. (2021) mapped travel conditions on Uummannaq shorefast ice from 1985 to
2019 using Level-1 top-of-atmosphere imagery from Sentinel-2 and Landsat,
classifying snow, ice and water on near-infrared reflectance. Their section 2.3
reports that shadows from the low sun early in the season made snow and ice hard
to tell from water, and that they therefore excluded every February image from
the analysis. So the defect this page reports against itself is a known property
of optical remote sensing at this place, found independently, and the difference
is one of choice rather than of quality: they dropped February, this project
keeps it and states what it costs.

**A second instrument has since answered them, and the answer is that the
readings are correct.** Collection 2 Level 2 could never reach this regime,
because surface reflectance is not produced above a solar zenith of 76 degrees.
Level 1 has no such floor. On five February and early March days at sun
elevations of 6.11 to 12.72 degrees, including 2025-03-01 from the list above,
Landsat Level 1 and Sentinel-2 agree to a bias of **-0.0001** and an RMSE of
**0.0076**: 0.014 against 0.013, 0.013 against 0.014, 0.072 against 0.086, 0.279
against 0.274, 0.060 against 0.051. Two radiometers, two orbits, two cloud masks,
the same nearly open fjord. See
[landsat-crosscheck.md](landsat-crosscheck.md#part-two-the-same-question-at-low-sun-on-level-1).

**Two physical supplements were tried and rejected.** The cirrus band B10 adds
essentially nothing here. A brightness and whiteness test flags **27.8 percent of
April fast ice as cloud**, because ice and cloud are both white and bright. That
is the fundamental difficulty of optical cloud detection over ice, and no
threshold solves it.

**What would.** Sentinel-1 radar needs neither sun nor a clear sky, so it can be
asked directly whether the fjord was frozen on a given day. That is why the SAR
cross-check moved from optional to load-bearing, and after the correction above
its target changed: the 28 clear-sky anomalies are the sharper question, because
they are the ones no denominator explains. Over Greenland the mission flies HH
and HV rather than VV and VH, so no threshold calibrated on VV transfers here.

*Mitigations in place:* the clear-sky denominator removes the mechanical part of
the bias, which the table above shows to be most of it, and scenes below 30
percent visibility are marked unusable. Neither helps with cloud the model failed
to detect at all, and neither explains the 28 clear-sky anomalies.

### The resolution the mask is computed at is worth more than the grid itself

`compute_cloud_mask` receives the pooled 40 m cube, so UNetMobV2 sees a cloud at
a sixteenth of the pixel count it was trained on. That is an unexamined choice,
and it turns out to be the largest one behind the 40 m number. Reproduce with:

```
python3 scripts/grid_resolution.py
```

Thirty scenes, three per season, each classified at 10, 20, 40 and 80 m and each
masked twice, once on the pooled cube and once natively.

| Question | Answer |
|---|---|
| Does the grid move the result? | Mean ice fraction 0.5075 at 10 m, 0.5081 at 40 m, 0.5090 at 80 m. Across a factor of eight, **0.0015**. Worst single scene 0.012. |
| Does pooling before the indices cost anything? | The 10 m reference sits **0.0006** below the published value, worst scene 0.011. Only 2.5 percent of 40 m cells are mixed at 10 m. |
| Does the mask resolution matter? | Pooled mask 0.175 cloud, native mask 0.279. They agree on **87.4 percent** of cells, worst scene 58.6. On the reported ice fraction: mean -0.014, **worst 0.209**. |

So the two questions that motivated the test are answered and both are
negligible: **40 m is neither right nor wrong, it is free**, and the
non-linearity of NDSI and NDWI under pooling costs less than a thousandth. The
third question, which was not the one being asked, is worth up to 0.209 of ice
fraction on a single scene, more than the 0.154 between the period means.

**Which mask is closer to the truth is not decided, and looking at them refuses
an easy answer.** On 2018-04-26, a visibly cloudless white fjord, the pooled mask
already flags 17 percent and the native mask flags 57, including the island
itself. On 2025-02-24, a scene under real haze at a sun elevation of 10 degrees,
the native mask catches veil that the pooled mask leaves in. The direction
depends on the regime, which is the same both-ways error this section opens with,
now located in a specific choice rather than in the model.

Settling it needs labels on scenes, which this project does not have and which is
its own piece of work.

**And then the headline barely notices.** Applying the per-season shift to the
published means, the same way the gate sweep does:

| | decline | permutation p |
|---|---|---|
| pooled mask, as published | 22.6 % | 0.119 |
| native mask | **22.4 %** | 0.129 |

The largest per-scene lever in this pipeline is worth **0.2 points** on the
result. It scatters rather than aligning with the period split: the two seasons
that move most are 2020 at -0.070 and 2024 at -0.046, one in each period, and
they cancel. It is also not mainly a low-sun effect, -0.018 below 15 degrees
against -0.011 above, correlating with sun elevation at r = +0.14.

So the honest statement is in two parts, and the second one is the important one.
The pipeline inherits a resolution for its cloud mask that nobody chose
deliberately, and on a single scene that inheritance is worth up to 0.209 of ice
fraction. Across a season it averages out, which is what every other stress test
on this page has also found.

## Sampling is uneven, and 2017 is thin

Measured days inside the analysed window: 2017 has **24**, the other seasons 46
to 66. Bootstrapping the measured days of each season, 2000 draws, gives the
sampling standard error of each season mean:

```
2017  0.870 +- 0.054   (24 days)      2022  0.793 +- 0.044   (66)
2018  0.871 +- 0.040   (58)           2023  0.572 +- 0.056   (46)
2019  0.655 +- 0.059   (54)           2024  0.746 +- 0.047   (58)
2020  0.753 +- 0.046   (64)           2025  0.502 +- 0.057   (54)
2021  0.339 +- 0.054   (59)           2026  0.494 +- 0.060   (60)
```

Fewer days than before across the board, because the gate now rejects scenes
that saw the fjord but classified too little of it.

The mean quoted here is the mean of the measured days, which is what the
bootstrap resampled. It is not the same number as the gap-filled seasonal mean
the charts plot, and the API returns both for exactly that reason: pairing an
interval with the wrong one of the two put the 2018 point below its own lower
bound.

The API reports these per season so charts can draw a band rather than a point.

**And the useful conclusion is what they are dwarfed by.** A typical season's
sampling error is 0.054. The spread between seasons is 0.104 within the early
period and 0.170 within the late one, two to three times larger. So the limit on
what this record can say is **not** how many scenes each season got. It is that
there are ten seasons. More imagery would not help; more years would.

Note also that fewest days and widest interval are not the same season. 2017 has
by far the fewest at 24 and only the fourth widest interval, because the days it
did get agree with each other; 2026 has 60 days and the widest, because its
season runs through break-up. A bootstrap widens with a small n and with spread,
and the two do not have to point the same way.

## The solid/light split

`ndsi_solid` is set to 0.70. The threshold derivation over eighteen scenes
produced 0.83 on the grounds that the gated ice distribution starts at 0.824.
Measured directly against a completely frozen fjord (2023-04-20, tile 22WDD,
151,150 bright usable cells) that does not hold: NDSI runs 0.687 at the 1st
percentile to 0.755 at the 99th, median 0.720. At 0.83 not one cell of a frozen
fjord is solid ice.

This does not move the published number, since the series is `solid + light` and
every one of those cells clears `ndsi_light` either way. It decides only what the
two class names mean. **Until the disagreement is settled, the split should not
be presented as thick against thin ice.**

## Smoothing shifts break-up earlier, and the definition shifts it much more

With a robust definition (7 consecutive days below the threshold), smoothing
dates break-up **6 days earlier on average**, up to 26 days in 2023, and always
earlier, never later. That was measured on the absolute date. The number the
story actually leans on is the **shift between the two periods**, and that turns
out to depend far more on the definition than on the smoothing. Reproduce with:

```
../climate-dashboard/backend/.venv/bin/python scripts/breakup_definitions.py
```

Thirty definitions: two series, four ice-fraction thresholds, three persistence
lengths, three requirements on how many observations a persistence window must
contain, plus Walsh et al. (2022). The published baseline is taken from the
shipped `_freeze_and_breakup` rather than reimplemented.

**First, the shipped detector cannot simply be pointed at the observed series.**
It asks for seven CONSECUTIVE rows below the threshold, and with coverage between
19 and 50 percent and gaps up to 17 days, that never happens. Run that way it
returns nothing for all ten seasons. Any observed-day definition therefore has to
use calendar persistence, because a gap is missing data and not evidence of thaw.

**The direction is unanimous. The magnitude is not determined by the data.**

| | shift, late minus early |
|---|---|
| all 30 definitions | negative, without exception |
| the 19 that censor no season | **-0.7 to -53.0 days**, median -19.3 |
| **published** | **-10.2 days** |

The published value sits inside that range and on the conservative side of its
median. Like for like, at the same threshold of 0.15 and with no season censored,
switching from the smoothed series to observed days gives -19.3 days at seven
days of persistence and -5.3 at fourteen. So the smoothing is not what governs
the shift. The persistence length is.

**Walsh et al. (2022) is in the table and should not be used here, for a reason
worth stating.** Its threshold is the season's own winter mean minus two standard
deviations, floored at 0.15, and it gives a shift of -0.7 days with nothing
censored, which looks like a refutation. It is not. Measured on this record the
threshold it produces runs 0.925, 0.946, 0.961, 0.920 for 2017 to 2020 and then
0.315, 0.845, 0.203, 0.586, 0.150, 0.150. It collapses in exactly the seasons
that carry the signal, because this fjord's winter mean is itself falling from
0.98 to 0.57. A definition anchored on a stable winter baseline cannot be used
where the winter baseline is the thing that moved: it absorbs what it is meant to
measure.

**What this means for the published break-up dates.** They are one defensible
choice among many that all point the same way. The direction is robust across
every definition tried. The size is not: a reader who takes "ten days earlier" as
a measurement is taking more than the record supports, and the range belongs
beside it.

## The seasonal window is hard-coded

Day of year 45 to 180, chosen for Uummannaq's solar geometry. It is not derived
from latitude, so the pipeline is not yet portable to another site without
revisiting it.

## What is not validated at all

- **No comparison against an independent product.** The Sentinel-1 check bounds
  one error and does not calibrate the series, and the season-end anchors above
  are the pipeline checked against itself on days whose answer is known, which
  is a real error rate but not an independent one. No in-situ, no second optical
  product. The series shows a direction; it is not a calibrated measurement.
- **No uncertainty is propagated** from the per-scene classification to the
  seasonal means beyond the sampling term above.
- **The 40 m analysis grid** resolves nothing smaller. Leads, cracks and the ice
  edge itself are sub-grid features.
- **Acquisition time varies** between 15:01 and 16:58 UTC. At 70 degrees north
  two hours of sun movement is not nothing, though the median is stable.
