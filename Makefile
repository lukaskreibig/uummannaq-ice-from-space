.PHONY: install dev lint lint-fix format test typecheck precommit docs \
        preflight archive verify publish

# The scripts that matter for a run. scripts/scrape_satellite_images.py is
# deliberately not here: it is an ad-hoc DMI scraper that starts a fifteen-year
# download at import time and has never been linted.
RUN_SCRIPTS := scripts/check_summary.py scripts/preflight.py scripts/watch_archive.py \
	scripts/validate_sar.py \
               scripts/derive_thresholds.py

# ---------------------------------------------------------------- development

install:
	python3 -m pip install -e .

dev:
	python3 -m pip install -e ".[dev,test,docs]"
	pre-commit install

lint:
	ruff check src tests $(RUN_SCRIPTS)

# Was written as `lint fix:`, which declares two targets sharing one recipe and
# silently overrode the real `lint` above. make printed a warning and then ran
# --fix whenever anyone typed `make lint`.
lint-fix:
	ruff check src tests $(RUN_SCRIPTS) --fix

format:
	ruff format src tests $(RUN_SCRIPTS)

typecheck:
	mypy src/uummannaq_ice

test:
	pytest --cov=uummannaq_ice --cov-report=term-missing

precommit:
	pre-commit run --all-files

docs:
	mkdocs serve

# ------------------------------------------------------------------- the run
#
# See docs/reprocessing-runbook.md. The three targets are meant to be run in
# order, and every one of them is safe to run twice.

ARCHIVE_OUT ?= out/archive
ARCHIVE_FIRST_YEAR ?= 2017
ARCHIVE_LAST_YEAR ?= $(shell date +%Y)
PUBLISHED_CSV ?= archive/legacy_pipeline/ice-final/summary_test.csv

# Metadata only, no pixels. Roughly 220 seconds for the full range.
preflight:
	AWS_NO_SIGN_REQUEST=YES python3 scripts/preflight.py scripts/watch_archive.py \
		--start $(ARCHIVE_FIRST_YEAR)-01-01 \
		--end $(ARCHIVE_LAST_YEAR)-12-31 \
		--out $(ARCHIVE_OUT)/preflight.json

# The overnight job. Resumable: re-run this exact target to continue.
archive:
	caffeinate -is scripts/run_archive.sh $(ARCHIVE_FIRST_YEAR) $(ARCHIVE_LAST_YEAR) \
		2>&1 | tee -a $(ARCHIVE_OUT)/run.log

# Exits non-zero if any gate failed.
verify:
	python3 scripts/check_summary.py $(ARCHIVE_OUT)/summary.csv \
		--expect $(ARCHIVE_OUT)/preflight.json \
		--baseline $(PUBLISHED_CSV)

# Hands the result to the story. See docs/handoff-to-story.md.
publish:
	cd ../climate-dashboard/data-pipeline && python3 refresh_fjord_season.py \
		--clean-only --raw $(abspath $(ARCHIVE_OUT))/summary.csv
