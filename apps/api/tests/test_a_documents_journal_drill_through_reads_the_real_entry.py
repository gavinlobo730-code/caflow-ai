"""
A document's journal drill-through reads the REAL entry, and each of its
lines now names its account (apex-sales-purchases-01 — second-client, Apex
Trading Solutions, walkthrough; Phase 7).

WHAT WAS WRONG
    Six document-view drawers — InvoiceViewDrawer, PurchaseBillViewDrawer,
    DebitNoteViewDrawer, PurchaseCreditNoteViewDrawer,
    SalesCreditNoteViewDrawer, SalesDebitNoteViewDrawer — opened their "View
    Journal" drill-through by calling `GET /api/accounting/journal` with the
    document's own date as a start/end window, then searching the result for
    the row matching `journal_entry_id`. That route answered from
    `accounting_service.list_journal_entries`, which filters
    MOCK_JOURNAL_ENTRIES — a hard-coded in-memory seed list — and never reads
    the real database, in any deployment. So the search always came back
    empty and every one of the six drawers rendered "Journal <uuid> — line
    detail unavailable here." for a posting that
    `GET /api/accounting/journal/{id}` (the real, DB-backed, single-entry
    endpoint, confirmed working) had all along. Reproduced live on invoice
    INV-BULK-02999 and purchase bill UFLPAC-26-27-0006.

    A second, smaller gap sat behind the first: even reading the right
    endpoint would only have swapped the sentence for a raw account UUID.
    `manual_journal_service.get()`'s own `journal_lines` embed carried
    `account_id` and nothing that names it — the six drawers already render
    `line.account_name ?? line.account_id ?? "—"`, so the JSX needed no
    change once the backend started sending a name.

THE FIX, PINNED HERE
    1. The six drawers now call the by-id endpoint directly with the
       document's own `journal_entry_id` — no date window, no list, no
       search. That change lives in apps/web and is not re-tested here in
       React; it is asserted structurally by
       scripts/a-document-drawers-journal-drill-through-reads-the-real-entry.test.ts.
    2. `manual_journal_service.get()` widens its existing `journal_lines`
       embed with `account:chart_of_accounts(account_name, account_code)` —
       one query, not a second round trip — and flattens it onto each line.
       Pinned below on the SELECT string and on the flattened output, against
       a FakeDB.
    3. `GET /journal` (the list route) is retired: nothing in apps/web called
       it any more once the six drawers moved to the by-id endpoint, and it
       answered from a mock in every deployment regardless. Pinned below by
       its absence from the mounted route table.

WHY A FakeDB, NOT THE MOCK-MODE `accounting_service`
    That is the whole defect: the six drawers were, in effect, reading the
    in-memory `accounting_service` engine (via the now-retired list route) in
    every real deployment, where a CA's screen needs the actual ledger.
    Pinning the fix against `accounting_service.list_journal_entries` would
    prove nothing — that engine has always "worked" against its own seed
    data. `tests.e2e_harness.FakeDB` is this repo's convention for exercising
    a router function against something that behaves like Postgres:
    `_Query._project` returns an embedded relation exactly as seeded, because
    (its own docstring) "Embeds (`a(b,c)`) ... are passed through untouched",
    which is what lets this test seed each line's `account` the way a real
    `chart_of_accounts` embed would resolve it — the same convention
    `test_accounting_client_scope.py::_seed_editable_entry` already uses for
    the outer `lines:journal_lines(...)` embed.

NEGATIVE CONTROL
    `test_the_drawers_own_call_path_names_every_account` was run against the
    pre-fix `manual_journal_service.get()` (the embed and the flattening loop
    reverted) and failed with `KeyError: 'account_name'` reading
    `l["account_name"]` — the line dict this test asserts on genuinely lacked
    the key before the fix, confirming the test exercises the real change and
    not a tautology. See this change's commit message for how that was run.
"""
from __future__ import annotations

import inspect

import routers.accounting as acct
from services.manual_journal_service import manual_journal_service as svc
from tests.e2e_harness import FakeDB, wire_e2e

FIRM, CLIENT = "firm-1", "client-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "e@f.test", "role": "Executive"}


def _e2e_setup(monkeypatch):
    db = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    wire_e2e(monkeypatch, db, [acct])
    # Client-assignment scope on this endpoint is pinned in
    # test_accounting_client_scope.py; this file is about what comes back for
    # a document the caller may already see, so it is not re-asserted here.
    monkeypatch.setattr(acct, "can_access_client", lambda user, client_id: True)
    return db


def _seed(db, **over):
    row = {
        "id": "J1", "firm_id": FIRM, "client_id": CLIENT,
        "entry_date": "2026-06-15", "reference_no": "INV/2026-27/2999",
        "narration": "Sale — INV-BULK-02999", "entry_type": "Sales",
        "is_posted": True, "is_reversed": False, "source_type": None,
        "deleted_at": None,
        # A real `account:chart_of_accounts(account_name, account_code)` embed
        # resolves to exactly this nested shape — FakeDB does not resolve
        # embeds (test_accounting_client_scope.py's own convention), so it is
        # seeded here the way Postgres would have already answered it.
        "lines": [
            {"id": "L1", "account_id": "acc-receivable", "debit_paise": 118000,
             "credit_paise": 0, "narration": "", "line_order": 0,
             "account": {"account_name": "Trade Receivables", "account_code": "1003"}},
            {"id": "L2", "account_id": "acc-sales", "debit_paise": 0,
             "credit_paise": 100000, "narration": "", "line_order": 1,
             "account": {"account_name": "Sales Revenue", "account_code": "4001"}},
            {"id": "L3", "account_id": "acc-gst-output", "debit_paise": 0,
             "credit_paise": 18000, "narration": "", "line_order": 2,
             "account": {"account_name": "GST Output Tax Payable", "account_code": "2002"}},
        ],
    }
    row.update(over)
    db.seed("journal_entries", row)
    return row


# ══ the drawer's own call path — GET /journal/{entry_id}, FakeDB-backed ═════

def test_the_drawers_own_call_path_names_every_account(monkeypatch):
    """The exact call a drawer's `openJournal()` now makes:
    GET /api/accounting/journal/{journal_entry_id} — no client_id, no date
    window, no search over a list. Reproduces the INV-BULK-02999 finding: a
    posted entry with a receivable, a revenue and a GST-output leg, each
    line's account named rather than left as a raw id."""
    db = _e2e_setup(monkeypatch)
    _seed(db)

    resp = acct.get_journal_entry("J1", current_user=USER)

    assert resp["success"] is True
    lines = resp["data"]["lines"]
    assert len(lines) == 3
    assert {l["account_name"] for l in lines} == {
        "Trade Receivables", "Sales Revenue", "GST Output Tax Payable",
    }
    assert {l["account_code"] for l in lines} == {"1003", "4001", "2002"}
    # Flattened, not carried through as a second nested shape a screen would
    # have to know about on top of every other (flat) line field.
    assert all("account" not in l for l in lines)
    assert resp["data"]["total_debit_paise"] == 118000 == resp["data"]["total_credit_paise"]


def test_a_line_with_no_resolved_account_renders_none_rather_than_raising(monkeypatch):
    """account_id carries a NOT NULL FK to chart_of_accounts (migration 003),
    so the embed is always present in production — but the flattening must
    not raise on a line that somehow carries none. A screen showing "—" beats
    a 500 on the one endpoint a CA opens to check what actually posted."""
    db = _e2e_setup(monkeypatch)
    _seed(db, lines=[
        {"id": "L1", "account_id": "acc-x", "debit_paise": 100, "credit_paise": 0,
         "narration": "", "line_order": 0},
        {"id": "L2", "account_id": "acc-y", "debit_paise": 0, "credit_paise": 100,
         "narration": "", "line_order": 1},
    ])

    resp = acct.get_journal_entry("J1", current_user=USER)

    for l in resp["data"]["lines"]:
        assert l["account_name"] is None
        assert l["account_code"] is None


def test_manual_journal_service_get_asks_for_the_account_embed():
    """A read that omits the embed has nothing to flatten — the same
    discipline `domain/accounting/line_order.REQUIRED_COLUMNS` pins for
    `line_order` itself, stated on the SELECT string rather than only on an
    end-to-end result."""
    src = inspect.getsource(svc.get)
    assert "account:chart_of_accounts(account_name, account_code)" in src, (
        "manual_journal_service.get() no longer embeds the account name/code "
        "on each line")


# ══ the mock-backed LIST route is retired, and the by-id one is not ════════

def test_the_journal_list_route_is_retired():
    """GET /api/accounting/journal (a date-windowed LIST over every entry) is
    gone. It answered from `accounting_service.list_journal_entries`, an
    in-memory MOCK_JOURNAL_ENTRIES filter, and never the real database in any
    deployment; the six drawers that searched it were the only callers left
    in apps/web (the Journal tab itself reads `journal_entries` straight over
    PostgREST) and now call the by-id route instead."""
    assert not hasattr(acct, "list_journal_entries"), (
        "the mock-backed journal LIST route is back on routers.accounting — "
        "see its own comment for why it was retired")

    import main
    journal_routes = sorted(
        f"{sorted(r.methods - {'HEAD', 'OPTIONS'})[0]} {r.path}"
        for r in main.app.routes
        if getattr(r, "path", "").startswith("/api/accounting/journal")
        and not getattr(r, "path", "").startswith("/api/accounting/journals")
        and getattr(r, "methods", None)
    )
    assert "GET /api/accounting/journal" not in journal_routes, (
        "the retired list route is mounted again")
    assert "GET /api/accounting/journal/{entry_id}" in journal_routes, (
        "the real, DB-backed single-entry route must still be mounted")


def test_the_shared_domain_function_survives_for_journal_suggestions():
    """`accounting_service.list_journal_entries` (the DOMAIN function, as
    distinct from the retired ROUTER endpoint of the same name) is NOT
    deleted: `services.intelligence_service.compute_journal_suggestions`
    (GET /api/intelligence/journal-suggestions) calls it directly in Python,
    not over HTTP, and deleting it would break that endpoint outright. It
    carries the identical mock-data defect and is a separate, unfixed finding
    — this only pins that the shared function was not collateral damage."""
    from domain.accounting_service import accounting_service
    from services.intelligence_service import compute_journal_suggestions

    assert hasattr(accounting_service, "list_journal_entries")
    assert "list_journal_entries" in inspect.getsource(compute_journal_suggestions)
