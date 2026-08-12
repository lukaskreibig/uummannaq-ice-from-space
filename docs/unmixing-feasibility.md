# Whether a fraction is recoverable at all

Every cross-check in this project has ended at the same wall. A 40 m cell gets
one label, so a cell that is half ice and half water falls to whichever side of
the threshold it lands on, and near a hard cut a small radiometric difference
moves a great deal of area.
[landsat-crosscheck.md](landsat-crosscheck.md#what-this-does-not-establish)
names it outright as the strongest argument in this project for reporting a
fraction instead of a class.

Spectral unmixing is the standard answer. Solve `r = E a` for the abundances
`a`, non-negative and summing to one, and report the ice share of the cell
rather than a verdict on it. This page is the test of whether that can work
here, run before any of it was built. Run on 2026-08-11 against the reprocessed
archive.

```
python3 scripts/endmember_separability.py
python3 scripts/ice_endmember_stability.py
```

Both runs are committed, as `archive/reprocessed_2026/endmember_spectra.csv` and
`archive/reprocessed_2026/ice_endmember_stability.csv`. Every number below comes
from those two files.

**The answer is no, and the reason is worth more than the method would have
been.**

---

## What was tested, and against what

Five anchor surfaces, each run through the pipeline's own loader, cloud model
and classifier, so the cells are exactly the cells the archive counted:

| anchor | day | cells | why its answer is not in doubt |
|---|---|---|---|
| open water | 2019-07-07 | 157345 | July, the fjord is certainly open |
| fast ice | 2018-04-20 | 157730 | ice = 0.9993, 103 water cells in the whole fjord |
| fast ice | 2023-03-31 | 156753 | ice = 0.9939, twelve days before the contested day and on the same processing baseline |
| contested | 2023-04-12 | 56520 | the cells the classifier called water |
| same day, ice | 2023-04-12 | 61404 | the cells it called ice |

The contested day is the one that matters. Two optical instruments read it as
half open water six weeks before that season had ever broken up, and radar puts
it within 2 dB of its own winter ice.

## 1. Separability is not the limit

| band | ice minus water | in within-class spreads |
|---|---|---|
| coastal | +0.6841 | 122 |
| green | +0.6606 | 119 |
| red | +0.7515 | 161 |
| rededge3 | +0.7765 | 201 |
| nir | +0.7329 | 220 |
| nir08 | +0.7677 | 211 |
| swir16 | +0.0453 | 43 |
| swir22 | +0.0470 | 47 |

The two poles are 110 to 220 spreads apart across the visible and near infrared
and still 43 to 47 apart in the SWIR. Nothing about this instrument's bands
prevents an unmixing. Whatever kills the idea, it is not that ice and water look
alike.

## 2. Two endmembers are enough, and the trap that nearly said otherwise

Fitted as a mixture, with shares non-negative and summing to one, weighted by
each band's own measured spread, and with the two atmospheric sounding bands
(B9 at 945 nm, B10 at 1373 nm) excluded because they carry no surface signal:

| model | ice share | atmosphere | residual |
|---|---|---|---|
| ice 2018 + water July | 0.123 | none | 4.0 spreads |
| ice 2018 + water July + atmosphere | 0.106 | 0.0575 | 2.6 spreads |
| ice 12 days before + water July | 0.219 | none | 3.9 spreads |
| ice 12 days before + water July + atmosphere | 0.191 | 0.0567 | 2.4 spreads |
| ice same day + water July | 0.356 | none | 2.1 spreads |
| **ice same day + water July + atmosphere** | **0.327** | **0.0326** | **1.3 spreads** |

Controls, fitted the same way on surfaces whose answer is certain: July water
comes out at 0.000 ice, April 2018 ice at 1.000, both with no residual and no
atmosphere spent. The machinery does not manufacture abundances.

**The trap.** Fitted without a term for the atmosphere, the residual is 4.0
spreads and systematically shaped: positive in the blue, negative in the near
infrared. That is exactly what a melt pond looks like, a surface still bright
where snow scatters and already dark where liquid water absorbs, and reading it
that way would have been a clean, publishable, wrong finding. It is Rayleigh
scattering. The water anchor is July and the contested surface is April, the two
carry different air masses, and at top of atmosphere the blue end lifts. Given a
free non-negative term proportional to lambda to the minus four, the residual
halves and the third material disappears.

Anyone building an unmixing on top of atmosphere reflectance will meet this. It
is not a subtlety, it is the first thing that happens.

## 3. The endmember is not stable, and that is what kills it

The fits above swing from 0.106 to 0.327 ice depending on nothing but which day
supplies the ice spectrum. A factor of three, on the same surface, from the same
data. So the question became whether fast ice has a spectrum at all, or only a
spectrum for the day.

Seventeen days the archive calls unambiguously frozen (ice at or above 0.99, at
least 0.85 of the fjord classified, February to April so break-up cannot be in
play), the two best-covered per season across all ten seasons:

| season | days | brightness | of the median day |
|---|---|---|---|
| 2017 | 2 | 0.6656 | 1.02 |
| 2018 | 2 | 0.6520 | 1.00 |
| 2019 | 2 | 0.6930 | 1.06 |
| 2020 | 2 | 0.6368 | 0.98 |
| 2021 | 1 | 0.6283 | 0.96 |
| 2022 | 1 | 0.6943 | 1.06 |
| **2023** | **2** | **0.4285** | **0.66** |
| 2024 | 2 | 0.6681 | 1.02 |
| **2025** | **2** | **0.5887** | **0.90** |
| **2026** | **1** | **0.5808** | **0.89** |

Band by band, across the seventeen days, the endmember moves by a factor of
1.53 in the coastal band, 1.67 in green, 1.82 in the 865 nm band, and 4.18 in
SWIR16.

**It is not the sun.** Sun elevation across these days runs from 20.7 to 32.7
degrees, and it explains 7 percent of the variance in brightness (r = +0.262).
L1C reflectance is already divided by the cosine of the solar zenith angle, so
this is the right expectation and it is what the data shows. The two darkest
days, 2023-04-02 and 2023-04-07, sit at sun elevations of 24.3 and 26.2 degrees,
squarely in the middle of the range, between days that read half again as
bright.

**It is not the processing baseline either.** From baseline 04.00 the products
carry a radiometric offset worth 0.1 in reflectance, and 2018 and 2023 sit on
opposite sides of that boundary, so the question had to be asked. The answer is
that post-offset days span the entire range: 2022 at baseline 04.00 reads 1.06
of the median, 2024 at 05.10 reads 1.02, 2026 at 05.12 reads 0.89, and 2023 at
05.09 reads 0.66. If the offset correction were wrong, they would move together.

## 4. What a fixed endmember library would cost

Anchored on the median frozen day, which is the library an honest implementation
would build, the seventeen days that are all 1.00 ice read between **0.63 and
1.08**. Only 59 percent of them land within 5 points of the truth. The worst,
2023-04-02, reads 0.63.

The effect this project measures is a decline of **0.154** in ice fraction
between the early and late period means, 0.6839 against 0.5296, which is the 22.6
percent the story publishes. An endmember error of 0.37 on a day whose answer is
certain is more than twice the entire signal. An earlier version of this
paragraph compared against 0.32, a decline this project has since retracted; the
correction widens the margin rather than narrowing it. A fixed library cannot be used here, and that closes the
direction as it was posed.

## 5. The finding that outlives the method

The spring fast ice of 2023 was **34 percent darker** than the ten-season median,
at the same sun elevations, on the same processing baseline, through the same
classifier, on days the archive scores at 0.99 ice. 2025 and 2026 read 10 and 11
percent darker. Every other season sits within 6 points of the median.

This is a physical statement about the surface, not about the software. And it
lands on exactly the seasons the rest of this project has been circling:
[limitations.md](limitations.md#melt-ponds-bias-break-up-early-and-now-there-is-a-number)
reports that twelve of 102 certainly-closed April scenes fall below 0.90 ice,
and that those twelve cluster in 2021, 2023 and 2025 at p = 0.0018.

It also names the mechanism. The brightness gate is a pair of fixed cuts, green
above 0.10 and near infrared above 0.17, applied to a surface whose brightness
varies by a third between seasons. The two 2023 days read NIR 0.47 and 0.52
against a ten-season median of 0.76, so the whole distribution moves toward the
gate and more of its lower tail crosses it. The classifier is therefore more
likely to lose ice in exactly the seasons that were darkest, and those are
seasons in the late period.

That last sentence points the same way as the published result, which is the
uncomfortable direction, and it is quantified in
[limitations.md](limitations.md) rather than left implicit here.

## What this does not establish

- **It does not show the published series is wrong.** It shows that one class of
  error concentrates in specific seasons, which the season-end calibration had
  already measured directly and in both directions: on 102 certainly-closed
  April scenes the median miss is 0.0019, and on 51 July scenes 0.0025.
- **It does not say why 2023 was dark.** Less snow on the ice, coarser or wetter
  snow, thinner ice showing through, all produce a darker surface, and this
  measurement cannot separate them. Only the flatness of the change argues
  against any single one of them: a snow grain-size effect bites far harder in
  the near infrared than in the blue, and the observed change is close to
  proportional across the whole spectrum.
- **It does not rule out unmixing with per-scene endmembers.** Deriving both
  poles from each image is standard practice and would sidestep the instability.
  It is also circular exactly where it matters: on a day when the whole fjord is
  wet, the brightest cells in the scene are wet ice, and the scale is set by the
  thing being measured.
- **The sample is 17, not 20.** Three of the twenty selected days were dropped
  because fewer than 5000 of their cells were classified as SOLID ice rather than
  light ice: 2021-04-07 at 2257 cells, 2022-03-23 at 4639, 2026-03-27 at 4463.
  Those are days whose ice was already less spectrally solid, so dropping them
  biases the surviving sample toward the bright end. The instability measured
  here is a lower bound.
- **One day carries less weight than the others.** 2025-03-30 contributed 97015
  cells where the rest contributed about 157000.

## The honest sentence

*Ice and water are 110 to 220 measurement spreads apart in these bands, and a
two-endmember mixture describes the contested April surface to within 1.3 of
them, so the arithmetic of a sub-pixel treatment is sound. What fails is the
anchor. Across seventeen days that are all unambiguously frozen ice, the pure
ice spectrum moves by a factor of 1.7, it is not the sun and it is not the
processing, and a fixed library would report a solidly frozen fjord as 0.63 ice.
That error is larger than the decline this project measures, so a fraction
cannot be published from a fixed endmember. The reason it fails is itself the
result: the spring ice of 2023 really was a third darker than the ten-season
median, and the seasons where this pipeline loses ice to the water class are the
seasons where its ice was darkest.*
