"""`docs/architecture/07-gst-engine.md` names things that exist, where they are, and states the figures the code holds.

WHAT WAS WRONG
    The architecture note was written when the GST engine was one builder and one router, and it was never brought
    forward. It sent a reader to `_compute_line_gst (routers/sales_invoices.py)` (the function moved to
    `domain/sales/line_tax.py` and the router keeps an alias), called the B2CL limit and the HSN tiers "hardcoded
    INR constants" with the figure ₹2.5 lakh (the limit forked to ₹1 lakh on 01-08-2024 and is chosen by the
    invoice's date; HSN digits are two notification tables chosen by period), said GSTIN was "Regex enforced"
    (the check digit is `gstin.problem_with`), described Rule 36(4) as a cap on a per-head sum (it is per document
    now), and said the tests "return 503 in the unit environment" (they run in mock mode and pass). Nothing read the
    file, so nothing noticed.

WHAT THIS HOLDS
    * every path the note names in backticks exists (a bare module name is read as `domain/gst/<name>`, which the
      note says in its introduction), so a moved or renamed module fails here and not in a reader's editor;
    * an identifier the note puts beside a path, in the form `name` (`path`), is defined in that path;
    * the two B2CL figures and the date the lower one starts, as the note states them, equal the classifier's;
    * the note names the module `compute_line_gst` actually lives in;
    * the one sentence about the test environment that was false is gone.

    A prose rule has no generic detector, so this does not say the note is right, only that what it names exists
    and that the figures it quotes are the code's.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from domain.gst import classifier

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]
DOC = REPO / "docs" / "architecture" / "07-gst-engine.md"

pytestmark = pytest.mark.skipif(not DOC.is_file(), reason="the architecture note is not in this checkout")

#: Roots a path with a directory in it may resolve under. A bare module name resolves under `domain/gst/` only.
ROOTS = (API, REPO / "apps" / "web", REPO)
PATH_TOKEN = re.compile(r"`([A-Za-z0-9_./\-]+\.(?:py|ts|tsx|json|sql))`")
NAME_AND_PATH = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)` \(`([A-Za-z0-9_./\-]+\.(?:py|ts|tsx))`\)")


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def _flat() -> str:
    return re.sub(r"\s+", " ", _doc())


def _resolve(token: str) -> Path | None:
    if "/" not in token:
        candidate = API / "domain" / "gst" / token
        return candidate if candidate.is_file() else None
    for root in ROOTS:
        candidate = root / token
        if candidate.is_file():
            return candidate
    return None


def test_the_note_names_enough_paths_for_the_check_below_to_mean_something():
    assert len(set(PATH_TOKEN.findall(_doc()))) >= 25, (
        "the note names almost no files, so 'every path it names exists' would pass over nothing")


def test_every_path_the_note_names_exists():
    missing = sorted({t for t in PATH_TOKEN.findall(_doc()) if _resolve(t) is None})
    assert not missing, (
        "docs/architecture/07-gst-engine.md names files that do not exist (a bare module name is read as "
        "domain/gst/<name>): " + ", ".join(missing))


def test_an_identifier_the_note_puts_beside_a_path_is_defined_there():
    pairs = NAME_AND_PATH.findall(_doc())
    assert len(pairs) >= 3, "the note no longer says where any identifier lives; the check below would pass over nothing"
    wrong = []
    for name, token in pairs:
        path = _resolve(token)
        if path is None:
            continue          # reported by the existence test; one failure per cause
        body = path.read_text(encoding="utf-8")
        if not re.search(rf"(?:\bdef |\bclass |^\s*(?:export )?(?:const |function )?){re.escape(name)}\b", body, re.M):
            wrong.append(f"`{name}` is not defined in {token}")
    assert not wrong, "; ".join(wrong)


def test_the_note_names_the_module_the_line_tax_lives_in():
    """`_compute_line_gst` was in `routers/sales_invoices.py` when the note was written. It MOVED to
    `domain/sales/line_tax.py` (the router keeps an alias), so a reader following the old pointer found an alias."""
    flat = _flat()
    assert (API / "domain" / "sales" / "line_tax.py").is_file(), "premise: the line-tax module exists"
    assert "domain/sales/line_tax.py" in flat, "the note does not name domain/sales/line_tax.py"
    assert not re.search(r"`_compute_line_gst` \(`routers/sales_invoices\.py`\)", flat), (
        "the note still says the line tax lives in the sales-invoices router")


def _lakh_to_paise(lakh: str) -> int:
    return int(Decimal(lakh) * 1_00_000 * 100)


def test_the_b2cl_figures_the_note_states_are_the_classifiers():
    """Rule 59(4)'s limit forked on 01-08-2024 (Notification 12/2024-CT) and the classifier picks by the invoice's
    date. The note called it a hardcoded constant of ₹2.5 lakh."""
    flat = _flat()
    new = re.search(r"`B2CL_THRESHOLD_PAISE` \(₹([\d.]+) lakh from (\d{2})-(\d{2})-(\d{4})", flat)
    old = re.search(r"`B2CL_THRESHOLD_LEGACY_PAISE` \(₹([\d.]+) lakh", flat)
    assert new and old, ("the note does not state the two B2CL limits as `B2CL_THRESHOLD_PAISE` (₹N lakh from "
                         "DD-MM-YYYY) and `B2CL_THRESHOLD_LEGACY_PAISE` (₹N lakh ...)")
    assert _lakh_to_paise(new.group(1)) == classifier.B2CL_THRESHOLD_PAISE, (
        f"the note says the current B2CL limit is ₹{new.group(1)} lakh; the classifier holds "
        f"{classifier.B2CL_THRESHOLD_PAISE} paise")
    assert _lakh_to_paise(old.group(1)) == classifier.B2CL_THRESHOLD_LEGACY_PAISE, (
        f"the note says the earlier B2CL limit is ₹{old.group(1)} lakh; the classifier holds "
        f"{classifier.B2CL_THRESHOLD_LEGACY_PAISE} paise")
    day, month, year = new.group(2), new.group(3), new.group(4)
    assert f"{year}-{month}-{day}" == classifier.B2CL_NEW_THRESHOLD_FROM, (
        f"the note says the lower limit starts {day}-{month}-{year}; the classifier says "
        f"{classifier.B2CL_NEW_THRESHOLD_FROM}")


def test_the_note_does_not_say_the_tests_fail_in_the_unit_environment():
    """`tests/test_phase3_gst.py` and `tests/test_hardening.py` run in mock mode and pass; the note said they 'return
    503 in the unit environment — a known environmental limitation', which sent a reader to excuse a real failure."""
    assert "503" not in _doc(), "the note still describes a 503 in the unit environment"
