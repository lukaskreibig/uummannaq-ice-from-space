# Handing a finished reprocess to the story

What has to happen between `out/archive/summary.csv` existing and SCHMELZPUNKT
serving the new numbers, and which published sentences will be wrong until
somebody rewrites them.

Everything below was read out of the code, not assumed. File and line
references are to the two repositories as of 2026-08-04.

---

## 1. The two CSVs are not the same file

This is the part that was broken and is worth stating first.

| file | one row per | columns |
|---|---|---|
| `out/archive/summary.csv` | **scene** | `tile_id, timestamp, solid_px … solid_pct, light_pct … edge_gap` |
| `data-pipeline/data/summary_test_cleaned.csv` | **day** | `date, year, doy, frac, frac_filled, frac_smooth` |

The classifier can only write the first. It has never heard of a day-of-year
climatology or a centred rolling mean.

`refresh_fjord_season.py` used to hand the classifier
`--csv-name summary_test_cleaned.csv`, so scene rows were appended to the file
that `update_fjord_data.py` then read as daily rows. Nothing in either repo
performed the conversion; the recipe lived only in
`archive/legacy_pipeline/ice-final/ice_classification_clean_updated (1).ipynb`.

It now lives in `clean_series()` in
`climate-dashboard/data-pipeline/refresh_fjord_season.py`, and it reproduces
the published `summary_test_cleaned.csv` from the published raw archive
exactly: 3047 rows, `diff` reports no difference at all.

The recipe, for the record:

1. `frac = solid_pct + light_pct` per scene, averaged over the scenes of a day.
2. reindex to every calendar day between the first and last scene.
3. gaps of 14 days or fewer are interpolated linearly; longer gaps fall back to
   the day-of-year mean across all years; outside day 45 to 180 nothing is
   filled.
4. two passes of a centred 7-day mean, which is a 13-day triangular kernel.
5. `frac_smooth` is blanked outside day 45 to 180.

---

## 2. The chain, file by file

```
out/archive/summary.csv                        the classifier's output
        |
        |  refresh_fjord_season.py --clean-only --raw <that file>
        |     clean_series()                   scenes -> days
        v
data-pipeline/data/summary_test_cleaned.csv    the series
        |
        +--> copied to frontend/public/data/summary_test_cleaned.csv
        |       the download the methodology box links to as
        |       /data/summary_test_cleaned.csv
        |
        +--> update_fjord_data.py, if DATABASE_URL is set
                TRUNCATE + reload of five tables:
                  fjord_daily, fjord_season_band, fjord_spring_anomaly,
                  fjord_mean_fraction, fjord_freeze_breakup
                v
        GET /uummannaq  (backend/main.py:795)
```

`GET /uummannaq` picks its source in this order:

1. **Postgres**, if `DATABASE_URL` or `DATABASE_PUBLIC_URL` resolves
   (`backend/main.py:797`). Reads the five tables above.
2. **`backend/data/fjord_data.json`**, if that file exists
   (`backend/main.py:876`). Served verbatim.
3. **The CSV**, via `_build_fjord_payload_from_csv()`
   (`backend/main.py:494`), searching three paths in order
   (`backend/main.py:57`):
   `backend/data/`, `data-pipeline/data/`, `frontend/public/data/`.

### The trap

`backend/data/fjord_data.json` exists on this machine (241 KB, untracked) and
**no script in either repository writes it**. It sits in front of the CSV. If
the database is unreachable, updating the CSV changes nothing that the API
serves, and the story keeps showing the old numbers with no error anywhere.

`refresh_fjord_season.py` now warns when that file is present. Delete it, or
regenerate it, before concluding the update did not work.

### Caching

There is no payload cache. The only `lru_cache` in `backend/main.py` is
`_engine()` at line 924, which caches the SQLAlchemy engine, not any data. Both
the CSV and the database are read per request. Restarting the API is not
required after a data change; deleting `fjord_data.json` is.

---

## 3. The command

```bash
cd ~/Developer/climate-dashboard/data-pipeline
python3 refresh_fjord_season.py --clean-only \
    --raw ~/Developer/uummannaq-ice-from-space/out/archive/summary.csv
```

It prints how far every season moved before it overwrites anything:

```
[INFO] against the current series: 1213 shared days,
       mean shift +0.0000, largest 0.0000
         was     now  delta
year
2017  0.5904  0.5904    0.0
...
```

Flags: `--no-public-copy` to skip the `frontend/public/data` copy,
`--skip-aggregate` to skip the database load, `--csv` to write the series
somewhere else while you look at it first.

The normal in-season path is unchanged and now writes the two files correctly:

```bash
python3 refresh_fjord_season.py            # classify what is missing, clean, load
python3 refresh_fjord_season.py --dry-run  # just show the windows
```

---

## 4. Two constants that are already out of step

Both live in `data-pipeline/update_fjord_data.py`, which serves the database
path, and both disagree with `backend/main.py`, which serves the CSV path. The
reprocess does not cause either, but it will be the moment somebody notices.

| | `update_fjord_data.py` | `backend/main.py` |
|---|---|---|
| fjord area for the spring anomaly | `FJORD_KM2 = 3450` (line 22) | `FJORD_KM2 = 253.5` (line 96), from the land mask |
| early / late year groups | `EARLY_YRS`, `LATE_YRS` frozen lists (lines 20-21) | derived from `FJORD_LATE_START_YEAR = 2021` (line 71) |

The area is a factor of 13.4 apart, and the comment at `backend/main.py:92`
says the AOI is 14.3 by 17.8 km, so 257 is the right one. The frozen year lists
stop at 2025, so a 2026 season would silently vanish from
`fjord_season_band`, `fjord_spring_anomaly` and `fjord_mean_fraction` on the
database path while appearing on the CSV path.

`_attach_fjord_meta` also hardcodes `"baselineYears": "2017-2020 vs
2021-2025"` (`backend/main.py:452`), which the frontend shows as the
comparison label.

---

## 5. Published numbers that will need re-checking

All of these were computed from the current
`data-pipeline/data/summary_test_cleaned.csv` using the backend's own formulas,
so they are what the story shows today. Every one of them is a function of the
classifier output and will move.

### Derived at request time, so they update themselves

| number | current value | where it is computed |
|---|---|---|
| season loss, early vs late | **32.4 %** | `backend/main.py:596` (CSV) and `:840` (database) |
| mean ice fraction per season | 2017 0.5904 · 2018 0.6158 · 2019 0.4263 · 2020 0.5160 · 2021 0.2194 · 2022 0.5118 · 2023 0.3260 · 2024 0.4490 · 2025 0.3235 | `backend/main.py:560` |
| freeze and breakup day, threshold 0.15 | 2017 50/156 · 2018 45/154 · 2019 45/139 · 2020 45/145 · 2021 45/119 · 2022 45/159 · 2023 46/122 · 2024 45/157 · 2025 45/129 | `backend/main.py:571` |
| spring anomaly per year | 2021 is the largest negative | `backend/main.py:556`, scaled by `FJORD_KM2` |
| the StatChip on the "When Normal Shifts" scene | reads `seasonLossPct` | `frontend/components/scenes/scenesConfig.tsx:849` |
| the shift chip inside the breakup chart | reads `summary.shiftDays` | `frontend/components/Rechart/BreakupTimingChart.tsx:106` |

### Hardcoded, so somebody has to retype them

| number | current text | file and line |
|---|---|---|
| **−11 days** breakup shift | `<StatChip value={11} prefix="−" …>` | `frontend/components/scenes/scenesConfig.tsx:918` |
| "about eleven days earlier" | scene copy | `frontend/locales/en.json:158`, `de.json:158` ("rund elf Tage früher") |
| "about eleven days earlier on average" | chart aria summary | `en.json:397`, `de.json:397` |
| "32 % less ice" | unused string, but still there | `en.json:140`, `de.json:140` |
| "about 32 percent lower" | chart aria summary | `en.json:398`, `de.json:398` |
| NDSI 0.52 · 0.31 to 0.52 · NDWI 0.25 | methodology box | `en.json:94`, `de.json:94` |
| "17.3 % of the measured days" under more than 80 % cloud, "2 % ice on average" | methodology box | `en.json:94`, `de.json:94` |
| "69.3 % of the days have a scene of their own" | methodology box | `en.json:94`, `de.json:94` |
| "2017 is the thinnest season at 39 days out of 137" | methodology box | `en.json:94`, `de.json:94` |
| "since 2019 no season falls below 68.6 %" | methodology box | `en.json:94`, `de.json:94` |
| ceiling "91 %", land "9 %" | scene copy and methodology box | `en.json:91` and `:94`, `de.json:91` and `:94` |
| "Ice fraction, 91 % maximum" | chart legend | `en.json:426`, `de.json:426` |
| "2017 to 2025" year spans | breakup aria summary, chart titles | `en.json:397`, `charts.earlyLateSeason.*` |

The measured values behind the four methodology bullets, recomputed today from
the published archive:

| the copy says | measured now |
|---|---|
| 17.3 % of days under more than 80 % cloud | **17.1 %** (145 of 847 observed days in the window) |
| those days report 2 % ice | **2.0 %** |
| 69.3 % of window days have their own scene | **69.8 %** (847 of 1213) |
| 2017 the thinnest at 39 of 137 | **39** observed days, of 131 rows in the window |
| no season below 68.6 % since 2019 | **68.4 %** (2023) |

They are already a little adrift. After the reprocess they will be a lot
adrift, and the cloud numbers especially: the whole point of the fix is that
cloud and water classification changes.

### The cloud-mask sentence is now simply false

`en.json:94` and `de.json:94` say:

> Cloud mask: a U-Net trained on the CloudSEN12 taxonomy outputs four classes.
> **Exactly one of them is used, dense cloud**, at probability 0.5 and above,
> then morphologically closed. **Thin cloud and cloud shadow stay unflagged.**

`processing.compute_cloud_mask` no longer does that. It takes the argmax over
all four CloudSEN12 classes and masks everything that is not `CLEAR`, so thin
cloud and cloud shadow **are** flagged now. There is no 0.5 probability
threshold left either. Both language versions describe a pipeline that no
longer exists, and the "thin cloud and cloud shadow pass straight into the
ice/water decision" bullet further down the same string contradicts the code
as well.

### The threshold sentence is the one that matters most

`en.json:94` and `de.json:94` state the published thresholds as numbers:
`Solid ice NDSI > 0.52 · thin or wet ice 0.31 to 0.52 · open water NDWI >
0.25`. Those were tuned on the biased reflectances. Whatever the re-derivation
produces has to be copied into both locale files by hand, in both languages, or
the methodology box describes a pipeline that no longer exists.

The same sentence says "day 45 to 181 of the year". The code uses 45 to 180
(`backend/main.py:63`, `refresh_fjord_season.py`). Off by one, in both
languages, already.

---

## 6. Checklist

```
[ ] thresholds re-derived and written into config/baseline.yaml
[ ] scripts/preflight.py run, inventory saved
[ ] scripts/run_archive.sh finished, exit 0
[ ] scripts/check_summary.py: ACCEPT or an explained REVIEW
[ ] refresh_fjord_season.py --clean-only, per-season shift table read
[ ] backend/data/fjord_data.json deleted or regenerated
[ ] frontend/public/data/summary_test_cleaned.csv refreshed (the script does it)
[ ] update_fjord_data.py FJORD_KM2 and the frozen year lists reconciled
[ ] every hardcoded number in section 5 rechecked, in en.json AND de.json
[ ] scenesConfig.tsx:918 StatChip value={11} recomputed
```
