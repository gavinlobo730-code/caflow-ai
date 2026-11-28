"""Every test file belongs to one part of the product, derived and never listed, and `--subsystem` runs that part (POST-A-191).

`tests/_subsystems.py` says what the grouping is for and why the 1,800 files were not moved into folders (a path one level wrong silently
empties a guard; 108 applied migrations cite tests by path and may not be edited; the required real-Postgres job collects with a one-level
glob). This file holds the grouping to what it promises:

  - every test file gets exactly one of the named subsystems, and the leftover (`other`) stays small, so the rule goes on meaning something
    as files are added: a new subject that the rules do not reach shows up here as a failing ceiling, and the answer is a line in RULES;
  - no subsystem is empty, and none has swallowed the suite;
  - the option selects by that rule, refuses a name that is not one (a typo that selected nothing would read as a clean run), and does
    NOTHING when it is not given, which is how the required checks run.
"""
from __future__ import annotations

import collections
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import _subsystems as S
from tests import conftest

TESTS = Path(__file__).resolve().parent


def _census() -> collections.Counter:
    return collections.Counter(S.subsystem_of(str(f)) for f in S.files_of(TESTS))


def test_every_test_file_gets_one_named_subsystem_and_the_leftover_stays_small():
    files = S.files_of(TESTS)
    assert len(files) >= 1500, f"only {len(files)} test files were found: the census is looking in the wrong place"
    census = _census()
    assert set(census) <= set(S.SUBSYSTEMS), sorted(set(census) - set(S.SUBSYSTEMS))
    assert sum(census.values()) == len(files)
    leftover = census["other"] / len(files)
    assert leftover <= 0.08, (
        f"{census['other']} of {len(files)} test files ({leftover:.0%}) belong to no subsystem. Measured 5% on 28-11-2026. A new subject needs a "
        "word or a module in tests/_subsystems.RULES; do not raise this ceiling to make room.")


def test_no_subsystem_is_empty_and_none_has_swallowed_the_suite():
    census = _census()
    total = sum(census.values())
    for name in S.SUBSYSTEMS:
        assert census[name] >= 20, f"{name} holds {census[name]} files: its rule matches almost nothing, or the name is not needed"
        assert census[name] <= 0.2 * total, f"{name} holds {census[name]} of {total} files: a word in its rule is too common to mean anything"


@pytest.mark.parametrize("name,imports,expected", [
    ("a_payslip_shows_its_working", set(), "payroll"),
    ("gstr3b_table_4", set(), "gst"),
    ("the_26q_deductor_block_is_read", set(), "tds"),
    ("a_capital_gain_asks_what_it_cannot_derive", set(), "income_tax"),
    ("bank_matching", set(), "banking"),
    ("something_with_no_telling_name", {"domain.payroll.statutory"}, "payroll"),       # what it imports says so when its name does not
    ("something_with_no_telling_name", set(), "other"),
    ("500_something_with_no_telling_name_pg", set(), "database"),                      # a real-Postgres file no rule reaches
    ("a_payroll_run_posts_its_journal", set(), "payroll"),                             # two subjects: the earlier, narrower rule takes the tie
])
def test_the_rule_reads_the_name_first_and_the_imports_second(name, imports, expected):
    assert S.subsystem_from(name, imports) == expected


def test_a_word_in_the_name_outweighs_an_import():
    """A GST test that has to reach the ledger to post an invoice is still a GST test."""
    assert S.subsystem_from("gstr1_is_built_from_the_books", {"services.phase2_journal_service"}) == "gst"


# ── the option ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _configured(option):
    config = SimpleNamespace(getoption=lambda name, default=None: option)
    conftest.pytest_configure(config)
    return config


def _left_out(option) -> tuple[list[Path], list[Path]]:
    """(the files collected, the files left out) for one value of `--subsystem`."""
    config = _configured(option)
    kept, dropped = [], []
    for f in S.files_of(TESTS):
        (dropped if conftest.pytest_ignore_collect(f, config) else kept).append(f)
    return kept, dropped


def test_without_the_option_no_file_is_left_out_which_is_how_the_required_checks_run():
    kept, dropped = _left_out(None)
    assert len(kept) == len(S.files_of(TESTS)) and dropped == []
    config = _configured(None)
    assert conftest.pytest_ignore_collect(TESTS / "conftest.py", config) is None
    assert conftest.pytest_ignore_collect(TESTS, config) is None


def test_the_option_keeps_the_files_of_that_subsystem_and_leaves_out_the_rest():
    kept, dropped = _left_out("tds")
    assert kept and dropped
    assert {S.subsystem_of(str(f)) for f in kept} == {"tds"}
    assert all(S.subsystem_of(str(f)) != "tds" for f in dropped)
    assert len(kept) + len(dropped) == len(S.files_of(TESTS))
    both, _ = _left_out("tds, gst")
    assert {S.subsystem_of(str(f)) for f in both} == {"tds", "gst"}


def test_the_option_leaves_helpers_and_directories_alone():
    """Only a test file is ever left out: the shared fixtures, the helpers and the folders must still be read, or the kept tests cannot run."""
    config = _configured("tds")
    for path in (TESTS / "conftest.py", TESTS / "e2e_harness.py", TESTS / "_subsystems.py", TESTS, TESTS / "fixtures"):
        assert conftest.pytest_ignore_collect(path, config) is None, path


@pytest.mark.parametrize("option", ["payrol", "tds,nonsense", ",", " ", ""])
def test_a_name_that_is_not_a_subsystem_is_refused_before_anything_is_collected(option):
    with pytest.raises(pytest.UsageError):
        _configured(option)


def test_the_listing_script_and_the_option_use_the_one_rule():
    """Two copies of the rule would drift: the script must import it, and hold no word list of its own."""
    script = (TESTS.parent / "scripts" / "tests_by_subsystem.py").read_text(encoding="utf-8")
    assert "from tests._subsystems import" in script
    assert "RULES" not in script.replace("tests/_subsystems.RULES", "")
