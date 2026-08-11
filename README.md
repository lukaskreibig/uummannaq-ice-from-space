# Uummannaq Ice From Space

A Sentinel-2 pipeline that turns one Greenland fjord into one ice-fraction number
per day, ten seasons, 2017 to 2026, and then spends most of its effort trying to
break that number.

What it measures: the later seasons hold about **23 percent** less spring ice
than the earlier ones. What it can defend after correcting a bias found with a
thermal band and resolved with radar: about **19.5 percent**. What it cannot
claim: significance. The exact permutation test gives **p = 0.119** over ten
seasons, and no monotone trend is detectable at all. The direction is consistent
under every treatment. The certainty is not there, and ten winters is why.

![The 30 March 2013 fjord in the near infrared and in brightness temperature, beside the same fjord on 23 April](docs/images/dark-ice-2013-03-30.jpg)

*Both days are frozen shore to shore. The classifier only says so about one of
them, because on 30 March the surface is too dark for the brightness gate and
falls through to the water class. A second satellite reads the same reflectance
that day to within a hundredth, so it is not the instrument. Found in the course
of asking whether the record began on an unusually icy stretch, and it turned out
to matter more than the question. `scripts/figure_dark_ice.py`.*

## One scene, and a defect you can see

![One scene through the pipeline: RGB, cloud mask, land mask, solid ice, light ice, and the overlay](docs/images/pipeline-panel-2017-02-19.jpg)

*One scene, 19 February 2017, at every stage, from a run of the current code.
**Look at the long blue wedge north of the island in the overlay.** That is the
mountain's shadow on sea ice, and the chain calls it open water, because a
shadowed surface is dark and a dark surface fails the brightness gate. On this
day it costs 9.9 percent of the readable fjord on ice that is frozen shore to
shore. `scripts/shadow_bias.py` measures it across the record: 0.216 in the first
fortnight of the window and 0.003 by April, because the shadow shortens as the
sun climbs. It very nearly cancels between the two periods only because both are
sampled at the same days of the year, median day 78 against 80. Panels like this
are written for every scene, and looking at them is how both this and the land
mask defect in docs/investigation-log.md were found.*

## What was asked, and what it cost

Every row is a question this project put to its own result, a script that
answers it, and a committed artefact under `archive/reprocessed_2026/`. The
right-hand column is what the answer did to the headline, because a check that
cannot move a number is not a check.

| The question | Answer | Headline |
|---|---|---|
| What does the choice of denominator do? `denominator_comparison.py` | cloud is not evenly spread across the years, and a cell called cloud can never be ice | **35.4 to 25.2 %** |
| Where should the brightness gate sit? `gate_sensitivity.py` | 19.4 to 23.0 across a range wider than anyone would defend | **20.3 %** if it tracks each season's own ice |
| How much rests on twelve suspect April scenes? `wet_day_sensitivity.py` | hand every one back a frozen fjord | 22.6 to **21.6 %** |
| What does the 40 m grid cost? `grid_resolution.py` | 0.0015 across grids from 10 to 80 m; the cloud mask's own resolution is the real lever | **0.2 points** |
| Does fast ice have a spectrum? `ice_endmember_stability.py` | no. It moves by a factor of **1.7** across days that are all unambiguously frozen | kills sub-pixel |
| Can a sub-pixel fraction replace the class? `endmember_separability.py` | the arithmetic is sound and the anchor is not | abandoned, with the reason |
| What is break-up, on observed days? `breakup_definitions.py` | 30 definitions, direction unanimous, magnitude **-0.7 to -53 days** | the shift is a choice |
| Does a second optical sensor agree? `landsat_crosscheck.py` | RMSE **0.026** over 23 days whose answer was not in doubt | thresholds are not overfitted |
| And at low winter sun, where Level 2 cannot go? `landsat_l1_crosscheck.py` | yes, and CFMask discards **83 %** of a frozen fjord | a fact about optical cloud masks |
| Does radar back the contested days? `validate_sar.py`, `sar_wet_days.py` | within about **2 dB** of that season's own fast ice | the ice was still there |
| Did the record begin on an unusually icy stretch? `landsat_season_series.py` | no. Four seasons further back move the baseline by under **0.04** either way | not a lucky start |
| Was Landsat 8 wrong in March 2013, or was the fjord? `commissioning_check.py` | the fjord. My own hypothesis, refuted by the one scene it had discarded | the route is in the log |
| What does a thermometer say, on every day? `thermal_audit.py` | **36 of 226** days call the fjord open while it radiates below the freezing point of seawater, twice as often after 2021 | the largest open item |
| Closed ice, or floes the chain read correctly? `sar_thermal_days.py` | 8 like fast ice, 6 like open water, 13 between | both extremes refused |
| What does that cost the published series? `sentinel_correction.py` | matched, corrected, and the published cleaning rerun unchanged | 22.6 to **19.5 %** |
| The mountain's shadow on the sea ice? `shadow_bias.py` | **0.216** of the fjord called water in mid February, 0.003 by April | cancels, because both periods sit on the same days |
| Do the published numbers still reproduce? `story_numbers.py` | recomputed from the archive and diffed against a committed set | **runs in CI** |

Five systematic errors were found this way and none of them raised an exception.
[docs/investigation-log.md](docs/investigation-log.md) is the route rather than
the destination, including four of my own and one hypothesis that did not survive
its own test.

## The scale of it

```
   1103 scenes        10 seasons, 2017 to 2026, Sentinel-2 L1C
     28 scripts       one question each, all committed with their artefacts
     23 artefacts     archive/reprocessed_2026, every published figure traceable to one
      4 instruments   Sentinel-2 optical, Landsat optical, Landsat thermal, Sentinel-1 radar
   4004 lines         documentation, ordered by how much each weakness could change a conclusion
    114 tests         plus two number gates that run on every push
```

## Check a number yourself

Every published figure has a committed artefact and a script. These run offline,
against `archive/reprocessed_2026/`, with no credentials and no network:

```bash
python scripts/story_numbers.py                       # the headline, and every number the story shows
python scripts/denominator_comparison.py              # why the denominator changed, and what it cost
python scripts/gate_sensitivity.py  --reuse --out archive/reprocessed_2026
python scripts/grid_resolution.py   --reuse --out archive/reprocessed_2026
python scripts/validate_sar.py --analyse-only --output archive/reprocessed_2026/sar_validation.csv
python scripts/check_summary.py archive/reprocessed_2026/summary.csv
```

The first and the last of those are the CI gate. `.github/workflows/ci.yml` runs them on
every push, so a page that has gone stale against the data fails the build rather
than waiting to be noticed. The daily series they read is committed as
`archive/reprocessed_2026/daily_series.csv`; `story_numbers.py --live` reads the
story repo's working copy instead and fails if the snapshot has drifted from it.

`docs/published_numbers.json` holds the figures the documentation quotes.
`story_numbers.py` recomputes them from the daily series and exits non-zero if
they have drifted, which is the fastest way to catch a page that has gone stale.

**One dependency is outside this repository.** The scene-to-day conversion, the
gap filling and the smoothing live in the story repo next door, at
`../climate-dashboard/data-pipeline/refresh_fjord_season.py`, and
`story_numbers.py`, `wet_day_sensitivity.py` and `sentinel_correction.py` all
import it. The recipe is written out in
[docs/handoff-to-story.md](docs/handoff-to-story.md), but without that checkout
those three scripts stop before printing anything. Everything else above is
self-contained.

## Read this first

The pipeline produces one number per day. These say what that number is, what it
is not, and how it was arrived at.

| | |
|---|---|
| [docs/limitations.md](docs/limitations.md) | What the method cannot do, quantified, ordered by how much it could change a conclusion. Start with the table at the top. |
| [docs/investigation-log.md](docs/investigation-log.md) | How five systematic errors were found. None of them raised an exception, and the fifth is still moving the headline. |
| [docs/methods.md](docs/methods.md) | Every processing step and the reason for each parameter, with the measurement behind it. |
| [docs/generalisation.md](docs/generalisation.md) | What it would take to run this at any Arctic coastal site, and what already does. |

And the three attempts to break the result with a different instrument, which are
the part of this project worth reading if you only read one thing:

| | |
|---|---|
| [docs/landsat-crosscheck.md](docs/landsat-crosscheck.md) | Four parts. A second optical sensor on the same day, then at low winter sun, then four seasons further back, then a thermal band and radar on the days where the classifier and the physics disagree. |
| [docs/sar-validation.md](docs/sar-validation.md) | Sentinel-1 on the winter days the optical chain cannot explain, including where two of this project's own cross-checks contradict each other. |
| [docs/unmixing-feasibility.md](docs/unmixing-feasibility.md) | Whether a sub-pixel fraction could replace the hard class. The arithmetic is sound, the anchor is not, and a systematically shaped residual that looked exactly like a melt pond was Rayleigh scattering. |

Where the evidence lives: `archive/reprocessed_2026/` holds the 1103-scene run
behind every figure plus 24 result artefacts, one per measurement. It is tracked,
not ignored, and it is not the legacy material described further down.

---

## What is still open

Ten seasons are processed and committed, so nothing here is about coverage.
Ordered by whether I would actually do it.

**1. Reach further back than 2013, with a threshold that is not absolute.** The
archive holds 36 seasons from 1990 and the blocker is calibration across sensor
boundaries, not data: over this AOI there are zero same-overpass pairs between TM
and ETM+ and zero between TM and OLI, so a fixed brightness threshold cannot be
carried across. The one untested route is a per-season adaptive gate, which
`gate_sensitivity.py` already implements for a different purpose. It stops
carrying an absolute threshold across the boundary, at the cost of a quantity
that is no longer identical from season to season, so it would be a second series
standing beside this one rather than a replacement. This is the item worth doing.

**2. MODIS from 2000, at 500 m rather than 250.** Worth stating carefully because
an earlier version of this list got it wrong. MODIS carries 250 m only in the red
and near infrared; the 1.6 micrometre band that NDSI needs is 500 m, and on Aqua
most of its detectors have failed, so this is Terra at 500 m. That is about a
thousand water cells over a 253 km2 fjord, coarse but not hopeless, and MODIS
carries thermal bands, which this project has learned to value. It would nearly
double the record at a resolution that would have to be shown not to change the
answer.

**3. Whether the dark-ice correction belongs inside the pipeline.** It is
currently measured, disclosed and applied alongside: the published series is
uncorrected and `sentinel_correction.py` says what correcting it would do. That
is deliberate rather than pending. Baking it in would make a chain of four
instruments into production data, and the correction depends on a matching window
that spans 17.9 to 20.9 percent, so the pipeline would carry a choice that the
evidence does not pin down. Reopen it when the matching window can be closed, not
before.

**4. A cast-shadow mask from a digital elevation model.** `shadow_bias.py` shows
the mountain's shadow costs 0.216 of the fjord in mid February and 0.003 by
April, and that it cancels between the periods because both are sampled at the
same days of the year. A DEM plus the per-scene sun geometry, both already
available, would let the chain treat shadow the way it treats cloud: an area it
cannot read rather than water. Not done, and not obviously worth it: the bias
cancels, and masking it would drop February scenes below the visibility gate
entirely, trading a measured bias for missing days in the thinnest part of the
record.

---

# Running it yourself

Everything above is the work. Everything below is the tool: how to install it,
how to run it, and how it is packaged.

## Quick start

```bash
python3 -m venv .venv              # Python 3.10 to 3.13 are supported
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
# Install PyTorch (pick the command that matches your platform)
# macOS / CPU / MPS:
pip install "torch==2.7.0" "torchvision==0.22.0" "torchaudio==2.7.0"
# CUDA 12.4 (Linux/Windows) (not tested):
# pip install "torch==2.7.0+cu124" "torchvision==0.22.0+cu124" "torchaudio==2.7.0+cu124" \
#   --index-url https://download.pytorch.org/whl/cu124
pip install -e .

# (optional) install development tooling + hooks
make dev

# Run the pipeline with the baseline YAML config (May to June 2025 AOI)
uummannaq-ice --config-file config/baseline.yaml --output-dir out/runs/latest
```

Use `uummannaq-ice --help` to view all parameters (AOI override, thresholds, device selection, etc.).

If you need a different build (e.g., other CUDA versions), follow the [official PyTorch install selector](https://pytorch.org/get-started/locally/) and then run `pip install -e .` afterwards.

## Repository layout

```
archive/reprocessed_2026/  # THE EVIDENCE: the committed run and one artefact per measurement
archive/legacy_pipeline/   # Unmodified legacy notebooks and outputs, kept for traceability
config/                 # YAML run configurations (supports inheritance)
data/                   # Raw/interim/processed datasets (ignored by git by default)
docs/                   # Extended documentation (architecture, pipeline, datasets, integration)
docker/                 # Container definitions (CPU + CUDA)
notebooks/              # Exploratory notebooks (moved from legacy pipeline)
scripts/                # Utilities (benchmarking, satellite scraping)
src/uummannaq_ice/      # Production Python package and CLI
tests/                  # Pytest suite (unit + mocked integration)
out/                    # Default runtime outputs (Git-ignored)
summary_test_singleimage.csv  # Historical output sample kept for reference
```

The packaged assets are:

- `src/uummannaq_ice/models/unet_mobv2_v2.pt`: MobilenetV2 UNet checkpoint (cloud segmentation).
- `src/uummannaq_ice/assets/landmask.tif`: the georeferenced land mask the pipeline uses.
  The older `landmask_template.png` is kept only for traceability; it is the painted,
  ungeoreferenced mask that docs/investigation-log.md records as a defect, and it must
  not be reintroduced.
- `config/*.yaml`: Versioned run presets (supports `extends` for layered configs).

## Pipeline overview

`docs/pipeline.md` describes every stage in detail; at a high level:

1. Search the Element84 STAC (`sentinel-2-l1c`) within the configured AOI and date range, deduplicated by observation date.
2. Stream tiles through `odc-stac.load`, average-pool to 40 m, align with the landmask, and derive NDSI/NDWI.
3. Run the MobilenetV2 UNet cloud classifier: four CloudSEN12 classes by argmax, everything not clear is masked, then morphologically closed.
4. Classify pixels into solid ice / light ice / water masks using the thresholds (default NDSI=0.70/0.40, NDWI=0.20) and the brightness gate that does the actual separating (green 0.10, near infrared 0.17).
5. Persist quicklook overlays + panels, aggregate CSV statistics (includes EO cloud cover and sun geometry), and log ETA estimates.

## Documentation

The four above plus the three cross-checks are the ones worth your time. The
rest, complete so that nothing in `docs/` is reachable only by listing the
directory:

- `docs/overview.md`: domain background, architecture, AOI context.
- `docs/architecture.md`: system diagram, components, and extensibility points.
- `docs/pipeline.md`: processing stages, concurrency model, threshold rationale.
- `docs/datasets.md`: data organisation, expected file formats, landmask provenance.
- `docs/handoff-to-story.md`: how a scene becomes a day, and the one step that
  lives in the story repo. Read this before trying to rebuild the daily series.
- `docs/reprocessing-runbook.md`: how the committed archive was produced.
- `docs/development.md`: environment setup, tooling, testing, and release process.
- `docs/integration.md`: CLI, Python, scheduler, Docker, and benchmarking guidance.
- `docs/troubleshooting.md`: symptom-based fixes and debug tips.
- `docs/models.md`: MobilenetV2 cloud model lineage and retraining guidance.
- `docs/published_numbers.json`: the figures the documentation quotes, machine
  readable, regenerated by `make numbers`.
- `CHANGELOG.md`: project history (update when shipping user-facing changes).

## Configuration & manifests

- YAML configs in `config/` capture run presets; use `extends` for overrides (`single_tile_debug.yaml` extends `baseline.yaml`).
- CLI overrides merge with YAML via `--config-file`.
- Each run writes `run_metadata/run_<timestamp>.json` with the resolved configuration, environment details, git commit, and summary stats.

## Testing & QA

- `make lint`, `make typecheck`, and `make test` mirror the CI pipeline (Ruff, mypy, pytest with coverage).
- The pytest suite includes mask aggregation unit tests, YAML inheritance checks, and a mocked pipeline smoke test.
- `scripts/benchmark.py` benchmarks repeated runs with unique output directories and prints aggregated stats.
- GitHub Actions (`.github/workflows/ci.yml`) runs across Python 3.10 to 3.12 on every push/PR.

## Deployment

- CPU Docker image: `docker build -f docker/Dockerfile -t uummannaq-ice:cpu .`
- CUDA Docker image (untested): `docker build -f docker/Dockerfile.cuda -t uummannaq-ice:cuda .`
- Execute via Docker with volume mounts: `docker run --rm -v "$PWD/out":/app/out uummannaq-ice:cpu --config-file config/baseline.yaml`
- The benchmarking script and manifest JSON make it easy to plug the pipeline into Airflow, Dagster, Prefect, or cron (see `docs/integration.md`).

## Legacy material

Legacy experiments from the climate-dashboard repo (including `ice_classification_experimental_copy.py` and historical CSV outputs) live under `archive/legacy_pipeline`. They are read-only snapshots for documentation and should not be edited unless you intend to replicate old behaviour.

To revisit the original scripts:

```bash
cd archive/legacy_pipeline/ice-final
python ice_classification_experimental_copy.py --log DEBUG
```

Note that the original heavy checkpoints have been moved to `models/legacy/` (ignored by git); see `archive/legacy_pipeline/ice-final/README.md` for details before running the legacy notebooks.

