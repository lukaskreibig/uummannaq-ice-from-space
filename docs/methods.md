# Method

How a Sentinel-2 scene becomes one ice-fraction number for Uummannaq Bay, and why
each choice is the one it is. Every number in this document was measured against
the imagery or the archive; nothing is quoted from a plan.

Companion documents: [limitations.md](limitations.md) for what the method cannot
do, [investigation-log.md](investigation-log.md) for how the current version was
arrived at.

---

## 1. Area of interest

A fixed rectangle over the bay, `-52.336121/70.628226` to `-51.945564/70.788206`,
which is **267.3 km²** on the WGS84 ellipsoid, about 14.7 by 18.1 km. Of that, **253.5 km² is water** and 13.7 km² is land, measured from `assets/landmask.tif` rather than assumed: the grid is 1474 by 1812 cells at 10 m and 0.05143 of them are land. The water figure is the one the story multiplies its anomalies by, and it is the only area number that should appear anywhere.

The area is computed from the polygon, not carried as a constant. It was a
constant, `FJORD_KM2 = 3450`, and that was wrong by a factor of 13.4. Because the
constant also converted the spring anomaly into square kilometres, the published
series reported anomalies of up to 1367 km² over a water area of 253.5 km², which is
physically impossible and went unnoticed for the life of the project.

## 2. Scene selection

Source: Sentinel-2 **L1C**, collection `sentinel-2-l1c` on Earth Search
(`earth-search.aws.element84.com/v1`), read anonymously from
`s3://sentinel-s2-l1c`.

**Why L1C and not L2A.** This is a deliberate choice, not an oversight.

- König, Hieronymi and Oppelt (2019, *Frontiers in Earth Science*) tested five
  atmospheric correction processors against ship-based spectra of Arctic sea ice.
  Sen2Cor performed worst, was the only processor returning reflectance above 1.0
  in bands 3 and 4, and their conclusion is that it is unsuitable for Arctic sea
  ice applications.
- ESA processes products with a solar zenith angle above 70 degrees with the
  angle clipped to 70, and states their surface reflectance should not be used
  for quantitative analysis. Measured over this archive that is **417 of 1552
  scenes**, including all of February and all of October, which are exactly the
  freeze-up and maximum-ice shoulders.
- NDSI on at-satellite reflectance has precedent: the MODIS Snowmap algorithm,
  the longest-running operational snow product, computes it from Level 1B
  radiances.

Honest counterpoint, worth knowing before defending this: the European
operational Sentinel-2 snow products (Theia, Copernicus HRSI) do use L2A, but
produced by **MAJA**, not Sen2Cor. Switching the collection string on Earth Search
gives Sen2Cor, which is the one option the literature rules out.

**Which scene, when several are on offer.** One scene per calendar day, chosen
deterministically:

1. Reject any item whose bounding box is too large to be a granule (over 20
   degrees of longitude or 10 of latitude). Tiles crossing the antimeridian carry
   a box of `[-180, ..., 180, ...]`, which covers every AOI on the planet
   perfectly. Two such scenes, from West Africa and the North Pacific, reached
   the published record and contributed an ice fraction of 0.0.
2. Reject anything covering less than 10 percent of the AOI box.
3. Rank by AOI coverage, then by whether the tile sits in the UTM zone the AOI
   itself belongs to, then by scene id.

The zone preference matters more than it looks. Both neighbouring tiles cover
this AOI completely and score 1.0, so coverage alone left the decision to the
alphabet: 21WXU sorts before 22WDD and would have won almost every day, where the
published archive is 81 percent 22WDD. Uummannaq sits at 52.1 degrees west, which
is zone 22, and a scene delivered in its own zone needs the least reprojection.
Verified against the live catalogue: season 2019 returns 102 scenes, all 22WDD,
no foreign tiles.

## 3. Reflectance

All 13 bands, converted from digital numbers per the ESA convention:

```
baseline < 04.00 :  reflectance = DN / 10000
baseline >= 04.00:  reflectance = DN / 10000 - 0.1
```

The offset (`RADIO_ADD_OFFSET = -1000`) was introduced with processing baseline
04.00 on 25 January 2022. The branch reads `s2:processing_baseline` **per item**,
not the acquisition date, because reprocessed baseline 05.00 products carry
acquisition dates from 2019 to 2021 and a date rule would misconvert them.

This was previously implemented with the sign reversed. See
[investigation-log.md](investigation-log.md#the-offset-that-was-holding-up-the-classification);
it is the most consequential defect the project has had.

Bands load onto a common 10 m grid and the 13-band stack is then average-pooled
4 by 4 onto a **40 m analysis grid**. Every mask and index below is evaluated
there, so features smaller than 40 m are not resolved.

## 4. Masks

**No-data.** A void pixel is DN = 0 in every band, which after the offset is a
known per-band constant (0.0 before baseline 4, -0.1 from 4 on). Each band is
tested against that constant rather than summing the cube: from baseline 04.00
the void value is negative, and a genuinely dark open-water pixel sums to about
-1.2 against a void pixel's -1.3, so a sum test discards real water.

**Land.** A GeoTIFF carrying its own CRS and transform, **reprojected** onto each
scene grid. It is derived from the imagery by `scripts/derive_landmask.py`: land
is what stays above 0.06 in the 75th percentile of near-infrared reflectance
across eight clear August scenes spanning 2019 to 2024. Open water is nearly
black in the near infrared (measured median 0.021) and rock and tundra are not
(0.141), a separation factor of 6.8, and drifting ice cannot hold a pixel across
four years.

The 75th percentile rather than the median is deliberate: at 70 degrees north the
mountain shadows its own eastern face, and a shadowed slope is as dark in the
near infrared as water. The sun azimuth differs between scenes, so a face
shadowed in one is lit in another.

Enclosed inland water counts as land. Uummannaq has lakes and ponds, they are
dark in the near infrared like the sea, and ice on them is lake ice. Measured:
4032 cells in 80 patches, largest 0.12 km². This is a sea-ice measurement, so
they are excluded.

Result: **5.15 percent** of the frame. The painted 512 by 512 template it
replaced masked a constant 9.00 percent of every scene regardless of grid size,
including for the two scenes from other continents, so it covered nearly twice
the island's actual extent.

**Cloud.** A CloudSEN12 UNetMobV2 checkpoint over the 13-band stack, four
classes (clear, thick cloud, thin cloud, cloud shadow). Everything the argmax
does not call clear is masked, followed by a 3 by 3 binary closing. Inference
runs in full precision on every device.

This is the weakest part of the method. See
[limitations.md](limitations.md#cloud-detection-is-the-largest-remaining-error).

## 5. Classification

On the cells that are not cloud, not land and not void:

```
NDSI = (green - swir16) / (green + swir16)
NDWI = (green - nir)    / (green + nir)

ice   requires  NDSI > threshold  AND  green > 0.10  AND  nir > 0.17
        solid:  NDSI > 0.70
        light:  0.40 < NDSI <= 0.70
water requires  NDWI > 0.20  and not already ice
```

**The brightness floors are not decoration, they are what separates ice from
water.** At top of atmosphere, open water is nearly black in the SWIR, so its
NDSI runs about 0.82, which is *higher* than April fast ice at 0.72. NDSI alone
therefore classifies the open fjord as ice. The floors are the classic Dozier
construction that the MODIS lineage still uses: snow and ice are bright in the
visible and the near infrared, water is dark in both.

Measured on the real 2023-08-18 scene, an open summer fjord: with the brightness
gate the ice fraction is 0.002, without it 0.584.

**Negative reflectance is clamped to zero before the ratios are formed.** After
the offset correction the darkest water can land slightly below zero, which is
unphysical and is the offset applied to sensor noise. A negative term breaks the
arithmetic that keeps a normalised difference inside [-1, 1]: with green 0.05 and
nir -0.02 the ratio is 2.33, and a real scene produced a mean NDWI of 1.65 this
way. A floor on the denominator (0.02) additionally rejects ratios of two
near-zero numbers.

**The solid/light split is weakly determined and should not be presented as thick
against thin ice.** See [limitations.md](limitations.md#the-solid-light-split).

## 6. From scene to number

Per scene the classifier reports pixel counts and two sets of percentages:

- against the **whole grid** (`solid_pct`, `light_pct`, ...), kept so the change
  stays auditable
- against the **clear cells** (`solid_pct_clear`, ...), which is
  `not cloud and not land and not void`

**Use the clear-sky columns.** Dividing by the whole grid makes the measurement
depend on the weather: cloud cells can never be ice, so a cloudy day mechanically
reports less ice even when the fjord underneath is unchanged. Cloud is not evenly
spread over this record. In the analysed window the 2017 to 2020 seasons average
21.3 percent cloud and the 2021 to 2025 seasons 29.7 percent, so the whole-grid
denominator turns a weather trend into an apparent ice trend. Measured on the
published archive, the early-to-late seasonal loss is **35.7 percent with the
whole-grid denominator and 22.7 percent with the clear-sky one**.

A scene is marked `usable = 0` when fewer than 30 percent of its cells are clear.
318 of 1552 published scenes are over 80 percent cloud and entered the daily
series unfiltered, with a mean reported ice fraction of 0.014. Those are pictures
of cloud, not measurements of ice.

Daily series (`scripts` in the story repo): ice fraction per scene is
`solid + light`, averaged over the day's scenes, reindexed to every calendar day,
gaps up to 14 days interpolated linearly and longer gaps filled from the
day-of-year mean, then two passes of a centred 7-day mean.

**Freeze-up and break-up** require the state to persist for 7 consecutive days.
They used to be the minimum and maximum of the days above the ice threshold, so a
single misclassified day decided a season in either direction.

## 7. Reproducibility

- Scene choice is deterministic; the same window returns the same scenes.
- Inference is device independent; CPU and MPS produce identical masks.
- A failed band read is rejected rather than published. GDAL can return a band as
  pure fill without raising, and the scene then reads as a plausible open-water
  day.
- Every run writes a manifest recording the resolved configuration.

## References

- König, M., Hieronymi, M., Oppelt, N. (2019). Application of Sentinel-2 MSI in
  Arctic research: evaluating the performance of atmospheric correction
  approaches. *Frontiers in Earth Science* 7:22.
- Dozier, J. (1989). Spectral signature of alpine snow cover from the Landsat
  Thematic Mapper. *Remote Sensing of Environment* 28, 9 to 22.
- Hall, D. K., Riggs, G. A. MODIS Snow Products Algorithm Theoretical Basis
  Document and MOD10A1 V006 User Guide.
- ESA SentiWiki, Sentinel-2 products: radiometric offset from processing
  baseline 04.00.
- Aybar, C. et al. CloudSEN12, a global dataset for semantic understanding of
  cloud and cloud shadow in Sentinel-2.
