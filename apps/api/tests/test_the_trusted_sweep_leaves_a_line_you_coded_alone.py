"""
BANK-16 — a trusted rule does not pass a line the CA answered themselves.

WHAT WAS WRONG
    A trusted rule passes its lines with no click; it is the one place the
    product acts unprompted, and docs/architecture/09-bank-entries.md grounds
    that in one sentence — "Its lines post on the authority of the person who
    trusted it ... There is no system user, because there is no such person to
    answer for it."

    Drafting stamps `draft_rule_id` on the row. Answering the line does not
    clear the stamp. So a line the CA coded themselves stayed in the trusted
    sweep's selection, and `pass_entry` then split the difference in the worst
    way: `coded_by_a_human` stopped the DRAFT being applied over the human's
    answer, so what posted was the CA's ledger, entity and GST treatment — but
    `actor = rule["trusted_by"]`, so journal_entries.created_by,
    bank_transactions.posted_by and the audit row all named the person who
    trusted the rule, with source = bank_trusted_rule. "Passed by rule Bank
    charges, trusted by Priya" over somebody else's posting.

WHAT IS ASSERTED, AND WHY IN THIS SHAPE
    1. The sweep does not pass such a line — and does not COUNT it either.
       The count is the half that matters: jobs/bank_trusted_rules_job loops
       while `remaining` is non-zero, so a line excluded from the page but not
       from the count spins the sweep on the same chunk. A test that asserted
       only "passed == 0" would pass against a post-fetch filter, which is the
       broken fix.
    2. `trusted_pending` agrees with the sweep. A screen offering "pass 3
       trusted drafts" that passes none is the same defect wearing a number.
    3. A PERSON can still pass the line. The fix must not make a human-coded
       line unpassable — only unpassable UNPROMPTED.
    4. pass_entry refuses a by_rule pass of such a line even when the caller
       forgot the filter, so the rule survives a second caller.
    5. The migration states the rule as CODE: the trigger assigns the column
       and the entry_state CASE READS it, rather than restating the predicate.
       Asserted against the SQL with comments stripped — this codebase has
       repeatedly written guards that matched their own explanatory prose.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.banking import entry as E
from services.bank_entry_service import bank_entry_service as svc
from tests.test_bank_entry_service import (CHARGES, RENT, _db, _line, _rule, _row,
                                           _state, poster)          # noqa: F401

MIGRATION = (Path(__file__).resolve().parents[1] / "migrations"
             / "369_the_trusted_sweep_leaves_a_line_you_coded_alone.sql")


def _trusted(db):
    _rule(db, rid="trusted", pattern="CHARGES", is_trusted=True, trusted_by="mgr-1",
          trusted_at="2026-09-03T00:00:00Z")


def _drafted_then_coded(db):
    """The exact row the defect needed: a trusted rule drafted it, and the CA
    then chose a different ledger from the detail."""
    _trusted(db)
    _line(db, "chg", "NEFT CHARGES")
    svc.redraft(db, *_ids())
    assert _row(db, "chg")["draft_rule_id"] == "trusted", "the rule must have drafted it"
    # The CA answers it themselves — a different account from the rule's.
    db.table("bank_transactions").update({"account_id": RENT}).eq("id", "chg").execute()
    row = _row(db, "chg")
    assert row["draft_rule_id"] == "trusted", "answering must not clear the stamp"
    assert row["coded_by_a_human"] is True
    assert row["entry_state"] == E.READY
    return row


def _ids():
    from tests.test_bank_matching import FIRM, CLIENT
    return FIRM, CLIENT


def test_the_sweep_neither_passes_nor_counts_a_line_you_coded(poster):   # noqa: F811
    db = _db()
    _drafted_then_coded(db)
    firm, client = _ids()

    out = svc.pass_ready(db, firm, client, only_trusted=True)

    assert out["passed"] == 0, "a line the CA coded is not the rule's to pass"
    # The half a post-fetch filter gets wrong. `remaining` drives the job's
    # loop; if this line is still counted, the sweep never finishes and never
    # reaches the lines behind it.
    assert out["remaining"] == 0, (
        "the human-coded line must be excluded from the COUNT as well as the "
        "page, or bank_trusted_rules_job spins on the same chunk")
    assert poster.calls == [], "nothing may be posted"
    assert _row(db, "chg").get("posted_by_rule_id") is None


def test_trusted_pending_counts_what_the_sweep_will_actually_pass(poster):  # noqa: F811
    db = _db()
    _drafted_then_coded(db)
    firm, client = _ids()
    assert svc.counts(db, firm, client)["trusted_pending"] == 0, (
        "the screen must not offer to pass a line the sweep will leave alone")


def test_a_person_can_still_pass_the_line_they_coded(poster):           # noqa: F811
    db = _db()
    _drafted_then_coded(db)
    firm, client = _ids()

    # "Pass N ready" — no only_trusted, so the actor is the person clicking.
    out = svc.pass_ready(db, firm, client, actor_id="exec-1")

    assert out["passed"] == 1, "the fix must not make a human-coded line unpassable"
    assert poster.calls == [dict(txn_id="chg", actor_id="exec-1", gst_rate_bps=None,
                                 is_interstate=False, actor_auth_id=None)]
    assert _row(db, "chg").get("posted_by_rule_id") is None, (
        "passed by a person, so no rule is credited")


def test_pass_entry_refuses_a_by_rule_pass_of_a_human_coded_line(poster):  # noqa: F811
    """Defence in depth: the rule holds even where a caller forgot the filter."""
    db = _db()
    _drafted_then_coded(db)
    firm, _client = _ids()

    res = svc.pass_entry(db, firm, "chg", actor_id="mgr-1",
                         by_rule={"id": "trusted", "rule_name": "Bank charges",
                                  "trusted_by": "mgr-1"})

    assert res["status"] == "skipped"
    assert "coded this line yourself" in res["reason"], res
    assert poster.calls == []


def test_the_sweep_still_passes_a_line_nobody_answered(poster):         # noqa: F811
    """The negative control for the three above: with no human answer on the
    row, the sweep behaves exactly as it did."""
    db = _db()
    _trusted(db)
    _line(db, "chg", "NEFT CHARGES")
    firm, client = _ids()
    svc.redraft(db, firm, client)

    assert svc.counts(db, firm, client)["trusted_pending"] == 1
    out = svc.pass_ready(db, firm, client, only_trusted=True)
    assert out["passed"] == 1 and out["remaining"] == 0
    assert poster.calls == [dict(txn_id="chg", actor_id="mgr-1", gst_rate_bps=None,
                                 is_interstate=False, actor_auth_id=None)]


# ── the migration states the rule, and is read as code ───────────────────────

def _sql_without_comments(path: Path) -> str:
    """Everything but the prose. A guard that scans a file which EXPLAINS the
    rule in English will find the rule in the explanation — this repo has done
    exactly that more than once."""
    return "\n".join(re.sub(r"--.*$", "", ln) for ln in path.read_text().splitlines())


def test_the_trigger_assigns_the_column_and_the_case_reads_it():
    body = _sql_without_comments(MIGRATION)
    assert "NEW.coded_by_a_human := COALESCE(" in body, (
        "the trigger must MAINTAIN the column — a column nothing assigns is "
        "frozen at its default and the sweep would pass everything")
    assert "WHEN NEW.coded_by_a_human" in body, (
        "entry_state's 'ready' branch must READ the column rather than restate "
        "the predicate; two copies of one rule is what the parity rule forbids")
    # The predicate must appear ONCE. Counting the most distinctive term of it.
    assert body.count("NEW.matched_entity_id IS NOT NULL") == 1, (
        "the human-coded predicate is written twice — it was MOVED out of the "
        "CASE, not copied beside it")


def test_the_column_is_not_null_so_an_old_row_reads_false_not_unknown():
    body = _sql_without_comments(MIGRATION)
    assert "coded_by_a_human BOOLEAN NOT NULL DEFAULT false" in body
    # And every row that predates the column is recomputed through the trigger.
    assert "UPDATE public.bank_transactions SET entry_state = entry_state;" in body, (
        "without the backfill, every row inserted before 369 reads false and "
        "the sweep would pass the human-coded ones among them")


def test_the_python_twin_and_the_sql_agree_on_every_branch():
    """Both twins listed side by side, so adding a branch to one and not the
    other is visible here as well as in the real-Postgres parity test."""
    body = _sql_without_comments(MIGRATION)
    for sql_term in ("NEW.account_id IS NOT NULL",
                     "NEW.matched_entity_id IS NOT NULL",
                     "NEW.has_splits",
                     "NEW.transfer_pair_id IS NOT NULL AND NEW.transfer_is_primary = true",
                     "NEW.category IN ('Customer Payment', 'Vendor Payment', 'GST Payment')"):
        assert sql_term in body, f"the SQL lost a branch: {sql_term}"
    for row, expected in (
        ({"account_id": "a"}, True),
        ({"matched_entity_id": "e"}, True),
        ({"has_splits": True}, True),
        ({"transfer_pair_id": "p", "transfer_is_primary": True}, True),
        ({"transfer_pair_id": "p", "transfer_is_primary": False}, False),
        ({"category": "Customer Payment"}, True),
        ({"category": "Transfer"}, False),
        ({"draft_grade": "ready", "draft_source": "rule"}, False),
        ({}, False),
    ):
        assert E.coded_by_a_human(row) is expected, row
