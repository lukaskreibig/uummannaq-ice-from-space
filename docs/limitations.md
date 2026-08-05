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

| Detected cloud | n | Ice / whole grid | Ice / clear sky |
|---|---|---|---|
| 0.00 to 0.05 | 144 | 0.890 | 0.976 |
| 0.05 to 0.25 | 21 | 0.687 | 0.918 |
| 0.25 to 0.50 | 32 | 0.346 | 0.590 |
| 0.50 to 0.75 | 33 | 0.179 | 0.616 |

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
its target changed: the 26 clear-sky anomalies are the sharper question, because
they are the ones no denominator explains. Over Greenland the mission flies HH
and HV rather than VV and VH, so no threshold calibrated on VV transfers here.

*Mitigations in place:* the clear-sky denominator removes the mechanical part of
the bias, which the table above shows to be most of it, and scenes below 30
percent visibility are marked unusable. Neither helps with cloud the model failed
to detect at all, and neither explains the 26 clear-sky anomalies.

## The record is ten seasons, and that is short

Spring means (day of year 60 to 151) per season, from the reprocessed archive:

```
2017 0.877   2018 0.957   2019 0.725   2020 0.787   2021 0.466
2022 0.941   2023 0.480   2024 0.770   2025 0.456   2026 0.608
```

- Early (2017 to 2020) mean 0.836, late (2021 to 2026) mean 0.620, a decline of
  **25.9 percent**.
- Exact permutation test over all 210 splits: **p = 0.090**.
- Mann-Kendall for a monotone trend: **p = 0.107**.

So the early-to-late difference does not reach significance at any conventional
level, and a monotone trend is not detectable at all. The interannual spread
(standard deviation 0.102 early, 0.198 late) is of the same order as the
difference between the period means (0.216), and 2022 at 0.941 sits above three
of the four early seasons.

**The direction is consistent. The certainty is not there, and ten winters is
why.**

## The result depends on two analysis choices

Neither is wrong, but both are choices, and the published combination sits near
the favourable end of the defensible range.

| Period boundary | Loss | p | | Season window (doy) | Loss | p |
|---|---|---|---|---|---|---|
| from 2019 | 28.7 % | 0.111 | | 45 to 180 | 29.1 % | 0.062 |
| **from 2021** | **25.9 %** | **0.090** | | **60 to 151** | **25.9 %** | **0.090** |
| from 2022 | 14.6 % | 0.389 | | 60 to 120 | 21.5 % | 0.029 |
| from 2024 | 18.2 % | 0.333 | | 100 to 151 | 28.4 % | 0.200 |

The 2021 boundary has a substantive justification, but the range across
defensible choices runs from 15 to 29 percent and that belongs on the page.
Across the eleven combinations tested, p runs from 0.03 to 0.39 and exactly one
falls below 0.05, which out of eleven is what chance alone produces.

## Sampling is uneven, and 2017 is thin

Measured days inside the analysed window: 2017 has **31**, the other seasons 53
to 75. Bootstrapping the measured days of each season, 2000 draws, gives the
sampling standard error of each season mean:

```
2017  0.703 +- 0.075   (31 days)      2022  0.742 +- 0.043   (75)
2018  0.851 +- 0.041   (60)           2023  0.496 +- 0.052   (53)
2019  0.580 +- 0.057   (64)           2024  0.668 +- 0.045   (69)
2020  0.714 +- 0.048   (72)           2025  0.381 +- 0.049   (66)
2021  0.294 +- 0.047   (65)           2026  0.443 +- 0.055   (66)
```

The mean quoted here is the mean of the measured days, which is what the
bootstrap resampled. It is not the same number as the gap-filled seasonal mean
the charts plot, and the API returns both for exactly that reason: pairing an
interval with the wrong one of the two put the 2018 point below its own lower
bound.

The API reports these per season so charts can draw a band rather than a point.

**And the useful conclusion is what they are dwarfed by.** A typical season's
sampling error is 0.040. The spread between seasons is 0.111 within the early
period and 0.142 within the late one, three to four times larger. So the limit on
what this record can say is **not** how many scenes each season got. It is that
there are nine seasons. More imagery would not help; more years would.

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
