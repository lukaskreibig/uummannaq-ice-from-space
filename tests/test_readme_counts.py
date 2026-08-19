"""The README counts things, and counting rots.

An audit of this repository found four stale counts in one file: 28 scripts on
one line against 33 on another, 851 lines for a document that had grown to 1034,
17 table rows described where the table had 22, and two errors announced above a
list of five. Every one of them was correct when written. Each was overtaken by a
later commit that had no reason to look at the sentence describing it.

Prose about the filesystem is a claim like any other, so it gets a gate like any
other. These tests fail when the README stops describing the repository, which is
the only moment at which anyone would want to know.

Where a count would rot on any edit at all, the README says "over N" instead and
the test checks the bound rather than the value. That is deliberate: a number
nobody can keep true is worse than a bound anyone can.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()


def test_the_script_count_is_stated_once_and_is_right() -> None:
    """Two lines used to give different counts for the same directory."""
    actual = len(list((ROOT / "scripts").glob("*.py")))
    claimed = {int(n) for n in re.findall(r"(\d+) scripts", README)}
    assert claimed == {actual}, (
        f"README claims {sorted(claimed)} scripts, scripts/ holds {actual}"
    )


def test_the_artefact_count_is_right() -> None:
    actual = len(list((ROOT / "archive/reprocessed_2026").iterdir()))
    claimed = {int(n) for n in re.findall(r"(\d+) artefacts", README)}
    assert claimed == {actual}, (
        f"README claims {sorted(claimed)} artefacts, the archive holds {actual}"
    )


def test_the_question_table_is_described_by_its_own_arithmetic() -> None:
    """Six rows moved the headline and the prose names the remainder."""
    rows = len(re.findall(r"^\| .*\.py`", README, flags=re.MULTILINE))
    words = {
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
    }
    match = re.search(r"The other (\w+) settled", README)
    assert match, "the sentence describing the rest of the table has moved"
    remainder = words[match.group(1)]
    assert remainder + 6 == rows, (
        f"the table has {rows} rows, the prose accounts for {remainder} + 6"
    )


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        (r"over (\d+) lines\s+documentation", "docs"),
        (r"over (\d+) lines of what the method cannot do", "docs/limitations.md"),
    ],
)
def test_the_documentation_bounds_still_hold(pattern: str, path: str) -> None:
    """A bound rather than a value, because these grow on almost every commit."""
    target = ROOT / path
    files = sorted(target.glob("*.md")) if target.is_dir() else [target]
    actual = sum(len(f.read_text().splitlines()) for f in files)
    match = re.search(pattern, README)
    assert match, f"the README no longer states a bound for {path}"
    bound = int(match.group(1))
    assert actual >= bound, (
        f"README claims over {bound} lines for {path}, found {actual}"
    )


def test_the_error_count_agrees_between_readme_and_the_log() -> None:
    """The log's heading and the README's sentence gave three different numbers."""
    log = (ROOT / "docs/investigation-log.md").read_text()
    section = log.split("## Five errors of my own")[1].split("\n## ")[0]
    listed = len(re.findall(r"^\*\*", section, flags=re.MULTILINE))
    assert listed == 5, f"the section lists {listed} errors under a heading saying five"
    assert "five mistakes of my own" in README


def test_the_test_count_is_right() -> None:
    """It drifted, and it drifts silently: nothing fails when a test is added.

    The count includes this test, which is why writing it moved the number by
    one. That is the right way round: the README quotes what a reader gets from
    running the suite, and this test is part of the suite.

    Counted by collecting the suite rather than by grepping for `def test_`,
    because parametrised cases and class methods make those two different
    numbers and the README quotes the one a reader would get from `pytest`.
    """
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", str(ROOT / "tests")],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    match = re.search(r"(\d+) tests? collected", result.stdout)
    assert match, (
        f"could not read the collected count from pytest:\n{result.stdout[-400:]}"
    )
    actual = int(match.group(1))
    claimed = {int(n) for n in re.findall(r"(\d+) tests", README)}
    assert claimed == {actual}, (
        f"README claims {sorted(claimed)} tests, the suite collects {actual}"
    )
