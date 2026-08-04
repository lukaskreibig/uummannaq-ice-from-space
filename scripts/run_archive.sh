#!/usr/bin/env bash
#
# Reprocess the Uummannaq archive, one season at a time, and survive the night.
#
#   scripts/run_archive.sh                      # 2017 to the current year
#   scripts/run_archive.sh 2019 2021            # just those seasons
#   OUT=out/rerun scripts/run_archive.sh        # somewhere else
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
trap 'interrupted=1; echo; echo "interrupted. re-run this script to resume."; exit 130' INT TERM

started_at=$(date +%s)
echo "reprocess          $FIRST_YEAR to $LAST_YEAR, $WINDOW_START to $WINDOW_END of each year"
echo "device             $DEVICE"
echo "output             $summary_path"
echo "resume            $( [ -f "$summary_path" ] && echo "appending to $(($(wc -l < "$summary_path") - 1)) existing rows" || echo "fresh file" )"
echo

failed_years=()
for (( year=FIRST_YEAR; year<=LAST_YEAR; year++ )); do
  log="$OUT/logs/${year}.log"
  ok=0
  for (( attempt=1; attempt<=ATTEMPTS; attempt++ )); do
    echo "[$(date +%H:%M:%S)] season $year, attempt $attempt of $ATTEMPTS -> $log"
    "$CLI" \
      --start-date "${year}-${WINDOW_START}" \
      --end-date "${year}-${WINDOW_END}" \
      --output-dir "$OUT" \
      --csv-name "$CSV_NAME" \
      --device "$DEVICE" \
      --log-level INFO \
      >> "$log" 2>&1
    status=$?
    if [ "$interrupted" = "1" ]; then exit 130; fi
    if [ $status -eq 0 ]; then
      ok=1
      rows=$(( $(wc -l < "$summary_path") - 1 ))
      echo "[$(date +%H:%M:%S)] season $year done, $rows rows in the CSV so far"
      break
    fi
    echo "[$(date +%H:%M:%S)] season $year exited $status. tail of $log:"
    tail -n 5 "$log" | sed 's/^/    /'
    # A failed attempt still wrote every scene it finished, so the retry is
    # cheap: it re-queries the catalogue and skips straight to the remainder.
    sleep $(( attempt * 30 ))
  done
  if [ $ok -eq 0 ]; then
    echo "[$(date +%H:%M:%S)] season $year gave up after $ATTEMPTS attempts"
    failed_years+=("$year")
  fi
done

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
