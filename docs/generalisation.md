# From one fjord to any Arctic coast

What it would take to turn this into a tool that builds a sea-ice time series for
an arbitrary Arctic coastal site, and why the work done so far already covers
more of that than it looks.

This is a design note, not a plan of record. It exists because several of the
corrections in [investigation-log.md](investigation-log.md) turned out, by
accident, to be exactly the steps that make the pipeline portable.

---

## What is already site independent

Four things that used to be hard-coded for Uummannaq now derive themselves.

| | Before | Now |
|---|---|---|
| UTM zone preference | implicit in which tile happened to win | computed from the AOI centroid |
| Analysed area | `FJORD_KM2 = 3450`, a constant, wrong by 13.4x | geodesic area of the AOI polygon |
| Land mask | a painted 512 by 512 PNG stretched to the grid | derived from eight clear summer scenes |
| Foreign-scene rejection | none | footprint plausibility, no site knowledge needed |

The land mask is the significant one. It was the single most site-specific asset
in the repository, a hand-painted file that could not exist for a new location
without someone painting it. It is now a 40 line derivation from imagery that
runs anywhere the sea is dark in the near infrared and the land is not, which is
every Arctic coast in summer.

**For a new site today the manual work is: draw a polygon, run
`scripts/derive_landmask.py`, look at the quicklook.**

## What is still specific, in order of difficulty

### 1. The seasonal window, easy

`SEASON_START_DOY = 45`, `SEASON_END_DOY = 180`, chosen for Uummannaq's solar
geometry. This is pure astronomy: the window should be the days on which the
solar elevation at local overpass time exceeds some floor, computed from latitude
and date. A dozen lines, no data needed.

The floor itself needs a decision. Uummannaq's 45 corresponds to roughly 10
degrees elevation, which is already marginal: February rests on few usable scenes
under long mountain shadows.

### 2. The brightness floors, moderate

`vis_bright_min` and `nir_bright_min` come from the Dozier construction and are
physical rather than local: ice is bright, water is dark, everywhere. But path
radiance at low sun lifts water in the visible, so a fixed visible floor is
latitude and season dependent in a way the near-infrared floor is not.

The defensible version makes the visible floor sun-angle aware, or adds a
Rayleigh correction term. That is a known, solvable piece of physics.

### 3. The NDSI cuts, harder

These are the least transferable numbers in the method, and the reason is
instructive: over this fjord NDSI carries almost no information about the
surface. Solid ice, thin ice and open water all sit around 0.7 to 0.95 because
all three are nearly black at 1.6 µm. The cut that separates ice types is
therefore weakly determined here, and there is no reason to think a value tuned
at one site transfers to another with different ice regimes.

Two honest options. Either derive them per site from the imagery, which needs a
labelled set and is the approach `scripts/derive_thresholds.py` sketches. Or
abandon NDSI for the ice-type split and use brightness, which is what actually
varies: sorting gated pixels by near-infrared brightness moves reflectance by a
factor of 43 across the deciles while NDSI stays inside 0.03.

### 4. Cloud, the real obstacle

The same weakness appears everywhere, not just here: optical cloud detection over
ice is hard because cloud and ice are both white and bright. The CloudSEN12
checkpoint under-detects and over-detects at this site depending on the scene,
and nothing suggests it would behave better elsewhere.

Any general product needs a position on this. The three plausible ones:

- **Report it.** Publish a per-scene confidence, gate on visibility, and let the
  user see the mask. This is what the current pipeline does.
- **Cross-check with SAR.** Sentinel-1 sees through cloud. Expensive per site,
  but it is the only measurement that bounds the error.
- **Retrain.** A cloud model fine-tuned on Arctic coastal scenes would probably
  beat a general one. This is a project, not a feature.

### 5. Coastal geometry, site by site

Uummannaq is an island in a bay, so "the water surface" is unambiguous once land
is masked. A site with a river mouth, a glacier front or a tidal flat is not.
Glacier ice reaching the water is the obvious hazard: it is bright, it is
adjacent to sea ice, and it is not sea ice.

This is the part that genuinely does not generalise without human judgement,
which leads to the next section.

## A product shape: automate, then show

The errors in this pipeline shared one property. **None of them raised an
exception.** A sign flip, a denominator, a stretched mask, a silently zeroed
band: every one produced a complete, plausible, wrong number. What found them was
a human comparing something against an expectation, and in two cases simply
looking at a picture.

That is an argument about product design, not just about testing. If the failure
mode of this class of work is quiet wrongness, then the interface should be built
around **making each automated step inspectable and rejectable**, rather than
around hiding the steps.

A shape that follows from that:

```
 1  Draw the AOI          →  area, UTM zone, tile candidates shown immediately
 2  Derive the land mask  →  overlay on a summer scene. Accept, adjust, redo.
 3  Fix the season        →  computed from latitude, shown as a calendar
 4  Propose thresholds    →  applied to 3 scenes across the season, side by side
 5  Trial run, 10 days    →  a panel per scene: raw, cloud, land, class, number
 6  Full time series      →  runs unattended, with the validator as the gate
 7  Refresh               →  same configuration, new dates, on a schedule
```

Steps 1 to 5 are a conversation; step 6 is a batch job; step 7 is a cron. The
value is not the automation, which is the easy part. The value is that every
accepted step is recorded as a **decision with a reason**, so what comes out at
the end is a time series with a derivation attached rather than a curve someone
has to take on trust.

Two things follow that are worth stating plainly:

- **The trial run is the product.** Ten days with visible intermediates would
  have caught the land mask, the cloud under-detection and the zeroed band. It is
  cheap and it is where the quiet errors surface.
- **The validator belongs in the loop, not at the end.** The checks in
  `scripts/check_summary.py` exist because each one corresponds to a defect that
  actually shipped. Those are the gates a general product would run automatically
  and show as a report.

## What this repository would need first

If the goal is a general tool rather than one fjord, the order that makes sense:

1. Derive the season window from latitude. Small, unlocks the next steps.
2. Make the visible brightness floor sun-angle aware. Physics, bounded work.
3. Persist the per-scene masks, which the pipeline currently computes and throws
   away. Without them nothing after the fact is inspectable and the archive
   cannot be re-thresholded without re-downloading everything.
4. A trial-run report: one page per scene, raw against classified.
5. Only then the site-agnostic threshold derivation.

Steps 3 and 4 are the ones that pay immediately, at this site as much as at any
other, and they are the precondition for the interface sketched above.
