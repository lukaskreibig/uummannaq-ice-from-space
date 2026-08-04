#!/usr/bin/env bash
#
# Reprocess the Uummannaq archive, one season at a time, and survive the night.
#
#   scripts/run_archive.sh                      # 2017 to the current year
#   scripts/run_archive.sh 2019 2021            # just those seasons
#   OUT=/Volumes/disk/archive scripts/run_archive.sh   # somewhere else
#   JOBS=4 scripts/run_archive.sh               # four seasons at once
#
# JOBS, and why more than one is worth it here:
#
#   The run moves about 9 MB/s, measured. One curl stream against the same
#   bucket reaches 30 MB/s and four reach 127, so the line is not the limit.
#   What costs the time is round trips: thirteen bands, each read as windows,
#   one scene after another. Seasons are independent, so running several at
#   once fills the wait.
#
#   With JOBS=1 this writes into one summary.csv exactly as before, which is
#   the path that has been tested. With JOBS>1 each season gets its own
#   summary_<year>.csv, because two processes appending to one file would
#   interleave rows, and they are merged at the end with a duplicate check.
#
# Why per season and not one long invocation:
#
#   * The STAC query for 2017 to 2026 takes 220 seconds, measured. That is paid
#     again on every restart. One season takes a few seconds.
#   * A crash inside one season costs at most that season's remaining scenes.
#   * The default window skips the dark half of the year. The catalogue offers
#     1804 scenes across the whole calendar; only 1101 of them fall between
#     1 February and 15 July, and the story throws the rest away (the backend
#     only reads day of year 45 to 180). That is 15 hours of compute not spent.
#
# Resume is the CSV itself. Every season writes into the same summary.csv and
# the writer skips any (tile_id, timestamp) already in it, so re-running this
# script after a crash picks up exactly where it stopped. Nothing already
# downloaded is downloaded again.
#
set -uo pipefail

FIRST_YEAR="${1:-2017}"
LAST_YEAR="${2:-$(date +%Y)}"

OUT="${OUT:-out/archive}"
CSV_NAME="${CSV_NAME:-summary.csv}"
WINDOW_START="${WINDOW_START:-02-01}"
WINDOW_END="${WINDOW_END:-07-15}"
ATTEMPTS="${ATTEMPTS:-4}"
CLI="${CLI:-uummannaq-ice}"
# Pinned, not auto-selected. compute_cloud_mask runs inference under autocast on
# mps and cuda but not on cpu, and the reduced precision flips the cloud mask on
# up to 0.22 per cent of cells. Leaving the device implicit also means the same
# command writes a different archive on a machine without a GPU. cpu inference
# costs about 0.17 s per scene, which is nothing next to the download.
DEVICE="${DEVICE:-cpu}"
# Seasons to process concurrently. 1 keeps the original single-file behaviour.
JOBS="${JOBS:-1}"

# Anonymous access to the Sentinel-2 public bucket. Without it every read is a
# 403 and the run produces an empty CSV in about a minute.
export AWS_NO_SIGN_REQUEST=YES
# Otherwise a killed run loses whatever python was still holding in its buffer.
export PYTHONUNBUFFERED=1

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if ! command -v "$CLI" >/dev/null 2>&1; then
  echo "error: '$CLI' is not on PATH." >&2
  echo "       pip install -e .   (or activate the venv that has it)" >&2
  exit 127
fi

mkdir -p "$OUT/logs"
summary_path="$OUT/$CSV_NAME"

interrupted=0

# Ctrl-C has to reach the season jobs, not just this shell. With JOBS>1 the
# seasons run as background subshells with a python child each, and a trap that
# only sets a flag leaves all of them running while the outer script exits: the
# terminal comes back, the archive keeps being written, and the next run appends
# to a file that something else still has open.
stop_children() {
  interrupted=1
  local pid
  for pid in $(jobs -p); do
    pkill -TERM -P "$pid" 2>/dev/null
    kill -TERM "$pid" 2>/dev/null
  done
  pkill -TERM -P $$ 2>/dev/null
}
trap 'stop_children; echo; echo "interrupted. re-run this script to resume."; exit 130' INT TERM

started_at=$(date +%s)
echo "reprocess          $FIRST_YEAR to $LAST_YEAR, $WINDOW_START to $WINDOW_END of each year"
echo "device             $DEVICE"
echo "output             $summary_path"
echo "resume            $( [ -f "$summary_path" ] && echo "appending to $(($(wc -l < "$summary_path") - 1)) existing rows" || echo "fresh file" )"
echo

failed_years=()

# One season, retried. Writes to $2 so the parallel path can give each its own.
run_season() {
  local year="$1" csv="$2"
  local log="$OUT/logs/${year}.log"
  local attempt status
  for (( attempt=1; attempt<=ATTEMPTS; attempt++ )); do
    echo "[$(date +%H:%M:%S)] season $year, attempt $attempt of $ATTEMPTS -> $log"
    "$CLI" \
      --start-date "${year}-${WINDOW_START}" \
      --end-date "${year}-${WINDOW_END}" \
      --output-dir "$OUT" \
      --csv-name "$csv" \
      --device "$DEVICE" \
      --log-level INFO \
      >> "$log" 2>&1
    status=$?
    if [ "$interrupted" = "1" ]; then return 130; fi
    if [ $status -eq 0 ]; then
      echo "[$(date +%H:%M:%S)] season $year done"
      return 0
    fi
    echo "[$(date +%H:%M:%S)] season $year exited $status. tail of $log:"
    tail -n 5 "$log" | sed 's/^/    /'
    # A failed attempt still wrote every scene it finished, so the retry is
    # cheap: it re-queries the catalogue and skips straight to the remainder.
    sleep $(( attempt * 30 ))
  done
  return 1
}

if [ "$JOBS" -le 1 ]; then
  for (( year=FIRST_YEAR; year<=LAST_YEAR; year++ )); do
    if run_season "$year" "$CSV_NAME"; then
      echo "[$(date +%H:%M:%S)] $(( $(wc -l < "$summary_path") - 1 )) rows in the CSV so far"
    else
      [ "$interrupted" = "1" ] && exit 130
      failed_years+=("$year")
    fi
  done
else
  echo "running $JOBS seasons at a time, one CSV each, merged at the end"
  declare -a pids=() pid_years=()
  for (( year=FIRST_YEAR; year<=LAST_YEAR; year++ )); do
    while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do sleep 2; done
    [ "$interrupted" = "1" ] && break
    run_season "$year" "summary_${year}.csv" &
    pids+=($!); pid_years+=("$year")
  done
  for i in "${!pids[@]}"; do
    wait "${pids[$i]}" || failed_years+=("${pid_years[$i]}")
  done
  [ "$interrupted" = "1" ] && exit 130

  echo
  echo "merging per-season files into $summary_path"
  python3 - "$OUT" "$CSV_NAME" <<'PY'
import csv, sys, pathlib
out = pathlib.Path(sys.argv[1]); target = out / sys.argv[2]
parts = sorted(out.glob("summary_[0-9][0-9][0-9][0-9].csv"))
if not parts:
    print("  no per-season files found"); raise SystemExit(1)
header, rows, seen, dupes = None, [], set(), 0
for part in parts:
    with part.open(newline="") as fh:
        reader = csv.reader(fh)
        head = next(reader)
        if header is None:
            header = head
        elif head != header:
            print(f"  FAIL {part.name} has a different column layout"); raise SystemExit(1)
        n = 0
        for row in reader:
            key = (row[0], row[1])          # tile_id, timestamp
            if key in seen:
                dupes += 1; continue
            seen.add(key); rows.append(row); n += 1
    print(f"  {part.name}: {n} rows")
rows.sort(key=lambda r: (r[1], r[0]))
with target.open("w", newline="") as fh:
    writer = csv.writer(fh); writer.writerow(header); writer.writerows(rows)
print(f"  wrote {len(rows)} rows to {target}" + (f", {dupes} duplicates dropped" if dupes else ""))
PY
fi

elapsed=$(( $(date +%s) - started_at ))
printf '\nfinished in %dh %dm\n' $(( elapsed / 3600 )) $(( (elapsed % 3600) / 60 ))
echo "rows in $summary_path: $(( $(wc -l < "$summary_path") - 1 ))"

if [ ${#failed_years[@]} -gt 0 ]; then
  echo "seasons that never completed: ${failed_years[*]}"
  echo "re-run this script to retry only what is missing."
  exit 1
fi

echo
echo "next: python3 scripts/check_summary.py $summary_path \\"
echo "        --expect $OUT/preflight.json \\"
echo "        --baseline archive/legacy_pipeline/ice-final/summary_test.csv"
