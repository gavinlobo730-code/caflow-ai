"""
Recurring PURCHASE bills. PUR-26, migration 379.

WHAT WAS MISSING
    Recurring sales invoices have existed since migration 107 and recurring
    journals since 377. The purchase side had nothing, so monthly rent
    (§194I), a consultant's retainer (§194J), electricity, telecom and software
    subscriptions were re-keyed by hand for every client, every month.

WHY IT IS NOT MERELY TYPING
    Most of the §194 series charges on the YEAR'S AGGREGATE — §194C(5) and the
    "aggregate of the sums" limb in §§194A/194D/194G/194H/194J — so a month
    nobody entered does not only lose an expense. It changes what the NEXT bill
    should withhold, and with it the Rule 30(2) deposit and the quarterly
    statement.

THE RULES THIS PINS
    * DRAFTS ONLY. Nothing here receives a bill, and receiving is what posts
      Dr Expense / Dr GST Input / Cr Trade Payables, withholds the TDS and
      claims the credit. The product acts unprompted in exactly one place — a
      bank rule a Manager has marked trusted — and that was a recorded owner
      decision, not a default to copy.
    * `bill_no` IS THE VENDOR'S and is left unset. A landlord's invoice number
      is a fact about the landlord's books and it is half the key GSTR-2B
      matching uses, so inventing one puts a number the supplier never issued
      onto a document the reconciliation reads. `our_reference` — ours — is
      stamped.
    * ONE CADENCE ENGINE. `domain/recurrence` is imported, not copied: two
      cadence engines drifting means one feature generates in a month the other
      skips. Its month-end rule (clamp against the ORIGINAL day, never the
      previous occurrence) is asserted here as well as on the sales side,
      because a copy would pass its own tests while disagreeing with the twin.
    * A FAILED OCCURRENCE DOES NOT ADVANCE THE TEMPLATE. Advancing past a
      failure skips the month silently, which is the one outcome a recurring
      feature must never produce.
    * The per-line facts that decide money — `itc_eligible` (CGST §17(5)),
      `expense_account_id`, `tds_applicable` — travel on the template. Letting
      them default at generation would re-decide, every month, what the CA
      decided once.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.parties import VendorIn
import routers.purchase_bills as pb
import routers.recurring_purchase_bills as rpb
import routers.vendors as ve
from services import recurring_purchase_bill_service as svc
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-PUR26"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "u1",
          "email": "ca@f.test", "role": "Partner"}


@pytest.fixture(autouse=True)
def _clean_mock_stores():
    # wire_e2e flips every wired module's _USE_MOCK to False, so these stores
    # should stay empty — cleared anyway so a leak from another module's test
    # cannot make one here pass or fail for the wrong reason.
    svc.MOCK_RECURRING_BILL_TEMPLATES.clear()
    svc.MOCK_RECURRING_BILL_RUNS.clear()
    pb.MOCK_PURCHASE_BILLS.clear()
    yield
    svc.MOCK_RECURRING_BILL_TEMPLATES.clear()
    svc.MOCK_RECURRING_BILL_RUNS.clear()
    pb.MOCK_PURCHASE_BILLS.clear()


def _bills(db):
    """Every purchase bill the run produced, oldest first."""
    return sorted(db.rows("purchase_bills"), key=lambda b: b.get("bill_date") or "")


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, ve, svc])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-RENT", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Office rent", "kind": "service"})
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Landlord", state_code="27"),
                            CALLER)["data"]
    return db, vend["id"]


def _template(vend_id, **over):
    body = {
        "client_id": "CLI", "vendor_id": vend_id, "title": "Office rent",
        "frequency": "monthly", "start_date": "2026-04-01",
        "lines": [{"service_catalogue_id": "SVC-RENT",
                   "description": "Rent for the month", "rate_paise": 5000000,
                   "gst_rate_percent": 18.0, "is_service": True,
                   "tds_applicable": True}],
    }
    body.update(over)
    return rpb.create_recurring_bill(rpb.RecurringBillTemplateIn(**body), CALLER)["data"]


# ── The template ─────────────────────────────────────────────────────────────

def test_a_template_starts_due_on_its_own_start_date(monkeypatch):
    db, vend = _setup(monkeypatch)
    t = _template(vend)
    assert t["next_run_date"] == "2026-04-01"
    assert t["status"] == "active"
    assert len(t["lines"]) == 1


def test_a_template_needs_at_least_one_line(monkeypatch):
    db, vend = _setup(monkeypatch)
    with pytest.raises(Exception):
        rpb.create_recurring_bill(rpb.RecurringBillTemplateIn(
            client_id="CLI", vendor_id=vend, title="x", frequency="monthly",
            start_date="2026-04-01", lines=[]), CALLER)


def test_an_end_date_before_the_start_is_refused(monkeypatch):
    db, vend = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _template(vend, end_date="2026-03-01")
    assert e.value.status_code == 422


def test_the_line_facts_that_decide_money_are_stored(monkeypatch):
    """§17(5) eligibility, the expense account and TDS applicability are the
    CA's decisions about WHAT is being bought, not about the month."""
    db, vend = _setup(monkeypatch)
    t = _template(vend, lines=[{
        "service_catalogue_id": "SVC-RENT",
        "description": "Club membership", "rate_paise": 100000,
        "gst_rate_percent": 18.0, "is_service": True,
        "itc_eligible": False, "blocked_credit_reason": "s.17(5)(b)(ii)",
        "tds_applicable": False, "expense_account_id": None,
    }])
    ln = t["lines"][0]
    assert ln["itc_eligible"] is False
    assert ln["blocked_credit_reason"] == "s.17(5)(b)(ii)"
    # Basis points on the template, percent on the bill — one conversion.
    assert ln["gst_rate_bps"] == 1800


# ── Generation ───────────────────────────────────────────────────────────────

def test_a_due_template_generates_a_draft_bill(monkeypatch):
    db, vend = _setup(monkeypatch)
    t = _template(vend)
    out = rpb.run_one_recurring_bill(t["id"], as_of="2026-04-05",
                                     current_user=CALLER)["data"]
    assert out["generated_count"] == 1
    bill = _bills(db)[0]
    assert bill["status"] == "draft", "receiving is the CA's act — it posts the AP journal"
    assert bill["bill_date"] == "2026-04-01"
    assert bill["recurring_template_id"] == t["id"]
    assert bill["recurring_occurrence"] == "2026-04-01"


def test_the_vendors_own_bill_number_is_not_invented(monkeypatch):
    """It is half the key GSTR-2B matching uses. `our_reference` is ours."""
    db, vend = _setup(monkeypatch)
    t = _template(vend)
    rpb.run_one_recurring_bill(t["id"], as_of="2026-04-05", current_user=CALLER)
    bill = _bills(db)[0]
    assert not bill.get("bill_no")
    assert (bill.get("our_reference") or "").startswith("RECUR-")
    assert "supplier's own bill number" in (bill.get("notes") or "")


def test_the_bill_engine_computes_the_tax_not_this_service(monkeypatch):
    """Reusing create_purchase_bill is what makes a generated bill identical to
    a typed one — GST, the §17(5) split and the vendor's TDS section."""
    db, vend = _setup(monkeypatch)
    t = _template(vend)
    rpb.run_one_recurring_bill(t["id"], as_of="2026-04-05", current_user=CALLER)
    bill = _bills(db)[0]
    assert bill["taxable_amount_paise"] == 5000000
    # Intra-state (client 27, vendor 27): CGST + SGST at 9% each, no IGST.
    assert bill["cgst_paise"] == 450000
    assert bill["sgst_paise"] == 450000
    assert bill["igst_paise"] == 0
    assert bill["total_paise"] == 5900000


def test_running_twice_generates_one_bill(monkeypatch):
    """One occurrence, one bill — the runs ledger and the partial unique index
    both say so, and a catch-up sweep must be safe to re-run."""
    db, vend = _setup(monkeypatch)
    t = _template(vend)
    rpb.run_one_recurring_bill(t["id"], as_of="2026-04-05", current_user=CALLER)
    # The template has advanced, so a second run at the same as_of does nothing
    # at all; force it back to the same occurrence to exercise the idempotency
    # check itself rather than the cursor.
    svc._set_next_run(FIRM, t["id"], "2026-04-01", None)
    out = rpb.run_one_recurring_bill(t["id"], as_of="2026-04-05",
                                     current_user=CALLER)["data"]
    assert out["generated_count"] == 0
    assert out["skipped_count"] == 1
    assert len(_bills(db)) == 1


def test_a_missed_quarter_catches_up_month_by_month(monkeypatch):
    """The whole point on the purchase side: a month nobody entered changes what
    the next bill withholds, because most of the §194 series charges on the
    year's aggregate. So catch-up generates EACH month, not one bill for the
    gap."""
    db, vend = _setup(monkeypatch)
    t = _template(vend)
    out = rpb.run_one_recurring_bill(t["id"], as_of="2026-06-15",
                                     current_user=CALLER)["data"]
    assert out["generated_count"] == 3
    assert [b["bill_date"] for b in _bills(db)] == [
        "2026-04-01", "2026-05-01", "2026-06-01"]


def test_a_month_end_template_clamps_against_the_original_day(monkeypatch):
    """domain/recurrence's rule, asserted on this side too. Clamping against the
    PREVIOUS occurrence walks a 31 January series permanently back to the 28th
    after one February."""
    db, vend = _setup(monkeypatch)
    t = _template(vend, start_date="2027-01-31")
    rpb.run_one_recurring_bill(t["id"], as_of="2027-03-31", current_user=CALLER)
    assert [b["bill_date"] for b in _bills(db)] == [
        "2027-01-31", "2027-02-28", "2027-03-31"]


def test_a_template_stops_at_its_end_date(monkeypatch):
    db, vend = _setup(monkeypatch)
    t = _template(vend, end_date="2026-05-31")
    out = rpb.run_one_recurring_bill(t["id"], as_of="2026-12-31",
                                     current_user=CALLER)["data"]
    assert out["generated_count"] == 2


def test_a_paused_template_generates_nothing(monkeypatch):
    db, vend = _setup(monkeypatch)
    t = _template(vend)
    rpb.pause_recurring_bill(t["id"], current_user=CALLER)
    with pytest.raises(HTTPException) as e:
        rpb.run_one_recurring_bill(t["id"], as_of="2026-06-01", current_user=CALLER)
    assert e.value.status_code == 422
    assert _bills(db) == []
    # And the firm-wide sweep skips it too.
    out = rpb.run_due_recurring_bills(client_id="CLI", as_of="2026-06-01",
                                      current_user=CALLER)["data"]
    assert out["generated_count"] == 0


def test_a_failed_occurrence_is_recorded_and_the_template_does_not_advance(monkeypatch):
    """Advancing past a failure skips the month silently — the one outcome a
    recurring feature must never produce."""
    db, vend = _setup(monkeypatch)
    t = _template(vend)

    def _boom(bill_in, actor):
        return {"success": False, "data": None, "error": "vendor is inactive"}
    monkeypatch.setattr(pb, "create_purchase_bill", _boom)

    out = rpb.run_one_recurring_bill(t["id"], as_of="2026-04-05",
                                     current_user=CALLER)["data"]
    assert out["failed_count"] == 1
    assert out["generated_count"] == 0
    assert svc.get_template(FIRM, t["id"])["next_run_date"] == "2026-04-01"
    runs = svc.template_history(FIRM, t["id"])
    assert [r["status"] for r in runs] == ["failed"]
    assert "vendor is inactive" in str(runs[0]["detail"])


def test_the_history_names_the_bill_each_occurrence_produced(monkeypatch):
    db, vend = _setup(monkeypatch)
    t = _template(vend)
    rpb.run_one_recurring_bill(t["id"], as_of="2026-05-15", current_user=CALLER)
    runs = rpb.history_recurring_bill(t["id"], current_user=CALLER)["data"]
    assert len(runs) == 2
    assert all(r["status"] == "generated" for r in runs)
    assert all((r["bill"] or {}).get("status") == "draft" for r in runs)


def test_the_preview_says_which_dates_are_coming(monkeypatch):
    db, vend = _setup(monkeypatch)
    t = _template(vend, frequency="quarterly")
    occ = rpb.preview_recurring_bill(t["id"], count=3, current_user=CALLER)["data"]["occurrences"]
    assert occ == ["2026-04-01", "2026-07-01", "2026-10-01"]


# ── Scope ────────────────────────────────────────────────────────────────────

def test_a_template_from_another_firm_is_not_found(monkeypatch):
    db, vend = _setup(monkeypatch)
    t = _template(vend)
    other = {**CALLER, "firm_id": "FIRM-OTHER"}
    with pytest.raises(HTTPException) as e:
        rpb.get_recurring_bill(t["id"], current_user=other)
    assert e.value.status_code == 404


def test_the_sweep_reaches_the_scheduler(monkeypatch):
    """A feature the daily job does not run is a feature the CA still has to
    remember, which is the thing this closes."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "jobs/scheduler.py"
    text = src.read_text()
    assert "generate_due_recurring_bills" in text
    assert '_already_ran_today("recurring_purchase_bills"' in text


def test_one_cadence_engine_and_this_module_does_not_hold_a_second(monkeypatch):
    """The rule CLAUDE.md states for exactly this: two cadence engines drifting
    means one feature generates in a month the other skips."""
    import inspect
    from domain import recurrence
    text = inspect.getsource(svc)
    assert "from domain import recurrence" in text
    assert svc.next_occurrence is recurrence.next_occurrence
    body = text.split('"""', 2)[-1]          # drop the module docstring
    assert "def next_occurrence" not in body
    assert "def add_months_clamped" not in body


def test_a_line_with_no_product_is_refused_at_save_time(monkeypatch):
    """PurchaseBillLineIn has required a catalogue item since migration 206, so
    a template without one could only fail inside the unattended 06:00 IST job
    — the worst place to discover it. The refusal moves to the moment the CA is
    looking at the form."""
    db, vend = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        svc.create_template(FIRM, {
            "client_id": "CLI", "vendor_id": vend, "title": "x",
            "frequency": "monthly", "start_date": "2026-04-01",
            "lines": [{"description": "Rent", "rate_paise": 100}],
        }, "u1", db)
    assert e.value.status_code == 422
    assert "Product/Service" in str(e.value.detail)


# ── The other end of the schema chain ────────────────────────────────────────

def test_every_updatable_field_is_a_column_the_create_path_writes():
    """`tests/test_backend_columns_exist_pg.py` checks a write's columns against
    the real schema only when they are written as a dict LITERAL, and a PATCH's
    key set is variable — so `update_template`'s `.update(fields)` cannot be
    one. It costs a unit of that test's budget and its columns go unchecked.

    So `create_template`'s INSERT is a literal (verified against Postgres
    there) and this asserts the update's field set is a SUBSET of those names.
    Add a field the table has no column for and this fails in MOCK mode, with
    no database needed. Same shape, same reason, as the recurring-journal
    twin's test of the same name.

    `updated_at` is the one exemption and is named rather than inferred: the
    create path leaves it to the column's own DEFAULT now(), so it is a real
    column that the INSERT legitimately does not mention.
    """
    import ast
    import inspect
    import pathlib as _p

    from services import recurring_purchase_bill_service as svc

    tree = ast.parse(_p.Path(inspect.getfile(svc)).read_text())

    def _fn(name):
        return next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == name)

    upd = _fn("update_template")
    updatable: set = set()
    # `for k in ("title", ...): ... fields[k] = data[k]`
    for n in ast.walk(upd):
        if (isinstance(n, ast.For) and isinstance(n.iter, ast.Tuple)
                and any(isinstance(x, ast.Subscript)
                        and getattr(x.value, "id", None) == "fields"
                        for b in n.body for x in ast.walk(b))):
            updatable |= {e.value for e in n.iter.elts
                          if isinstance(e, ast.Constant)}
    # `fields["start_date"] = ...`
    for n in ast.walk(upd):
        if not isinstance(n, ast.Assign):
            continue
        for t in n.targets:
            if (isinstance(t, ast.Subscript)
                    and getattr(t.value, "id", None) == "fields"
                    and isinstance(t.slice, ast.Constant)
                    and isinstance(t.slice.value, str)):
                updatable.add(t.slice.value)
    assert updatable, "the scan found no updatable fields — it has stopped matching"

    insert_keys = next(
        {k.value for k in call.args[0].keys}
        for call in ast.walk(_fn("create_template"))
        if isinstance(call, ast.Call)
        and getattr(call.func, "attr", None) == "insert"
        and call.args and isinstance(call.args[0], ast.Dict))

    extra = updatable - insert_keys - {"updated_at"}
    assert extra == set(), (
        f"update_template can write {sorted(extra)}, which create_template does "
        f"not — either it is not a column of recurring_purchase_bill_templates, "
        f"or the create path is missing it")


def test_the_line_insert_names_its_columns_where_the_schema_check_can_read_them():
    """`.insert(_line_rows(...))` is a CALL and invisible to the schema check,
    so a wrong column there would never be caught. `_insert_lines` restates the
    names as a comprehension over dict literals, and BOTH the create and the
    update replacement go through it — a second `.insert(` on the line table
    anywhere else in the module puts the blind spot straight back."""
    import ast
    import inspect
    import pathlib as _p

    from services import recurring_purchase_bill_service as svc

    src = _p.Path(inspect.getfile(svc)).read_text()
    tree = ast.parse(src)
    sites = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) == "insert"
             and isinstance(n.func.value, ast.Call)
             and getattr(n.func.value.func, "attr", None) == "table"
             and n.func.value.args
             and isinstance(n.func.value.args[0], ast.Constant)
             and n.func.value.args[0].value
             == "recurring_purchase_bill_template_lines"]
    assert len(sites) == 1, (
        f"{len(sites)} places insert template lines — there must be exactly "
        f"one, so the column names are stated once where the schema check can "
        f"read them")
    payload = sites[0].args[0]
    assert isinstance(payload, ast.ListComp) and isinstance(payload.elt, ast.Dict), (
        "the line insert's payload must be a comprehension over a dict LITERAL "
        "— a call or a bare name is invisible to "
        "tests/test_backend_columns_exist_pg.py")
