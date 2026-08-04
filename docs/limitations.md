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

| Scene | ESA `eo:cloud_cover` (tile) | Model, over the AOI |
|---|---|---|
| 2023-08-18 | 48.4 % | 22.6 % |
| 2023-04-20 | 9.6 % | 0.0 % |
| 2023-02-25 | 32.9 % | 56.0 % |
| 2019-08-08 | 22.4 % | 50.4 % |

> **Provenance warning.** These four rows come from interactive scene runs during
> the cloud investigation and were never written to an artefact. They cannot be
> reproduced from the published archive, which reports 0.0, 0.0, 22.7 and 0.0
> percent model cloud for the same dates, nor from any run output on disk. They
> are kept because the qualitative finding they illustrate is independently
> supported below, but a number that no stored result can reproduce does not
> belong in a limitations page. Regenerating them from the reprocessed archive is
> part of that run.

On 2023-08-18 the fjord is visibly overcast in the true-colour composite while
the model reports 22.6 percent. The thin-cloud and shadow classes almost never
win the argmax (0.2 and 0.0 percent on that scene), so the four-class head
behaves as a two-class one.

**An earlier version of this page argued the consequence from a number that does
not support it, and the correction matters more than the original claim.** It
reported that ice fraction correlates with detected cloud at r = -0.42 across
all 1552 archived scenes. That correlation is real (recomputed: -0.419) and it
is also **mechanically forced**. It was measured against the whole-grid
denominator, where a cell classified as cloud can never also be counted as ice,
so more cloud must produce less ice by construction, and a perfect cloud mask
would produce the same negative sign. On the clear-sky denominator, which is the
one this project actually publishes, the same correlation is **+0.058** over
1295 scenes, or -0.097 over the 1120 that clear the 30 percent visibility gate.
The number proved nothing, and it was the first thing a reviewer would check.

**What the archive does show, on the clear-sky denominator.** February and March,
277 scenes, a fjord that is frozen with near certainty:

| Detected cloud | n | Ice / whole grid | Ice / clear sky |
|---|---|---|---|
| 0.00 to 0.05 | 176 | 0.897 | 0.999 |
| 0.05 to 0.25 | 33 | 0.491 | 0.613 |
| 0.25 to 0.50 | 18 | 0.376 | 0.655 |
| 0.50 to 0.75 | 15 | 0.248 | 0.713 |

Across these four bands the whole-grid column falls by a factor of 3.6 while the
clear-sky column stays high. The band above 0.75 cloud is left out on purpose:
there the whole-grid figure reaches 0.017, a fiftyfold collapse, but the
clear-sky figure is meaningless because `cloud_pct + land_pct + nodata_pct`
exceeds one in those rows and the denominator goes negative. That is itself a
defect of the archive and is listed below. So the headline cloud artefact is, to
a first approximation, **the denominator**, and switching denominators is the fix
rather than a mitigation.

**What survives is smaller, sharper and not a cloud problem.** Of the 233
February and March scenes that pass the visibility gate, **26 report under 0.15
ice on the clear-sky denominator with a median detected cloud of 0.055 and 83
percent of the grid clear**. Cloud does not explain those. Something else does,
most plausibly the brightness gate at low winter sun, and the archive cannot
say which, because `sun_elev` was never written to it (all 1552 rows carry 19 of
the 22 header columns; `sun_elev`, `sun_azim` and `edge_gap` are empty).

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

## The record is nine seasons, and that is short

Spring means (day of year 60 to 151) per season, from the published archive:

```
2017 0.719   2018 0.790   2019 0.536   2020 0.624
2021 0.269   2022 0.629   2023 0.403   2024 0.552   2025 0.396
```

- Early (2017 to 2020) mean 0.667, late (2021 to 2025) mean 0.450.
- Exact permutation test over all 126 splits: **p = 0.032** with the whole-grid
  denominator, **p = 0.056** with the clear-sky one.
- Mann-Kendall for a monotone trend: **p = 0.076** and **p = 0.348**.

So the early-to-late difference is at best marginal once the cloud artefact is
removed, and a monotone trend is not detectable at all. The interannual spread
(standard deviation 0.111 early, 0.142 late) is nearly as large as the difference
between the period means (0.217), and 2022 sits above both 2019 and 2020.

**The direction is consistent. The certainty is not there, and nine winters is
why.**

## The result depends on two analysis choices

Neither is wrong, but both are choices, and the published combination sits near
the favourable end of the defensible range.

| Period boundary | Loss | p | | Season window (doy) | Loss | p |
|---|---|---|---|---|---|---|
| from 2019 | 35.5 % | 0.028 | | 45 to 181 | 30.4 % | 0.032 |
| **from 2021** | **32.6 %** | **0.040** | | **60 to 151** | **32.6 %** | **0.040** |
| from 2022 | 15.7 % | 0.214 | | 60 to 120 | 26.6 % | 0.008 |
| from 2024 | 16.4 % | 0.278 | | 100 to 151 | 35.8 % | 0.056 |

The 2021 boundary has a substantive justification, but the range across
defensible choices runs from 16 to 36 percent and that belongs on the page.

## Sampling is uneven, and 2017 is thin

Measured days inside the analysed window: 2017 has **39**, the other seasons 81
to 107. Bootstrapping the measured days of each season, 2000 draws, gives the
sampling standard error of each season mean:

```
2017  0.590 +- 0.064   (39 days)      2022  0.512 +- 0.037  (107)
2018  0.616 +- 0.044   (81)           2023  0.326 +- 0.036   (93)
2019  0.426 +- 0.038  (102)           2024  0.449 +- 0.036  (107)
2020  0.516 +- 0.038  (106)           2025  0.324 +- 0.037  (106)
2021  0.219 +- 0.029  (106)
```

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
