"""
The Cash Flow Statement's fast path must equal the full-history replay, exactly.

WHY THIS IS THE ONE THAT NEEDED PROVING
    Trial Balance, P&L and Balance Sheet were moved onto the reporting passbook
    and their equivalence pinned by test_passbook_read_path. Cash Flow was left
    behind, and so became the only report still fetching a client's ENTIRE
    posted history plus six document tables it never reads. In production that
    is the whole gap: profit-loss 2.15s, trial-balance 2.06s, cash-flow 54.34s
    on the same client, same request.

    Making it fast means changing WHERE the numbers come from — a bounded
    entries fetch for the period, and the passbook's monthly buckets for opening
    and closing cash. Any drift between those and the replay is not a slow
    report, it is a WRONG cash flow statement, which is worse. So every assertion
    here compares the two whole dicts, not a summary figure.

WHAT IS DELIBERATELY COVERED
    * Month-aligned windows (a financial year), where the passbook needs no edge
      months at all, and ragged windows, where it must replay one or two partial
      months from raw entries. The ragged case is where an off-by-one in the
      bucket boundary would show up.
    * A window whose opening balance is non-zero — otherwise opening cash is 0
      either way and the passbook half of the test proves nothing.
    * The reconciliation flags, which are the statement's own integrity check:
      if the fast path got opening/closing cash from a different place than the
      body, `reconciles` would go False even while the totals looked plausible.
    * That the fast path really is narrower — it must not touch the document
      tables, and its entries fetch must be date-bounded. A "fast" path that
      quietly still reads everything would pass every equality assertion above
      while fixing nothing.
"""
from __future__ import annotations

import pytest

from domain.reporting.balance_cache import build_buckets
from domain.reporting.service import ReportingService
from domain.reporting.sources import SupabaseLedgerSource
from tests.test_passbook_read_path import (  # the same Supabase-shaped fake DB
    CLIENT, FIRM, _DB, _entry,
)

# Windows chosen so both bucket regimes are exercised:
#   month-aligned  -> zero edge-month replays
#   ragged         -> one or two partial months replayed from raw entries
WINDOWS = [
    ("2026-04-01", "2027-03-31"),   # a financial year — both ends month-aligned
    ("2025-04-01", "2026-03-31"),   # the prior FY, so opening cash is 0
    ("2026-07-05", "2026-07-20"),   # ragged at both ends, inside one month
    ("2026-04-15", "2026-08-31"),   # ragged start, aligned end
    ("2026-05-01", "2026-07-12"),   # aligned start, ragged end
]


def _account(aid, code, name, atype, subtype=None, key=None):
    return {"id": aid, "account_code": code, "account_name": name, "account_type": atype,
            "account_subtype": subtype, "system_account_key": key,
            "firm_id": FIRM, "client_id": None, "is_active": True}


# A fixed asset is added to the borrowed chart so the statement has an INVESTING
# section — without one, _activity_of_entry never takes that branch and the
# equality assertions would only ever compare operating and financing.
ACCOUNTS = [
    _account("bank", "1000", "Bank", "Asset", "Bank", "bank"),
    _account("rev", "4000", "Sales", "Revenue"),
    _account("exp", "5000", "Rent", "Expense"),
    _account("cap", "3000", "Capital", "Equity"),
    _account("fa", "1500", "Plant & Machinery", "Asset", "Fixed Asset"),
]

# Entries land ON several window boundaries ON PURPOSE. Opening cash is the
# balance as of the day BEFORE `start`, and the only way to tell that apart from
# the balance as of `start` is to have a bank movement dated exactly `start` —
# otherwise an off-by-one at the opening boundary produces identical numbers and
# every assertion in this file passes through it. Verified by mutation: changing
# _day_before(start) to start makes test_fast_cash_flow_equals_legacy fail.
ENTRIES_RAW = [
    _entry("e1", "2025-05-10", [("bank", 100000, 0), ("cap", 0, 100000)]),   # financing
    _entry("e2", "2025-06-15", [("bank", 20000, 0), ("rev", 0, 20000)]),     # operating
    _entry("e3", "2026-04-01", [("exp", 5000, 0), ("bank", 0, 5000)]),       # ON an FY start
    _entry("e4", "2026-04-15", [("fa", 30000, 0), ("bank", 0, 30000)]),      # ON a ragged start, investing
    _entry("e5", "2026-05-01", [("bank", 8000, 0), ("rev", 0, 8000)]),       # ON an aligned start
    _entry("e6", "2026-07-05", [("exp", 2000, 0), ("bank", 0, 2000)]),       # ON a ragged start
    _entry("e7", "2026-07-12", [("bank", 4000, 0), ("rev", 0, 4000)]),       # ON a ragged end
    _entry("e8", "2026-07-20", [("exp", 3000, 0), ("bank", 0, 3000)]),       # ON a ragged end
    _entry("e9", "2026-07-25", [("exp", 1000, 0), ("bank", 0, 1000)]),
    _entry("e10", "2027-03-31", [("bank", 6000, 0), ("cap", 0, 6000)]),      # ON an FY end
]


def _seed_store() -> dict:
    """journal_entries + chart_of_accounts + the passbook buckets built from the
    same entries, so the fast and legacy paths are reading one consistent world."""
    parsed = SupabaseLedgerSource(_DB({"journal_entries": ENTRIES_RAW}))._entries(FIRM, CLIENT)
    apb = [
        {"id": f"b{i:04d}", "firm_id": FIRM, "client_id": CLIENT, "account_id": aid,
         "period_month": month, "debit_paise": dr, "credit_paise": cr}
        for i, ((aid, month), (dr, cr)) in enumerate(build_buckets(parsed.values()).items())
    ]
    return {"journal_entries": ENTRIES_RAW, "chart_of_accounts": ACCOUNTS,
            "account_period_balances": apb}


def _svc(store=None) -> ReportingService:
    return ReportingService(SupabaseLedgerSource(_DB(store or _seed_store())))


@pytest.mark.parametrize("start,end", WINDOWS)
def test_fast_cash_flow_equals_legacy(monkeypatch, start, end):
    svc = _svc()
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "off")
    legacy = svc.cash_flow_statement(FIRM, CLIENT, start, end)
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    fast = _svc().cash_flow_statement(FIRM, CLIENT, start, end)

    assert fast == legacy, f"cash flow mismatch {start}..{end}"


@pytest.mark.parametrize("start,end", WINDOWS)
def test_the_statement_still_reconciles_on_the_fast_path(monkeypatch, start, end):
    """Not implied by the equality above: if BOTH paths were wrong the same way
    they would still match. `reconciles` is computed inside builders.cash_flow
    from closing − opening versus the sum of the classified sections, so it fails
    if opening/closing cash and the body ever disagree."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    out = _svc().cash_flow_statement(FIRM, CLIENT, start, end)

    assert out["reconciles"] is True, out
    assert out["operating_reconciliation"]["ties_out"] is True, out


def test_opening_cash_is_actually_non_zero_somewhere(monkeypatch):
    """Vacuity guard for the whole file. The passbook's job here is the CUMULATIVE
    balance before the window; if every fixture window opened at zero, the two
    paths would agree by both returning 0 and prove nothing."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    svc = _svc()
    openings = [svc.cash_flow_statement(FIRM, CLIENT, s, e)["opening_cash_paise"]
                for s, e in WINDOWS]

    assert any(o != 0 for o in openings), f"every window opens at zero: {openings}"


def test_cash_basis_is_served_by_the_same_numbers(monkeypatch):
    """basis is echoed only — the statement is intrinsically actual-cash. The
    fast path passes "accrual" to the passbook gate regardless of what the caller
    asked for, so this pins that the two bases really do produce one answer."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    svc = _svc()
    accrual = svc.cash_flow_statement(FIRM, CLIENT, "2026-04-01", "2027-03-31", basis="accrual")
    cash = _svc().cash_flow_statement(FIRM, CLIENT, "2026-04-01", "2027-03-31", basis="cash")

    assert cash.pop("basis") == "cash"
    assert cash == accrual


def test_shadow_mode_serves_the_legacy_result(monkeypatch):
    """Same rollout discipline as the other three reports: shadow must serve the
    trusted number even though it computes the fast one to compare."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "shadow")
    shadow = _svc().cash_flow_statement(FIRM, CLIENT, "2026-04-01", "2027-03-31")
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "off")
    legacy = _svc().cash_flow_statement(FIRM, CLIENT, "2026-04-01", "2027-03-31")

    assert shadow == legacy


def test_a_broken_fast_path_degrades_to_legacy_not_to_a_wrong_number(monkeypatch):
    """A stale or missing passbook must make the report SLOW, never wrong."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "off")
    legacy = _svc().cash_flow_statement(FIRM, CLIENT, "2026-04-01", "2027-03-31")

    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    svc = _svc()
    def boom(*a, **k):
        raise RuntimeError("buckets unavailable")
    monkeypatch.setattr(svc.source, "fetch_buckets", boom)

    assert svc.cash_flow_statement(FIRM, CLIENT, "2026-04-01", "2027-03-31") == legacy


# ── the fast path must actually BE narrower ──────────────────────────────────

class _RecordingDB(_DB):
    """Records which tables were queried, and the date bounds of each read."""

    def __init__(self, store):
        super().__init__(store)
        self.tables: list[str] = []
        self.entry_filters: list[list] = []

    def table(self, name):
        self.tables.append(name)
        q = super().table(name)
        if name == "journal_entries":
            self.entry_filters.append(q.f)   # same list object the query mutates
        return q


DOCUMENT_TABLES = {"client_sales_invoices", "receipts", "receipt_allocations",
                   "credit_notes", "purchase_bills", "purchase_payments"}


def test_the_fast_path_reads_none_of_the_document_tables(monkeypatch):
    """Six of _base()'s seven fetches, plus its chunked serial allocations tail,
    are dead weight for this statement — it reads raw posted entries and never
    the cash-basis projector. If they come back, the endpoint is paying for data
    it discards."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    db = _RecordingDB(_seed_store())
    ReportingService(SupabaseLedgerSource(db)).cash_flow_statement(
        FIRM, CLIENT, "2026-04-01", "2027-03-31")

    touched = DOCUMENT_TABLES & set(db.tables)
    assert not touched, f"fast path still reads document tables: {sorted(touched)}"
    assert "account_period_balances" in db.tables, "the passbook was not consulted at all"


def test_the_fast_paths_entry_fetch_is_date_bounded(monkeypatch):
    """The other half of the win: without bounds this fetches a client's entire
    posted history — 12,836 entries and 32,936 embedded lines in the production
    case — to build a statement about one financial year."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    db = _RecordingDB(_seed_store())
    ReportingService(SupabaseLedgerSource(db)).cash_flow_statement(
        FIRM, CLIENT, "2026-04-01", "2027-03-31")

    assert db.entry_filters, "no journal_entries query was made at all"
    for filters in db.entry_filters:
        ops = {k: op for k, (op, _v) in filters}
        assert ops.get("entry_date") in ("gte", "lte"), (
            f"an unbounded journal_entries fetch survives on the fast path: {filters}")


def test_the_legacy_path_is_the_thing_being_avoided(monkeypatch):
    """Control for the two tests above: with the passbook off, the document
    tables and the unbounded fetch DO appear. Without this, both assertions
    would pass just as well against a code path that never runs."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "off")
    db = _RecordingDB(_seed_store())
    ReportingService(SupabaseLedgerSource(db)).cash_flow_statement(
        FIRM, CLIENT, "2026-04-01", "2027-03-31")

    assert DOCUMENT_TABLES & set(db.tables), "the legacy path stopped reading documents"
    assert any("entry_date" not in {k for k, _ in f} for f in db.entry_filters), (
        "the legacy path has no unbounded entries fetch — this control is stale")


def test_the_fixtures_have_an_entry_outside_every_window(monkeypatch):
    """Guards the date-bounding tests from proving nothing: if all fixture
    entries fell inside every window, a bounded and an unbounded fetch would
    return the same rows and the equality tests could not tell them apart."""
    store = _seed_store()
    dates = sorted(e["entry_date"] for e in store["journal_entries"])

    assert dates[0] < "2026-04-01", f"nothing precedes the FY window: {dates}"
    assert any(d < s or d > e for d in dates for s, e in WINDOWS)
