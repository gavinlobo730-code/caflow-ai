"""
Five banking defects, one shape each, and the guard that keeps each closed.

BANK-10 — the bill side reported its whole net payable as outstanding
    `_fetch_bill_pool` never selected `paid_paise`, so `_bills_from` set
    `outstanding_paise = net_payable_paise`. A bill 90% settled therefore
    claimed its full net payable was still open, and matcher.py's "+15 matches
    outstanding balance" could fire on a figure that was not outstanding. The
    INVOICE side had always subtracted — so the two halves of one screen
    answered the same question differently.

    Both now read `outstanding_paise`, the GENERATED STORED column migration 278
    put on both tables, and fall back to its own transcribed formula for rows
    that never came from Postgres (mock mode, the in-memory doubles). That also
    picks up the s.34 credit/debit-note terms, which `total - paid` omitted.

BANK-17 — undo disturbed a line a completed reconciliation had certified
    `bank_posting_service.undo` checked match_status, the journal's source_type
    and the period lock, and never read `reconciliation_id`. Reversing the
    journal moves the book balance the completed session's frozen snapshot was
    signed against, while `reconciliation_id` and `reconciled` stay set — so the
    session goes on counting the line as cleared, and nothing recomputes a
    completed session to notice.

    `unmatch` is NOT given a second guard, and that is deliberate: a reconciled
    transaction is by construction a posted one (reconcile() only accepts rows
    with a posted_journal_id), and unmatch already refuses those. Asserted
    below, so the reasoning is checked rather than asserted in prose.

BANK-13 — a "Needs review" tab that could never have anything in it
    Nothing in the codebase has ever written `needs_review = true`.

BANK-03(a) — a statement in a currency the posting path cannot post
    `post()` calls `_create_journal` with no txn_currency, so it takes INR at
    rate 1: a USD line reading 1,000.00 was booked as one thousand rupees.

BANK-26 — a saved column mapping was reachable from one bank account only
    Same firm, same bank, same header fingerprint, thirty clients: the mapping
    was drawn thirty times.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

import services.bank_candidate_search_service as search_svc
import services.bank_column_mapping_service as column_mappings
import services.bank_matching_service as bms
from domain.banking import bill_open_paise, invoice_open_paise, rank_suggestions
from domain.banking.narration import describe, parse_narration
from services.bank_matching_service import bank_matching_service as svc
from services.bank_posting_service import bank_posting_service
from services.bank_register_service import STATUS_FILTERS
from services.banking_service import assert_bank_account_is_inr

from tests.test_bank_matching import FIRM, CLIENT, FakeDB

API = Path(__file__).resolve().parents[1]
WEB = API.parents[1] / "apps" / "web"


@pytest.fixture(autouse=True)
def _silence(monkeypatch):
    monkeypatch.setattr(bms.timeline_service, "log", lambda *a, **k: None)
    yield


# ── BANK-10: the open figure ─────────────────────────────────────────────────

def _bill(**kw):
    row = {"id": "b1", "bill_no": "B-1", "bill_date": "2026-04-01",
           "total_paise": 118_000, "net_payable_paise": 100_000,
           "vendor_id": "v1", "status": "unpaid"}
    row.update(kw)
    return row


def _invoice(**kw):
    row = {"id": "i1", "invoice_no": "INV-1", "invoice_date": "2026-04-01",
           "total_paise": 100_000, "paid_paise": 0,
           "customer_id": "c1", "status": "issued"}
    row.update(kw)
    return row


def test_a_bill_ninety_percent_paid_reports_the_tenth_that_is_left():
    [c] = svc._bills_from([_bill(paid_paise=90_000, status="partially_paid")],
                          {"v1": "Om Stationers"}, 100_000)
    assert c.outstanding_paise == 10_000, (
        "a bill with 90,000 of its 100,000 net payable settled has 10,000 open; "
        f"got {c.outstanding_paise}")
    assert c.amount_paise == 100_000, (
        "the candidate's own amount stays the net payable — FindMatchModal "
        "renders the 'open' figure only when it DIFFERS from the amount, so "
        "collapsing the two would delete the very annotation this fixes")


def test_the_same_bill_through_the_search_path_answers_identically():
    """Two services build Candidates off purchase_bills — the amount-banded
    automatic offer and the unbanded manual search. One subtracted and one did
    not, so the two halves of the same screen could disagree about the same
    bill. Run BOTH, against the same row."""
    row = _bill(paid_paise=90_000, status="partially_paid")
    db = FakeDB()
    db.store["purchase_bills"] = [{**row, "firm_id": FIRM, "client_id": CLIENT,
                                   "deleted_at": None}]
    db.store["vendors"] = [{"id": "v1", "firm_id": FIRM, "client_id": CLIENT,
                            "name": "Om Stationers"}]

    from_match = svc._bills_from([row], {"v1": "Om Stationers"}, 100_000)[0]
    [from_search] = search_svc.bank_candidate_search_service._bills(
        db, FIRM, CLIENT, "2026-01-01", "2026-12-31")

    assert from_search.outstanding_paise == from_match.outstanding_paise == 10_000
    assert from_search.amount_paise == from_match.amount_paise == 100_000


def test_the_search_path_drops_a_settled_bill_its_status_still_calls_unpaid():
    """Its own module docstring calls fully-paid a RULE rather than a filter,
    and the invoice branch enforced it. The bill branch never fetched
    paid_paise, so it could not."""
    db = FakeDB()
    db.store["purchase_bills"] = [{**_bill(paid_paise=100_000, status="unpaid"),
                                   "firm_id": FIRM, "client_id": CLIENT,
                                   "deleted_at": None}]
    db.store["vendors"] = [{"id": "v1", "firm_id": FIRM, "client_id": CLIENT,
                            "name": "Om"}]
    assert search_svc.bank_candidate_search_service._bills(
        db, FIRM, CLIENT, "2026-01-01", "2026-12-31") == []


def test_a_fully_settled_bill_is_not_a_candidate_whatever_its_status_says():
    """`status` is maintained by the settlement writers and can lag. The money
    cannot: paid >= payable means nothing is owed."""
    assert svc._bills_from([_bill(paid_paise=100_000, status="unpaid")],
                           {"v1": "Om"}, 100_000) == []


def test_the_note_columns_move_the_open_figure_the_way_the_schema_says():
    """CGST Act s.34. `total - paid` omitted them entirely, so a bill with a
    note against it offered the wrong payable.

    The SIGNS are migration 278's, and they are not guessable from the column
    names: migration 210 added the INCREASE document to both sides at once — a
    sales debit note and a purchase credit note — so `credit_note_paise` ADDS on
    purchase_bills while `credited_paise` SUBTRACTS on client_sales_invoices.
    Getting that backwards is the mistake this test exists to catch, and it
    caught it once already while being written."""
    assert bill_open_paise(_bill(paid_paise=0, credit_note_paise=25_000)) == 125_000
    assert bill_open_paise(_bill(paid_paise=0, debited_paise=25_000)) == 75_000
    assert invoice_open_paise(_invoice(credited_paise=40_000)) == 60_000
    assert invoice_open_paise(_invoice(debit_note_paise=5_000)) == 105_000


def test_the_generated_column_wins_over_the_transcribed_formula():
    """Migration 278 owns the definition. Where Postgres supplied it, it is
    read; the arithmetic below it exists only for rows Postgres never touched."""
    row = _bill(paid_paise=0, outstanding_paise=7)
    assert bill_open_paise(row) == 7
    assert invoice_open_paise(_invoice(outstanding_paise=9)) == 9


def test_the_pools_fetch_what_the_open_figure_needs():
    """A formula whose inputs are not selected silently reads them as zero — the
    exact way the bill side broke. Asserted against the select text because that
    is what PostgREST is actually sent."""
    for fn, needed in (
        (svc._fetch_bill_pool, ("paid_paise", "credit_note_paise", "debited_paise",
                                "outstanding_paise")),
        (svc._fetch_invoice_pool, ("paid_paise", "credited_paise", "debit_note_paise",
                                   "outstanding_paise")),
    ):
        src = inspect.getsource(fn)
        for col in needed:
            assert col in src, f"{fn.__name__} never selects {col}"


def test_the_outstanding_bonus_no_longer_fires_on_a_settled_bill():
    """The scoring consequence, end to end. matcher.py adds +15 for 'matches
    outstanding balance'; on a 90%-paid bill reporting its full payable, a bank
    line for the FULL payable collected that bonus — the ranker asserting the
    line settles a bill that has a tenth of it left."""
    [c] = svc._bills_from([_bill(paid_paise=90_000, status="partially_paid")],
                          {"v1": "Om"}, 100_000)
    [s] = rank_suggestions(100_000, "2026-04-01", "OM STATIONERS", [c])
    assert "matches outstanding balance" not in s.reasons, (
        "the bank line is 100,000 and only 10,000 is open — that is not a match "
        "on the outstanding balance")
    assert s.outstanding_paise == 10_000, "and the CA is shown what is actually open"


# ── BANK-17: a certified line ────────────────────────────────────────────────

class _ReconDB(FakeDB):
    """FakeDB with a posted transaction inside a reconciliation session."""

    def __init__(self, recon_status: str):
        super().__init__()
        self.store["bank_reconciliations"] = [{
            "id": "recon-1", "firm_id": FIRM, "client_id": CLIENT,
            "status": recon_status, "period_start": "2026-04-01",
            "period_end": "2026-04-30",
        }]
        self.store["bank_transactions"] = [{
            "id": "t1", "firm_id": FIRM, "client_id": CLIENT,
            "transaction_date": "2026-04-10", "description": "NEFT",
            "debit_paise": 0, "credit_paise": 100_000,
            "match_status": "posted", "posted_journal_id": "je-1",
            "reconciliation_id": "recon-1", "reconciled": True,
        }]
        self.store["journal_entries"] = [{
            "id": "je-1", "firm_id": FIRM, "source_type": "bank_transaction",
            "entry_date": "2026-04-10", "reversal_of": None,
        }]


def test_undo_refuses_a_line_a_completed_reconciliation_certified():
    db = _ReconDB("completed")
    with pytest.raises(HTTPException) as e:
        bank_posting_service.undo(db, FIRM, "t1")
    assert e.value.status_code == 409
    detail = str(e.value.detail)
    assert "completed bank reconciliation" in detail
    assert "Reopen" in detail, (
        "the refusal has to name the way through — reopening is Partner-only "
        "and reason-required, and a CA will not guess it")
    assert "2026-04-01" in detail and "2026-04-30" in detail, (
        "and WHICH reconciliation, or the CA has to go and find it")


@pytest.mark.parametrize("status", ["open", "in_progress"])
def test_undo_allows_a_line_in_a_session_that_will_be_recomputed(status):
    """An open or in-progress session re-runs its tie-out and its
    every-line-reviewed guard at completion, from the rows as they are then. An
    undo inside one is self-correcting, so refusing it would only obstruct."""
    db = _ReconDB(status)
    try:
        bank_posting_service.undo(db, FIRM, "t1")
    except HTTPException as e:
        assert "reconciliation" not in str(e.value if False else e.detail).lower(), (
            f"a {status} session must not block an undo: {e.detail}")


def test_a_line_in_no_reconciliation_is_not_asked_about():
    db = _ReconDB("completed")
    db.store["bank_transactions"][0]["reconciliation_id"] = None
    try:
        bank_posting_service.undo(db, FIRM, "t1")
    except HTTPException as e:
        assert "reconciliation" not in str(e.detail).lower()


def test_unmatch_needs_no_reconciliation_check_because_posted_covers_it():
    """The finding named unmatch too. It never reads reconciliation_id and does
    not need to: reconcile() indexes only transactions with a posted_journal_id,
    so every reconciled line is a posted one, and unmatch refuses posted lines
    already. Asserted rather than reasoned about in a comment — if either guard
    is ever relaxed this fails and the second check becomes real work."""
    db = _ReconDB("completed")
    with pytest.raises(HTTPException) as e:
        bms.bank_matching_service.unmatch(db, FIRM, "t1")
    assert e.value.status_code == 409
    assert "posted" in str(e.value.detail).lower()

    from services.bank_reconciliation_service import bank_reconciliation_service as recon
    assert "posted_journal_id" in inspect.getsource(recon._posted_account_txns), (
        "reconcile() reaches transactions through _posted_account_txns; if that "
        "stops filtering on posted_journal_id, unmatch needs its own guard")


# ── BANK-13: a filter that can match something ───────────────────────────────

def _api_sources() -> list[Path]:
    out = []
    for d in ("services", "routers", "domain", "jobs", "models"):
        out += list((API / d).rglob("*.py"))
    return out


def _web_sources() -> list[Path]:
    if not WEB.exists():
        return []
    out = []
    for d in ("app", "components", "lib"):
        p = WEB / d
        if p.exists():
            out += [f for f in p.rglob("*.ts*") if ".next" not in f.parts]
    return out


_WRITES_TRUE = re.compile(r'["\']needs_review["\']\s*:\s*(True|true)\b')


def test_the_needs_review_filter_is_offered_only_if_something_can_set_it():
    """The RULE, in both directions, rather than "the tab is gone".

    Today nothing writes the flag and nothing offers the filter, so this passes.
    The day BANK-13's exception service lands and starts writing it, this fails
    until the filter is restored — which is the point: the reason the tab was
    removed was the missing writer, so the writer is what should bring it back.
    """
    writers = [f for f in _api_sources() if _WRITES_TRUE.search(f.read_text())]
    offered = "needs_review" in STATUS_FILTERS
    assert bool(writers) == offered, (
        "needs_review writers and the register filter must appear together.\n"
        f"  writers: {[str(f.relative_to(API)) for f in writers] or 'none'}\n"
        f"  offered by STATUS_FILTERS: {offered}")


# The OFFER, not the word. `shared.ts` declaring `needs_review: boolean` on the
# row type is accurate — the API returns the column — and EntryDetailModal
# building a local `{needs_review: false}` is not a filter either. What must not
# exist is the value as a STRING: a filter id, a union member, a query value.
# Comments are stripped first, because the two files that explain why the tab
# went away necessarily quote it, and a guard its own explanation trips is a
# guard that gets deleted.
_TS_COMMENTS = (re.compile(r"/\*[\s\S]*?\*/"), re.compile(r"^\s*//.*$", re.M))


def _ts_code(path: Path) -> str:
    text = path.read_text()
    for pattern in _TS_COMMENTS:
        text = pattern.sub("", text)
    return text


def test_no_screen_offers_a_needs_review_tab_while_nothing_writes_it():
    offenders = [f for f in _web_sources()
                 if re.search(r'["\']needs_review["\']', _ts_code(f))]
    assert not offenders, (
        "a tab that always shows zero rows reads as 'nothing needs review', "
        "which is a false assurance rather than an empty list: "
        f"{[str(f.relative_to(WEB)) for f in offenders]}")


def test_the_route_and_the_service_advertise_the_same_filters():
    src = inspect.getsource(__import__("routers.banking", fromlist=["x"]).bank_register)
    pattern = re.search(r'pattern="\^\(([^)]+)\)\$"', src)
    assert pattern, "the register route no longer declares a status pattern"
    assert set(pattern.group(1).split("|")) == set(STATUS_FILTERS)


# ── BANK-03(a): one unit ─────────────────────────────────────────────────────

class _AccountDB(FakeDB):
    def __init__(self, currency: str):
        super().__init__()
        self.store["bank_accounts"] = [{
            "id": "ba-1", "firm_id": FIRM, "client_id": CLIENT,
            "bank_name": "Citi", "currency": currency,
        }]


def test_a_foreign_bank_account_refuses_a_statement():
    with pytest.raises(HTTPException) as e:
        assert_bank_account_is_inr(_AccountDB("USD"), FIRM, "ba-1", client_id=CLIENT)
    assert e.value.status_code == 422
    detail = str(e.value.detail)
    assert "USD" in detail and "rupees" in detail, (
        "the refusal has to say what would otherwise happen — the line would be "
        f"booked as rupees at its face figure. Got: {detail}")


@pytest.mark.parametrize("currency", ["INR", "inr", None])
def test_an_inr_account_is_untouched(currency):
    db = _AccountDB("INR")
    db.store["bank_accounts"][0]["currency"] = currency
    assert_bank_account_is_inr(db, FIRM, "ba-1", client_id=CLIENT)


def test_no_bank_account_means_nothing_to_refuse():
    """A statement with no linked account has no currency to read, and INR is
    the column default."""
    assert_bank_account_is_inr(_AccountDB("USD"), FIRM, None)


def test_both_the_import_and_the_post_ask():
    """The import tells the CA before three hundred rows are loaded; the post is
    what protects the ledger, and reaches statements imported before the import
    check existed. One without the other leaves a hole."""
    import services.banking_service as banking_svc
    assert "assert_bank_account_is_inr" in inspect.getsource(banking_svc.BankingService._import_core)
    assert "_assert_postable_currency" in inspect.getsource(bank_posting_service.post)


def test_the_multi_allocation_path_is_deliberately_not_blocked():
    """match_and_settle_multi carries currency and exchange_rate through to
    receipt/payment creation. It is the path that already works, so guarding it
    would remove FX capability rather than protect anything."""
    src = inspect.getsource(bank_posting_service.match_and_settle_multi)
    assert "_assert_postable_currency" not in src
    assert "exchange_rate" in src


# ── BANK-26: the mapping is the firm's ───────────────────────────────────────

class _MappingDB(FakeDB):
    def __init__(self, rows):
        super().__init__()
        self.store["bank_statement_column_mappings"] = rows


def _mapping_row(**kw):
    row = {"id": "m1", "firm_id": FIRM, "client_id": CLIENT,
           "bank_account_id": "ba-1", "header_fingerprint": "fp-A",
           "mapping": {"date": 0, "description": 1}, "created_at": "2026-04-01"}
    row.update(kw)
    return row


def test_this_accounts_own_mapping_still_wins():
    db = _MappingDB([_mapping_row(id="mine"),
                     _mapping_row(id="theirs", bank_account_id="ba-2")])
    found = column_mappings.find_mapping(db, FIRM, "ba-1", "fp-A")
    assert found["id"] == "mine"
    assert found["match_scope"] == "account"


def test_the_same_layout_recorded_on_another_account_is_reused():
    db = _MappingDB([_mapping_row(id="theirs", bank_account_id="ba-2",
                                  client_id="other-client")])
    found = column_mappings.find_mapping(db, FIRM, "ba-1", "fp-A")
    assert found is not None, (
        "the firm has already told us how to read this exact header — asking "
        "again for every client is BANK-26")
    assert found["match_scope"] == "firm", (
        "and the caller must be able to say so, rather than presenting another "
        "client's mapping as this account's settled answer")


def test_a_different_layout_is_never_reused_however_close():
    """The one thing the fallback must not do. A changed export read at the old
    column positions produces numbers that are wrong without looking wrong."""
    db = _MappingDB([_mapping_row(bank_account_id="ba-2", header_fingerprint="fp-B")])
    assert column_mappings.find_mapping(db, FIRM, "ba-1", "fp-A") is None


def test_another_firms_mapping_is_never_reached():
    db = _MappingDB([_mapping_row(firm_id="other-firm", bank_account_id="ba-9")])
    assert column_mappings.find_mapping(db, FIRM, "ba-1", "fp-A") is None


# ── BANK-28: the cheque number ───────────────────────────────────────────────

@pytest.mark.parametrize("narration,expected", [
    ("CHQ NO 123456 PAID", "123456"),
    ("CLG/000123/ACME PVT LTD", "000123"),
    ("MICR CHEQUE 456789", "456789"),
    ("123456 CHQ", "123456"),
    ("CHEQUE NO. 654321", "654321"),
])
def test_a_cheque_number_beside_a_cheque_word_is_kept(narration, expected):
    assert parse_narration(narration).cheque_no == expected


@pytest.mark.parametrize("narration", [
    "NEFT DR 123456 ACME",            # six digits, no cheque word
    "UPI/DR/412345678901/RAMESH",     # a UTR, not a cheque
    "CHQ 12345",                      # five digits is not a cheque serial
    "CHQ 1234567",                    # nor is seven
    "",
])
def test_nothing_else_is_read_as_a_cheque_number(narration):
    assert parse_narration(narration).cheque_no is None


def test_the_queue_summary_carries_it():
    """A cheque is the one channel with no UTR, so without this every cheque
    line read 'CHEQUE · <name>' with nothing to tell one from the next."""
    assert "Cheque 123456" in describe(parse_narration("CLG/123456/ACME LTD"))
