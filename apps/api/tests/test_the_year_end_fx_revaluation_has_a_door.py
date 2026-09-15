"""
THE AS 11 REVALUATION WAS BUILT, TESTED, AND UNREACHABLE.

AS 11 paragraph 11 retranslates a MONETARY item held in a foreign currency at
the CLOSING rate on each balance sheet date, and paragraph 13 takes the
difference to the profit and loss account. `FXRevaluationService.revalue` has
done exactly that since Multi-Currency Phase 4 — idempotent, self-healing,
period-lock aware, posting through the one kernel and auto-reversing on day 1
of the next period.

It had **zero production importers**. `revalue` is the only writer of
`fx_revaluations`, so `GET /api/fx-reports/unrealized` reported a structural
nil for every client however many foreign documents they held — while
`services/fx_reporting_service.py`'s own header said those tables were
"written by the Phase-4 settlement + revaluation paths", which was true of
settlement and false of revaluation. The same shape as the year-end
`capital_wip` line that nothing could reach.

ACC-19 made migration 122's three gates WRITABLE on 13-09-2026, which is what
turned a dormant phase into a live gap: a firm can now switch multi-currency
on and the year-end step it needs has no door.

This module pins the door, and — the part that matters most — that the PREVIEW
and the POSTING are one walk.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import HTTPException

from models.invoices import InvoiceLineIn, SalesInvoiceIn
from models.parties import CustomerIn
from domain.currency.fx_revaluation_service import fx_revaluation_service as REVAL
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

API = Path(__file__).resolve().parents[1]

FIRM = "FIRM-FXDOOR"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "u1",
          "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch, *, entitled=True, client_on=True):
    import routers.customers as cu
    import routers.sales_invoices as si
    import routers.fx_revaluation as fxr

    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, si, fxr])
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    db.seed("firms", {"id": FIRM, "multi_currency_entitled": entitled})
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5",
                        "functional_currency": "INR",
                        "multi_currency_enabled": client_on})
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar",
                           "minor_unit": 2, "is_active": True})
    db.seed("currencies", {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee",
                           "minor_unit": 2, "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Services", "kind": "service"})
    return cu, si, fxr, db


def _usd_invoice(si, cust_id, rate, *, cents=100_000, no="USD-001"):
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust_id, invoice_date="2025-06-01",
        invoice_no=no, currency="USD", exchange_rate=str(rate),
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Export",
                             hsn_sac="9982", quantity=1, rate_paise=cents,
                             gst_rate_percent=0.0)]), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)
    return inv


def _exposed(monkeypatch, *, entitled=True, client_on=True):
    """A client with an open USD receivable, then the gates set as asked.

    The exposure is ALWAYS created with both gates on, because a foreign
    invoice cannot be raised with multi-currency off — correctly. Turning a
    gate off afterwards is also the real situation being tested: a client who
    had it on, has foreign documents, and has since been switched off.
    """
    cu, si, fxr, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="US Buyer"), CALLER)["data"]
    _usd_invoice(si, cust["id"], "80.00")
    if not entitled:
        db.table("firms").update({"multi_currency_entitled": False}).eq("id", FIRM).execute()
    if not client_on:
        db.table("clients").update({"multi_currency_enabled": False}).eq("id", "CLI").execute()
    return fxr, db


# ── the preview writes nothing, and is the posting's own walk ────────────────

def test_the_preview_writes_NOTHING(monkeypatch):
    fxr, db = _exposed(monkeypatch)
    before = len(db.table("fx_revaluations").select("*").execute().data or [])
    before_entries = len(db.table("journal_entries").select("*").execute().data or [])

    fxr.preview_revaluation(client_id="CLI",
                            payload={"period_end": "2026-03-31",
                                     "closing_rates": {"USD": "84.00"}},
                            current_user=CALLER)

    assert len(db.table("fx_revaluations").select("*").execute().data or []) == before
    assert len(db.table("journal_entries").select("*").execute().data or []) == before_entries


def test_what_the_preview_shows_is_what_the_run_POSTS(monkeypatch):
    """One walk. Two compositions of exposure + prior runs would drift, and a
    CA would be shown one figure and post another."""
    fxr, db = _exposed(monkeypatch)
    rates = {"USD": "84.00"}
    plan = fxr.preview_revaluation(
        client_id="CLI", payload={"period_end": "2026-03-31", "closing_rates": rates},
        current_user=CALLER)["data"]
    run = fxr.run_revaluation(
        client_id="CLI", payload={"period_end": "2026-03-31", "closing_rates": rates},
        current_user=CALLER)["data"]

    planned = {(r["currency"], r["item_type"], r["item_ref"]): r["delta_paise"]
               for r in plan["rows"]}
    posted = {(r["currency"], r["item_type"], r["item_ref"]): r["delta_paise"]
              for r in run["adjustments"]}
    assert planned == posted
    assert plan["reversal_date"] == run["reversal_date"]


def test_the_preview_reaches_the_service_through_plan_not_a_second_walk():
    """Stated on the CODE, because two callers of `_exposure` would pass every
    behavioural test above on the day they were written."""
    src = (API / "domain" / "currency" / "fx_revaluation_service.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "revalue")
    body = ast.dump(fn)
    assert "'plan'" in body or '"plan"' in body, \
        "revalue must post from plan(), not from its own second walk"
    # And exactly one place computes the exposure.
    walkers = [n for n in ast.walk(tree)
               if isinstance(n, ast.Attribute) and n.attr == "_exposure"]
    assert len(walkers) == 2, (
        f"_exposure should be called by plan() and revalue() and nothing else; "
        f"found {len(walkers)} call sites")


# ── a rate nobody recorded ───────────────────────────────────────────────────

def test_the_preview_NAMES_the_currencies_when_no_rate_is_given(monkeypatch):
    """The useful first call. A CA opens the screen to find out what to go and
    look up, so the preview must answer without a rate rather than refuse."""
    fxr, db = _exposed(monkeypatch)
    plan = fxr.preview_revaluation(
        client_id="CLI", payload={"period_end": "2026-03-31"},
        current_user=CALLER)["data"]
    assert plan["currencies"] == ["USD"]
    assert plan["rate_gaps"], "a missing rate must be reported, not silently nil"
    assert "USD" in plan["rate_gaps"][0]
    assert all(r["delta_paise"] is None for r in plan["rows"])
    assert plan["would_post"] == 0


def test_the_RUN_still_refuses_a_missing_rate(monkeypatch):
    """`plan` reports and `revalue` refuses, and that difference is the point:
    an exchange difference is a real posting to the P&L and a rate nobody
    supplied cannot be guessed."""
    fxr, db = _exposed(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        fxr.run_revaluation(client_id="CLI",
                            payload={"period_end": "2026-03-31",
                                     "closing_rates": {"EUR": "90"}},
                            current_user=CALLER)
    assert exc.value.status_code == 422
    assert "USD" in str(exc.value.detail)


def test_the_run_refuses_an_EMPTY_rate_map_EVEN_WITH_NOTHING_EXPOSED(monkeypatch):
    """The distinguishing case, and the reason the endpoint guards it itself.

    With foreign exposure, `revalue` would refuse anyway — its own message
    names the currency. With NO exposure it would do nothing and return
    SUCCESS, so a CA who pressed the button having recorded no rate at all
    would be told the revaluation had run. "Nothing to revalue" and "you did
    not give me a rate" are different answers.
    """
    cu, si, fxr, db = _setup(monkeypatch)   # a client with no foreign documents
    with pytest.raises(HTTPException) as exc:
        fxr.run_revaluation(client_id="CLI",
                            payload={"period_end": "2026-03-31", "closing_rates": {}},
                            current_user=CALLER)
    assert exc.value.status_code == 422
    assert "preview" in str(exc.value.detail).lower(), \
        "the refusal must say where to find which currencies need a rate"


def test_a_non_positive_rate_is_reported_not_computed_with(monkeypatch):
    fxr, db = _exposed(monkeypatch)
    plan = fxr.preview_revaluation(
        client_id="CLI",
        payload={"period_end": "2026-03-31", "closing_rates": {"USD": "0"}},
        current_user=CALLER)["data"]
    assert plan["rate_gaps"]
    assert plan["rows"][0]["delta_paise"] is None


# ── the three gates ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("entitled,client_on", [(False, True), (True, False), (False, False)])
def test_a_gate_that_is_down_REFUSES_and_posts_nothing(monkeypatch, entitled, client_on):
    """A run that ignored the gates would post journals for a feature nobody
    switched on — the reason the three gates exist."""
    fxr, db = _exposed(monkeypatch, entitled=entitled, client_on=client_on)
    out = fxr.run_revaluation(client_id="CLI",
                              payload={"period_end": "2026-03-31",
                                       "closing_rates": {"USD": "84.00"}},
                              current_user=CALLER)
    assert out["success"] is False
    assert "Multi-Currency" in (out["error"] or "")
    assert (db.table("fx_revaluations").select("*").execute().data or []) == []


def test_a_gate_that_is_down_makes_the_PREVIEW_say_so_rather_than_lie(monkeypatch):
    fxr, db = _exposed(monkeypatch, client_on=False)
    plan = fxr.preview_revaluation(
        client_id="CLI", payload={"period_end": "2026-03-31"},
        current_user=CALLER)["data"]
    assert plan["active"] is False
    assert plan["refusal"]
    assert plan["rows"] == []


# ── posting, re-running, and the reversal ────────────────────────────────────

def test_it_posts_the_revaluation_and_its_AUTO_REVERSAL(monkeypatch):
    fxr, db = _exposed(monkeypatch)
    out = fxr.run_revaluation(client_id="CLI",
                              payload={"period_end": "2026-03-31",
                                       "closing_rates": {"USD": "84.00"}},
                              current_user=CALLER)["data"]
    adj = [a for a in out["adjustments"] if a["delta_paise"] != 0]
    assert adj, "a rate that moved must produce an adjustment"
    assert all(a["journal_entry_id"] for a in adj)
    assert all(a["reversal_entry_id"] for a in adj)
    # AS 11 paragraph 11 is a BALANCE SHEET DATE restatement; the reversal is
    # day 1 of the next period so the documents keep their booked rates.
    assert out["reversal_date"] == "2026-04-01"
    assert (db.table("fx_revaluations").select("*").execute().data or []) != []


def test_re_running_at_the_SAME_rate_posts_nothing_more(monkeypatch):
    fxr, db = _exposed(monkeypatch)
    body = {"period_end": "2026-03-31", "closing_rates": {"USD": "84.00"}}
    fxr.run_revaluation(client_id="CLI", payload=body, current_user=CALLER)
    first = len(db.table("journal_entries").select("*").execute().data or [])
    again = fxr.run_revaluation(client_id="CLI", payload=body,
                                current_user=CALLER)["data"]
    assert all(a["delta_paise"] == 0 for a in again["adjustments"])
    assert len(db.table("journal_entries").select("*").execute().data or []) == first


def test_re_running_at_a_CORRECTED_rate_posts_only_the_difference(monkeypatch):
    """The correction path. A CA who fixes a rate before the accounts are
    signed must get a correcting entry, not a duplicate — which is also why
    the panel says so."""
    fxr, db = _exposed(monkeypatch)
    fxr.run_revaluation(client_id="CLI",
                        payload={"period_end": "2026-03-31",
                                 "closing_rates": {"USD": "84.00"}},
                        current_user=CALLER)
    plan = fxr.preview_revaluation(
        client_id="CLI",
        payload={"period_end": "2026-03-31", "closing_rates": {"USD": "85.00"}},
        current_user=CALLER)["data"]
    row = plan["rows"][0]
    assert row["prior_paise"] != 0, "the first run must be visible to the second"
    assert row["delta_paise"] == row["target_paise"] - row["prior_paise"]


def test_an_OPEN_period_reports_no_problem(monkeypatch):
    fxr, db = _exposed(monkeypatch)
    plan = fxr.preview_revaluation(
        client_id="CLI",
        payload={"period_end": "2026-03-31", "closing_rates": {"USD": "84.00"}},
        current_user=CALLER)["data"]
    assert plan["period_problem"] is None


def test_a_LOCKED_year_is_reported_and_the_figures_still_shown(monkeypatch):
    """A preview of a closed year still says what the adjustment WOULD have
    been — that is the point of a preview — while naming what stops it."""
    fxr, db = _exposed(monkeypatch)
    db.table("firms").update({"locked_financial_years": ["2025-26"]}).eq("id", FIRM).execute()
    plan = fxr.preview_revaluation(
        client_id="CLI",
        payload={"period_end": "2026-03-31", "closing_rates": {"USD": "84.00"}},
        current_user=CALLER)["data"]
    assert plan["period_problem"], "a locked FY must be named"
    assert "2025-26" in plan["period_problem"]
    assert plan["rows"], "the figures are still shown; only the posting is barred"
    assert plan["rows"][0]["delta_paise"] is not None


def test_a_FINALISED_client_year_end_is_reported_too(monkeypatch):
    """The reason the preview asks `closure_reason` and not the firm-FY
    validator alone: the posting kernel refuses a finalised client year-end
    (migration 361), and a preview that asked only the firm's own switch would
    have said nothing and then failed at the button."""
    fxr, db = _exposed(monkeypatch)
    db.seed("client_year_locks", {"id": "L1", "firm_id": FIRM, "client_id": "CLI",
                                  "financial_year": "2025-26"})
    plan = fxr.preview_revaluation(
        client_id="CLI",
        payload={"period_end": "2026-03-31", "closing_rates": {"USD": "84.00"}},
        current_user=CALLER)["data"]
    assert plan["period_problem"], "a finalised client year-end must be named"
    assert "finalised" in plan["period_problem"]


def test_a_FILED_RETURN_does_NOT_bar_the_revaluation(monkeypatch):
    """CGST Rule 34 fixes the rate of exchange at the TIME OF SUPPLY, so
    restating the rupee carrying amount afterwards cannot change a figure any
    filed GSTR-1 or GSTR-3B reported. Reporting a filed return here would tell
    a CA their June return has closed this March adjustment, which is false —
    which is why the preview asks `closure_reason` and not `lock_reason`."""
    fxr, db = _exposed(monkeypatch)
    # The columns `period_lock_service.reason_from_tables` actually reads, and
    # a period that COVERS the revaluation date — the first draft of this
    # fixture invented `return_type`/`period`/`filed_at` and a June period, so
    # the filed-return branch never fired and the test could not tell
    # `closure_reason` from `lock_reason` at all.
    db.seed("filings", {"id": "F1", "firm_id": FIRM, "client_id": "CLI",
                        "filing_type": "GSTR-3B", "filed_date": "2026-04-20",
                        "period_start": "2026-03-01", "period_end": "2026-03-31",
                        "deleted_at": None})
    plan = fxr.preview_revaluation(
        client_id="CLI",
        payload={"period_end": "2026-03-31", "closing_rates": {"USD": "84.00"}},
        current_user=CALLER)["data"]
    assert plan["period_problem"] is None

    # AND THE FIXTURE IS LIVE — otherwise this test passes on a seed the
    # filed-return branch cannot see, which is exactly how the first draft
    # failed to distinguish the two functions.
    from services import period_lock_service
    assert period_lock_service.lock_reason(db, FIRM, "CLI", "2026-03-31"), \
        "the seeded filing must be visible to lock_reason, or this proves nothing"


# ── the shape of the door ────────────────────────────────────────────────────

def test_the_posting_endpoint_is_NOT_on_the_read_only_fx_reports_router():
    """`routers/fx_reports.py` says "read-only FX reporting" in its first line.
    A POST that writes journals under that prefix would make the next reader
    believe the contract still holds."""
    reports = (API / "routers" / "fx_reports.py").read_text()
    assert "@router.post" not in reports
    assert "revalue" not in reports


def test_the_two_endpoints_carry_the_right_actions():
    """The preview READS and the run CREATES. A preview behind a create
    permission would hide the working from a reviewer who may not post."""
    src = (API / "routers" / "fx_revaluation.py").read_text()
    tree = ast.parse(src)
    actions = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        # A `Depends(rbac(...))` is the DEFAULT of the parameter, not part of
        # the arg node — reading the arg alone found nothing and made this
        # test pass vacuously on the first draft.
        for default in node.args.defaults + [d for d in node.args.kw_defaults if d]:
            dump = ast.dump(default)
            if "rbac" in dump:
                actions[node.name] = dump
    assert "preview_revaluation" in actions and "run_revaluation" in actions, \
        f"no rbac dependency found on either endpoint: {sorted(actions)}"
    assert "'read'" in actions["preview_revaluation"]
    assert "'write'" in actions["run_revaluation"]


def test_both_endpoints_assert_client_scope():
    """The client_id is a caller-supplied query parameter on both."""
    src = (API / "routers" / "fx_revaluation.py").read_text()
    tree = ast.parse(src)
    for name in ("preview_revaluation", "run_revaluation"):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        assert "assert_client_access" in ast.dump(fn), \
            f"{name} does not assert client scope"


def test_the_client_row_is_fetched_INSIDE_the_firm():
    """The service-role key bypasses RLS, so the app-layer firm_id filter is
    the primary isolation control."""
    src = (API / "routers" / "fx_revaluation.py").read_text()
    assert '.eq("firm_id", firm_id)' in src


def test_nothing_schedules_this():
    """CA-initiated, one period at a time. The closing rate is a fact somebody
    records and the entry is a real posting to the P&L, so it is never swept."""
    for path in (API / "jobs").rglob("*.py"):
        assert "fx_revaluation" not in path.read_text(), \
            f"{path.name} schedules the revaluation; it is a CA action"
