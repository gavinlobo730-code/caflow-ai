"""
The general ledger can name the document behind every entry it holds.

WHAT WAS WRONG
    `journal_entries.source_type` / `source_id` have existed since migration
    104, which also created `idx_je_source (source_type, source_id)` for the
    lookup they enable. Only TWELVE of the twenty-six posting paths ever filled
    them in. The fourteen that did not were:

        journal_for_sales_invoice          journal_for_payroll
        journal_for_purchase_bill          journal_for_payroll_disbursement
        journal_for_credit_note            journal_for_settlement
        journal_for_debit_note             journal_for_asset_acquisition (x2)
        journal_for_sales_debit_note       journal_for_depreciation
        journal_for_purchase_credit_note   journal_for_asset_disposal
                                           journal_for_bank_transaction

    — that is, every sales invoice, every purchase bill, all four §34 note
    paths, payroll, the leaver's settlement, all four fixed-asset paths and the
    bank journal. Most of the general ledger of a real practice. So the index
    was there and the answer was not, and a CA reading "Trade Receivables
    1,18,000 Dr" had nothing to open.

    This was found while scoping ACC-22, whose own text asserts that
    "source_type/source_id are already stamped on the entry". For the two
    commonest documents in an Indian practice that was simply untrue, and a
    drill-through built on it would have worked for almost nothing.

WHY STAMPING IS SAFE, and this is the part worth re-reading
    Every guard that branches on source_type treats NULL as NOT manual —
    `_is_manual` is `(source_type or "") == "manual"`, and migrations 275 and
    338 use `COALESCE(source_type, '') <> 'manual'`. So an entry that gains a
    real source is refused by the edit and discard paths EXACTLY as it was when
    it had none. Nothing is opened up; the refusal only gains the ability to say
    which document to go and correct.

WHAT IS ASSERTED
    1. The RULE, not a list: every `_create_journal` call site in the codebase
       passes a source_type. Written by parsing the calls, so a fifteenth
       posting path added tomorrow fails this rather than joining the gap
       silently. Comments and docstrings are stripped first — this repo has
       repeatedly written guards that matched their own explanatory prose.
    2. Every value stamped is in the ONE vocabulary, so a second spelling of
       "sales invoice" cannot appear.
    3. The guards still refuse. Asserted against the real functions, because
       "it is still refused" is the property stamping could plausibly break.
    4. The refusal names the document in words.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from domain.accounting import journal_source as JS
from services.manual_journal_service import _is_manual, _not_manual_message

API_ROOT = Path(__file__).resolve().parents[1]
SEARCH_DIRS = ("services", "routers")


def _module_constants(tree) -> dict:
    """This module's own top-level `NAME = "literal"` bindings.

    Needed because three callers pass their source through a local constant —
    `MANUAL_SOURCE`, `OPENING_SOURCE`, `TB_SOURCE` — rather than a literal or a
    `JS.` attribute. Resolving them is the difference between this guard
    checking every call and quietly skipping the ones that use a name."""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
    return out


def _calls_to_create_journal():
    """Every `_create_journal(...)` call in the codebase, with the keywords it
    passes. Parsed with `ast`, not grepped: a regex over source text sees the
    word `source_type` in a comment explaining why a call needs one."""
    found = []
    for d in SEARCH_DIRS:
        for path in sorted((API_ROOT / d).glob("*.py")):
            tree = ast.parse(path.read_text())
            consts = _module_constants(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = (fn.attr if isinstance(fn, ast.Attribute)
                        else fn.id if isinstance(fn, ast.Name) else None)
                if name != "_create_journal":
                    continue
                kw = {k.arg for k in node.keywords if k.arg}
                found.append((f"{d}/{path.name}", node.lineno, kw, node, consts))
    return found


def test_there_are_posting_paths_to_check_at_all():
    """A guard that silently found nothing would pass for ever."""
    calls = _calls_to_create_journal()
    assert len(calls) >= 25, f"only {len(calls)} call sites found — did the parse break?"
    # And every one of them must RESOLVE, or the checks below pass vacuously on
    # a call whose source this parser simply could not read.
    unresolved = [f"{f}:{ln}" for f, ln, kw, node, consts in calls
                  if "source_type" in kw and _stamped_source(node, consts) is None]
    assert unresolved == [], (
        f"a source_type this guard cannot read is a check it is not making: {unresolved}")


def test_every_posting_path_stamps_the_document_it_came_from():
    missing = [f"{f}:{ln}" for f, ln, kw, _n, _c in _calls_to_create_journal()
               if "source_type" not in kw]
    assert missing == [], (
        "these posting paths write a journal nothing can trace back to its "
        f"document: {missing}. journal_entries.source_type/source_id exist and "
        "are indexed (migration 104) — pass them, using a name from "
        "domain/accounting/journal_source.py.")


#: A call that PROPAGATES an existing entry's source rather than naming one.
#: `reverse_entry` does this deliberately — task #102 — so the document can be
#: found from the reversal as well as from the original, and it is right that
#: it cannot be resolved statically: the value is whatever the original had.
PROPAGATED = "<propagated>"


def _stamped_source(node, consts: dict) -> str | None:
    """The source_type a call passes, as a VALUE.

    Three legitimate forms: a literal, a `JS.NAME` attribute, or the calling
    module's own constant. A fourth — reading `source_type` off another entry —
    is propagation and answers PROPAGATED. Anything else answers None, which
    the guards treat as a failure rather than a pass, because a source this
    parser cannot read is a check it is not making."""
    for k in node.keywords:
        if k.arg != "source_type":
            continue
        v = k.value
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            return v.value
        if isinstance(v, ast.Attribute):
            return getattr(JS, v.attr, None)
        if isinstance(v, ast.Name):
            return consts.get(v.id)
        if any(isinstance(n, ast.Constant) and n.value == "source_type"
               for n in ast.walk(v)):
            return PROPAGATED
    return None


def test_every_posting_path_that_names_a_ROW_says_which_row():
    """A source_type with no source_id names a kind and not a row, which is a
    breadcrumb leading nowhere.

    Three sources are exempt and the exemption is in the VOCABULARY, not here:
    `ENTRY_IS_THE_RECORD` — a manual journal, an opening balance and a
    trial-balance import have no separate document, so the entry itself is what
    a CA would open. Writing that list into this test instead would have made
    it an exception the next reader has to take on trust."""
    missing = []
    for f, ln, kw, node, consts in _calls_to_create_journal():
        if "source_type" not in kw or "source_id" in kw:
            continue
        src = _stamped_source(node, consts)
        if src not in (JS.ENTRY_IS_THE_RECORD | {PROPAGATED}):
            missing.append(f"{f}:{ln} -> {src!r}")
    assert missing == [], f"stamped a kind but not a row: {missing}"


def test_the_exempt_sources_really_are_the_ones_with_no_document():
    """Pins the exemption to its reason, so it cannot quietly grow to cover a
    path that simply forgot its id."""
    assert JS.ENTRY_IS_THE_RECORD == {JS.MANUAL, JS.OPENING, JS.TRIAL_BALANCE_IMPORT}
    for src in JS.ENTRY_IS_THE_RECORD:
        assert src in JS.ALL_SOURCES


def test_nothing_is_stamped_outside_the_one_vocabulary():
    """Catches a second spelling before it reaches production data, where it
    would be permanent."""
    bad = [f"{f}:{ln} -> {_stamped_source(node, consts)!r}"
           for f, ln, kw, node, consts in _calls_to_create_journal()
           if "source_type" in kw
           and _stamped_source(node, consts) not in (JS.ALL_SOURCES | {PROPAGATED})]
    assert bad == [], (
        f"stamped a source that is not in journal_source.ALL_SOURCES: {bad}")


# ── the property stamping could have broken ──────────────────────────────────

@pytest.mark.parametrize("source_type", sorted(JS.ALL_SOURCES - {JS.MANUAL}))
def test_a_stamped_entry_is_still_refused_by_the_manual_only_guard(source_type):
    """NULL was never 'manual' — `_is_manual` is `(source_type or "") ==
    "manual"` and migrations 275/338 use `COALESCE(source_type,'') <>
    'manual'`. So giving an entry a real source must leave it refused, not
    admit it. This is the assertion that made the sweep safe to do."""
    assert _is_manual({"source_type": source_type}) is False


def test_an_unstamped_entry_is_still_refused_too():
    """Entries posted before their path stamped a source keep NULL for ever —
    there is no backfill — so the guard must go on refusing them."""
    assert _is_manual({"source_type": None}) is False
    assert _is_manual({}) is False


def test_a_manual_entry_is_still_editable():
    assert _is_manual({"source_type": JS.MANUAL}) is True


def test_the_refusal_names_the_document_in_words():
    msg = _not_manual_message({"source_type": JS.SALES_INVOICE})
    assert "a sales invoice" in msg
    assert "sales_invoice" not in msg, "a column value is not a sentence"


def test_the_refusal_survives_an_entry_with_no_source():
    """It is a refusal the CA has to read; failing to render it would turn
    'correct the document' into a 500."""
    assert "a source document" in _not_manual_message({"source_type": None})


# ── the vocabulary itself ────────────────────────────────────────────────────

def test_every_source_has_something_to_call_it():
    assert set(JS.SOURCE_LABEL) == JS.ALL_SOURCES


def test_the_two_camel_case_values_are_left_alone():
    """They are in production data and name EVENTS rather than documents — an
    opening balance and a trial-balance import are not rows a CA can open — so
    renaming them would strand existing entries for no gain."""
    assert JS.OPENING == "Opening"
    assert JS.TRIAL_BALANCE_IMPORT == "TrialBalance"


def test_the_vocabulary_module_carries_no_duplicate_values():
    values = [v for k, v in vars(JS).items()
              if k.isupper() and isinstance(v, str) and not k.startswith("_")]
    assert len(values) == len(set(values)), (
        f"two names for one source: {sorted(v for v in values if values.count(v) > 1)}")
