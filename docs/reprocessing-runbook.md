# Reprocessing the archive

Everything needed to reclassify the Uummannaq record from 2017 to today, check
that the result is sane, and hand it to the story. Written for someone who has
not read the discussion that produced it.

Every number below came from a command run on this machine, not from an
estimate. Where a number will change once the band-parallel read lands, that is
said explicitly.

---

## 0. What this run is for

A radiometric offset was being applied with the wrong sign. ESA baseline 04.00
(from 25 January 2022) carries `RADIO_ADD_OFFSET = -1000`, so reflectance is
`DN/10000 - 0.1`; before 04.00 it is `DN/10000`. The code added `+0.1` to the
older era and subtracted nothing from the newer, so both eras sat 0.1 above
true reflectance. Every published number was produced from those biased
reflectances, and the cloud model was fed them too.

That is fixed. The archive has to be reprocessed for the published series to
mean what the methodology box says it means.

**Before starting, confirm the thresholds have been re-derived.** `ndsi_solid
0.52` and `ndsi_light 0.31` were tuned on the biased values. In true NDSI units
0.52 corresponds to roughly 0.65 to 0.78 depending on pixel brightness. Running
10 to 20 hours against the old numbers produces an archive that has to be
thrown away. Check `config/baseline.yaml` and the derivation write-up before
you type anything below.

---

## 1. One-time preparation

```bash
cd ~/Developer/uummannaq-ice-from-space
source .venv/bin/activate          # or however you enter the environment
pip install -e .                   # puts `uummannaq-ice` on PATH
uummannaq-ice --help               # should print, not fail
```

### The one environment variable that matters

```bash
export AWS_NO_SIGN_REQUEST=YES
```

The Sentinel-2 L1C bucket is public but anonymous access has to be requested
explicitly. Without this every band read is a 403. The run does not crash; it
finishes quickly with an almost empty CSV, which is the worst possible failure
mode. `scripts/run_archive.sh` exports it for you; set it yourself if you call
the CLI directly.

`run_pipeline` also does `os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")`,
so a direct CLI call is covered too. Anything that shells out to GDAL outside
the pipeline is not.

---

## 2. Preflight: know the job before you start it

```bash
AWS_NO_SIGN_REQUEST=YES python3 scripts/preflight.py \
    --start 2017-01-01 --end 2026-12-31 \
    --out out/archive/preflight.json
```

This is a metadata query. It downloads no pixels. Measured, on the full range,
it takes **219.5 seconds**; on a single season (1 February to 15 July 2022) it
takes **12.8 seconds**.

What it told us on 2026-08-04:

| | |
|---|---|
| scenes offered, whole calendar 2017 to 2026 | **1804** |
| scenes between 1 February and 15 July | **1101** |
| scenes inside the sun window, day 45 to 180 | **965** |
| MGRS tile mix | `21WXU: 1776, 22WDD: 24, 23XMJ: 2, 60UXB: 2` |
| processing baselines present | 02.04 through 05.12, thirteen distinct values |

It also writes `preflight.json`, which `check_summary.py` later uses to answer
"did every scene the catalogue offered actually make it into the CSV".

**Read the two warnings it prints.** Both are real and both were confirmed by
direct inspection of the catalogue:

1. **Four scenes come from tiles that cannot see this fjord.** `23XMJ` and
   `60UXB` have catalogue bounding boxes of `[-180, -90, 180, 90]` and
   `[-180, 51.06, 180, 90]`. Those span the planet, so the AOI-coverage floor
   in `stac.py` scores them at 1.0 and waves them through. One of them,
   `S2A_60UXB_20190418_0_L1C`, falls on day 108, inside the published season,
   and will land in the record as an ice-free spring day.
2. **The run would use 21WXU where the published archive used 22WDD.** On a
   normal day both tiles have an AOI coverage of exactly 1.0, so `_sort_key`
   falls through to the id tiebreak, and `21WXU` sorts before `22WDD`. The
   published archive is 81 percent 22WDD; this run would be 98 percent 21WXU.

   Measured effect on the number itself, same day, same code, both tiles
   (2022-04-20):

   | tile | grid cells | ice fraction | clear-sky share |
   |---|---|---|---|
   | 21WXU | 186 921 | 0.9095 | 0.9099 |
   | 22WDD | 166 732 | 0.9089 | 0.9100 |

   A difference of 0.0006 on a clear frozen day. So the swap is not a
   catastrophe, but it is a change nobody chose, on top of a change that was
   chosen, and it should be a decision rather than a surprise.

---

## 3. The run

```bash
caffeinate -is scripts/run_archive.sh 2>&1 | tee out/archive/run.log
```

`caffeinate -is` keeps the machine awake for the duration. Without it a laptop
that sleeps mid-run leaves the socket to S3 hanging.

Defaults: seasons 2017 to the current year, 1 February to 15 July of each,
output into `out/archive/`, four attempts per season.

Useful overrides:

```bash
scripts/run_archive.sh 2019 2021               # only those seasons
OUT=out/rerun scripts/run_archive.sh           # somewhere else
WINDOW_START=02-14 WINDOW_END=06-29 scripts/run_archive.sh   # exactly the sun window
```

### Why season by season and not one long call

* The STAC query for the full range costs 219.5 seconds and it is paid again on
  every restart. One season costs 12.8 seconds.
* A crash inside one season costs at most that season's remaining scenes.
* The default window skips the dark half of the year. Of the 1804 scenes the
  catalogue offers, only 1101 fall between 1 February and 15 July, and the
  story discards the rest anyway: `backend/main.py` only reads day of year 45
  to 180, and the cleaning step blanks `frac_smooth` outside it. Skipping them
  removes about a third of the wall clock for no loss of published information.
  The window is deliberately wider than 45 to 180 so the gap interpolation at
  the two edges still has neighbours to work with.

### How long, how much

**This job is bounded by bandwidth, not by the classifier.** Say that first,
because it changes what is worth optimising and what the ETA in the log means.

Measured on this machine on 2026-08-04, a clean run of 2021-03-25 to
2021-04-05, ten scenes, nothing else competing:

| | measured |
|---|---|
| wall clock, start of command to exit | **61 s** |
| inside `run_pipeline` | 54.4 s |
| per scene, wall | **6.1 s** |
| per scene, the classifier's own `elapsed` | **1.18 s** |
| inbound bytes on `en0` | **785 953 344** |
| per scene | **78.6 MB** |
| sustained throughput | 12.9 MB/s |

The two per-scene numbers differ by a factor of five because the bands are now
fetched ahead of and in parallel with the loop. The `elapsed` and `ETA` the
pipeline prints measure classification only; they will always look faster than
the clock on the wall.

Extrapolated to the 1101 scenes of the default window:

| | |
|---|---|
| download | **86.5 GB** |
| wall clock at the measured 12.9 MB/s | **about 1.9 hours** |
| classification alone | 22 minutes |
| the whole calendar instead, 1804 scenes | 142 GB, about 3.1 hours |

Divide 86.5 GB by whatever the connection actually sustains to get the real
answer. At 3 MB/s the same job is 8 hours. This is worth knowing if the
connection is metered.

> Earlier in the same session the same measurement gave 75 s per scene and
> 109 MB per scene. Both improved because the band reads became parallel and
> because the unused pre-rendered `visual` asset stopped being downloaded. If
> the pipeline changes again, re-measure with one short window rather than
> trusting this table, and feed the result to
> `preflight.py --seconds-per-scene`.

Disk, measured from existing quicklooks: overlays average 219 685 bytes and
panels 736 526 bytes, so 1101 scenes produce about **1.0 GB** of PNGs plus a
CSV of a few hundred kilobytes.

### Pin the device

`run_archive.sh` passes `--device cpu` by default, and it should stay that way
for an archive build.

`resolve_device(None)` picks MPS on this Mac and CPU on a machine without one,
so leaving it implicit means the same command can write a different archive
depending on where it ran. Inference on CPU costs about 0.17 s per scene, which
against a 6 s scene is nothing.

`DEVICE=mps scripts/run_archive.sh` overrides it if you want the speed and do
not care about reproducibility.

---

## 4. When it dies, and it will

**Resume is the CSV.** Every season writes into the same `summary.csv`, and
`SummaryWriter` skips any `(tile_id, timestamp)` already present. To resume,
run exactly the same command again:

```bash
caffeinate -is scripts/run_archive.sh 2>&1 | tee -a out/archive/run.log
```

Nothing already processed is downloaded again. The skip happens after the STAC
metadata query and before any pixel is fetched, so a resume of a nearly
finished archive costs one metadata query per season and nothing else.

Verified by test, not by reading:

* Killing a run and restarting it re-processes nothing already in the CSV and
  produces no duplicate rows.
* The "every tile already processed" branch used to raise
  `TypeError: can't subtract offset-naive and offset-aware datetimes`, because
  `pipeline.py` mixed `dt.datetime.utcnow()` with a timezone-aware
  `started_at`. That means the *second* run over a finished window crashed.
  Fixed; the branch now returns clean stats.
* A CSV truncated mid-row, which is what a `SIGKILL` during a flush leaves
  behind, used to be fatal twice over: the half-written scene was registered as
  already processed and so never redone, and the next appended row was glued
  onto the fragment, producing a line with more fields than the header that
  pandas refuses to parse at all. `SummaryWriter` now trims a fragment on open
  and logs that it did.
* Appending to a CSV written with a different column layout now raises
  `HeaderMismatchError` with the two headers printed, instead of quietly
  producing rows of two different widths.

### If a whole season keeps failing

`run_archive.sh` retries four times with growing backoff, then moves on and
reports the season at the end with a non-zero exit. Look at
`out/archive/logs/<year>.log`.

| what you see | what it is | what to do |
|---|---|---|
| `Failed to load <id>: ... 403` | `AWS_NO_SIGN_REQUEST` is not set | export it and re-run |
| `Failed to load <id>: ...` on scattered scenes | transient S3 or DNS | re-run; the retry picks up only the misses |
| `HeaderMismatchError` | the CSV was written by a different version | point `OUT` at a fresh directory |
| `skipped – RGB bands missing` | the catalogue entry is incomplete | nothing to do, that scene has no usable data |
| process killed, no message | most likely the OOM killer | re-run; the fragment is trimmed automatically |

A single scene that raises inside classification, rather than during loading,
still takes the whole invocation down: only the load is wrapped. That is what
the retry loop in `run_archive.sh` is for. Because resume is exact, a crash
costs the crashing scene and nothing else.

---

## 5. Verify before you believe it

```bash
python3 scripts/check_summary.py out/archive/summary.csv \
    --expect out/archive/preflight.json \
    --baseline archive/legacy_pipeline/ice-final/summary_test.csv
```

Exits 0 on ACCEPT, 1 on REJECT. Twelve gates plus two conditional warnings,
and `--json` writes the verdict out for a script to read. Each gate is a thing that has
actually gone wrong:

| gate | fails when |
|---|---|
| `header` | the column layout is not the current one |
| `rows_intact` | a row holds more fields than the header, the torn-fragment signature |
| `no_duplicate_scenes` | the same `(tile_id, timestamp)` appears twice |
| `no_duplicate_dates` | a calendar day carries more than one scene |
| `tiles` | a scene comes from an MGRS tile that does not see this fjord |
| `ranges` | any share falls outside 0 to 1, or a pixel count is negative |
| `indices` | an NDSI or NDWI mean falls outside -1 to 1 |
| `grid` | the implied grid size is not consistent within a row |
| `grid_accounting` | the classes claim more cells than the grid holds |
| `season_shape` | a season is not high in February and low in late June |
| `scene_counts` | fewer scenes made it in than the catalogue offered |
| `baseline` | informational: the biggest movers against the published series |

Run against the currently published archive it reports three failures, which is
a fair demonstration that the gates are not decorative: the two foreign tiles,
383 rows with a negative `unknown_px`, and 368 of 1552 rows claiming up to
117.8 percent of the grid. The same checker on a fresh ten-scene run passes
every structural gate.

What a good result looks like: `ACCEPT` or `REVIEW`, `season_shape` passing for
every year, `scene_counts` complete, and a `baseline` line whose per-year table
moves in a direction you can explain.

---

## 6. Hand it to the story

See [`handoff-to-story.md`](handoff-to-story.md). In short:

```bash
cd ~/Developer/climate-dashboard/data-pipeline
python3 refresh_fjord_season.py --clean-only \
    --raw ~/Developer/uummannaq-ice-from-space/out/archive/summary.csv
```

That turns one row per scene into one row per day, writes
`data/summary_test_cleaned.csv`, copies it to `frontend/public/data/`, prints
how far each season moved, and recomputes the derived tables if a database is
configured.

---

## 7. Quick reference

```bash
# preflight
AWS_NO_SIGN_REQUEST=YES python3 scripts/preflight.py \
    --start 2017-01-01 --end 2026-12-31 --out out/archive/preflight.json

# run, and resume with the identical command
caffeinate -is scripts/run_archive.sh 2>&1 | tee -a out/archive/run.log

# verify
python3 scripts/check_summary.py out/archive/summary.csv \
    --expect out/archive/preflight.json \
    --baseline archive/legacy_pipeline/ice-final/summary_test.csv

# publish
cd ~/Developer/climate-dashboard/data-pipeline
python3 refresh_fjord_season.py --clean-only \
    --raw ~/Developer/uummannaq-ice-from-space/out/archive/summary.csv
```

Or through the Makefile: `make preflight`, `make archive`, `make verify`.
