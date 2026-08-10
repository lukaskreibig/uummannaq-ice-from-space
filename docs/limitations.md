# Limitations

What this method cannot do, quantified where it can be. Written to be read by
someone looking for the weak points, because that is the useful way to read it.

Ordered by how much they could change a conclusion.

---

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

## The result depends on two analysis choices

Neither is wrong, but both are choices, and both belong on the page.

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

## Melt ponds bias break-up early

Melt water sits on top of ice and reads as open water in the optical bands, so
the measured break-up is earlier than the physical one. The bias points the same
way as the headline result and grows in warm springs, which is the uncomfortable
direction.

It is **not quantified**. SAR shares this failure mode for wet surfaces, so a
radar cross-check bounds it only partially.

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

## Smoothing shifts break-up earlier

With a robust definition (7 consecutive days below the threshold), smoothing
dates break-up **6 days earlier on average**, up to 26 days in 2023, and always
earlier, never later.

## The seasonal window is hard-coded

Day of year 45 to 180, chosen for Uummannaq's solar geometry. It is not derived
from latitude, so the pipeline is not yet portable to another site without
revisiting it.

## What is not validated at all

- **No comparison against an independent product.** No SAR, no in-situ, no other
  optical product. The series shows a direction; it is not a calibrated
  measurement.
- **No uncertainty is propagated** from the per-scene classification to the
  seasonal means beyond the sampling term above.
- **The 40 m analysis grid** resolves nothing smaller. Leads, cracks and the ice
  edge itself are sub-grid features.
- **Acquisition time varies** between 15:01 and 16:58 UTC. At 70 degrees north
  two hours of sun movement is not nothing, though the median is stable.
