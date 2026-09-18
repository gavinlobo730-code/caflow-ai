"""The §43B(h) working reads the ledger, and the endpoint that serves it.

PUR-15's second half. The rule is
`domain/income_tax/section_43b_h.py` and is tested in
tests/test_section_43b_h_msme_disallowance.py. These are about what a domain
test cannot see: that the SERVICE fetches the right rows, and that the
ENDPOINT is wired and guarded.

THE WHOLE POINT OF THE FIX is that nothing is typed twice. `msme_payments` —
the hand-keyed side table `/accounting/msme-tracker` used to write — is
neither read nor written here, and a test below asserts that from the source,
because "we stopped reading it" is exactly the kind of claim that quietly
stops being true.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

import routers.income_tax as it
import services.msme_43bh_service as svc

FIRM, CLIENT, FY = "firm-1", "client-1", "2025-26"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1",
        "email": "p@f.in", "role": "Partner"}


class _Q:
    def __init__(self, store, table, calls):
        self.store, self.table, self.calls = store, table, calls
        self.f, self.isnull, self.ins, self.notnull = {}, {}, {}, set()
        self.gt = None

    def select(self, cols="*", **k):
        self.calls.append({"table": self.table, "select": cols})
        return self

    def eq(self, k, v): self.f[k] = v; return self
    def is_(self, k, v): self.isnull[k] = v; return self
    def in_(self, k, v): self.ins[k] = [str(x) for x in v]; return self
    def gt(self, k, v): self.gt = (k, v); return self
    def order(self, *a, **k): return self
    def limit(self, n): return self

    @property
    def not_(self):
        outer = self

        class _Not:
            def is_(self, k, v):
                outer.notnull.add(k)
                return outer
        return _Not()

    def execute(self):
        rows = [r for r in self.store.get(self.table, [])
                if all(r.get(k) == v for k, v in self.f.items())]
        for k, v in self.isnull.items():
            rows = [r for r in rows if r.get(k) is None]
        for k in self.notnull:
            rows = [r for r in rows if r.get(k) is not None]
        for k, vals in self.ins.items():
            rows = [r for r in rows if str(r.get(k)) in vals]
        if self.gt:
            rows = [r for r in rows if str(r.get(self.gt[0])) > str(self.gt[1])]
        rows = sorted(rows, key=lambda r: str(r.get("id")))
        self.calls[-1]["filters"] = dict(self.f)
        return type("R", (), {"data": rows})()


class _DB:
    def __init__(self, store): self.store, self.calls = store, []
    def table(self, name): return _Q(self.store, name, self.calls)


def _store(**over):
    s = {
        "vendors": [
            {"id": "v1", "firm_id": FIRM, "client_id": CLIENT,
             "name": "Acme Tools", "msme_status": "micro",
             "msmed_agreement_days": None},
        ],
        "purchase_bills": [
            {"id": "b1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "v1",
             "bill_no": "INV-1", "bill_date": "2025-05-01", "status": "received",
             "total_paise": 1_18_000, "taxable_amount_paise": 1_00_000,
             "tds_paise": 0, "ineligible_itc_igst_paise": 0,
             "ineligible_itc_cgst_paise": 0, "ineligible_itc_sgst_paise": 0},
        ],
        "purchase_payment_allocations": [],
        "purchase_payments": [],
        "fixed_assets": [],
    }
    s.update(over)
    return _DB(s)


# ── the fetch ────────────────────────────────────────────────────────────────

def test_it_derives_the_disallowance_from_the_bills():
    out = svc.for_financial_year(_store(), FIRM, CLIENT, FY)
    assert out["disallowed_paise"] == 1_00_000
    assert out["bills"][0]["due_by"] == "2025-05-16"


def test_it_reads_only_this_firm_and_this_client():
    """The service-role key bypasses RLS, so the app-layer filter is the
    isolation. Another client's unpaid MSME bill is another client's
    disallowance."""
    db = _store()
    db.store["purchase_bills"].append(
        {**db.store["purchase_bills"][0], "id": "b2", "client_id": "other"})
    db.store["purchase_bills"].append(
        {**db.store["purchase_bills"][0], "id": "b3", "firm_id": "other-firm"})
    out = svc.for_financial_year(db, FIRM, CLIENT, FY)
    assert [b["bill_id"] for b in out["bills"]] == ["b1"]
    for call in db.calls:
        if call["table"] in ("purchase_bills", "vendors", "fixed_assets"):
            assert call["filters"]["firm_id"] == FIRM
            assert call["filters"]["client_id"] == CLIENT


@pytest.mark.parametrize("status", ["draft", "cancelled"])
def test_a_draft_or_cancelled_bill_is_not_a_liability(status):
    """A draft is not payable and a cancelled bill is not owed, so neither can
    be late under MSMED §15."""
    db = _store()
    db.store["purchase_bills"][0]["status"] = status
    out = svc.for_financial_year(db, FIRM, CLIENT, FY)
    assert out["bills"] == []
    assert out["disallowed_paise"] == 0


def test_the_payment_date_comes_off_the_payment_not_the_allocation():
    db = _store()
    db.store["purchase_payments"] = [
        {"id": "p1", "firm_id": FIRM, "payment_date": "2025-05-10"}]
    db.store["purchase_payment_allocations"] = [
        {"id": "a1", "purchase_payment_id": "p1", "purchase_bill_id": "b1",
         "allocated_paise": 1_18_000, "is_voided": False}]
    out = svc.for_financial_year(db, FIRM, CLIENT, FY)
    assert out["disallowed_paise"] == 0
    assert out["bills"][0]["paid_in_time_paise"] == 1_18_000


def test_a_voided_allocation_settled_nothing():
    """A reversed payment's allocations are voided rather than deleted
    (migration 226). Counting one would show a bill as paid in time that was
    never paid at all."""
    db = _store()
    db.store["purchase_payments"] = [
        {"id": "p1", "firm_id": FIRM, "payment_date": "2025-05-10"}]
    db.store["purchase_payment_allocations"] = [
        {"id": "a1", "purchase_payment_id": "p1", "purchase_bill_id": "b1",
         "allocated_paise": 1_18_000, "is_voided": True}]
    out = svc.for_financial_year(db, FIRM, CLIENT, FY)
    assert out["disallowed_paise"] == 1_00_000
    assert out["bills"][0]["unpaid_paise"] == 1_18_000


def test_a_written_agreement_on_the_vendor_lengthens_the_limit():
    db = _store()
    db.store["vendors"][0]["msmed_agreement_days"] = 45
    out = svc.for_financial_year(db, FIRM, CLIENT, FY)
    assert out["bills"][0]["limit_days"] == 45
    assert out["bills"][0]["due_by"] == "2025-06-15"


def test_blocked_tax_is_part_of_the_deduction_and_creditable_tax_is_not():
    """§17(5) tax is capitalised or expensed, so it IS claimed; creditable GST
    is input tax credit and is not a deduction at all."""
    db = _store()
    db.store["purchase_bills"][0]["ineligible_itc_cgst_paise"] = 9_000
    db.store["purchase_bills"][0]["ineligible_itc_sgst_paise"] = 9_000
    out = svc.for_financial_year(db, FIRM, CLIENT, FY)
    assert out["bills"][0]["deductible_paise"] == 1_18_000
    assert out["disallowed_paise"] == 1_18_000


def test_a_bill_capitalised_into_an_asset_disallows_nothing():
    db = _store()
    db.store["fixed_assets"] = [
        {"id": "fa1", "firm_id": FIRM, "client_id": CLIENT,
         "purchase_bill_id": "b1", "deleted_at": None}]
    out = svc.for_financial_year(db, FIRM, CLIENT, FY)
    assert out["disallowed_paise"] == 0
    assert "Capitalised" in out["bills"][0]["reason"]


def test_a_soft_deleted_asset_does_not_excuse_a_bill():
    """Migration 351 makes a soft-deleted asset a row created by mistake. If it
    still counted, deleting the asset would silently remove the disallowance."""
    db = _store()
    db.store["fixed_assets"] = [
        {"id": "fa1", "firm_id": FIRM, "client_id": CLIENT,
         "purchase_bill_id": "b1", "deleted_at": "2025-06-01T00:00:00Z"}]
    out = svc.for_financial_year(db, FIRM, CLIENT, FY)
    assert out["disallowed_paise"] == 1_00_000


def test_every_live_bill_is_read_not_only_this_years():
    """An EARLIER year's bill paid late during this year comes back as a
    deduction now, so the fetch cannot be filtered to the year."""
    db = _store()
    db.store["purchase_bills"].append(
        {**db.store["purchase_bills"][0], "id": "b0", "bill_date": "2024-05-01"})
    db.store["purchase_payments"] = [
        {"id": "p1", "firm_id": FIRM, "payment_date": "2025-09-01"}]
    db.store["purchase_payment_allocations"] = [
        {"id": "a1", "purchase_payment_id": "p1", "purchase_bill_id": "b0",
         "allocated_paise": 1_18_000, "is_voided": False}]
    out = svc.for_financial_year(db, FIRM, CLIENT, FY)
    assert out["allowed_on_payment_paise"] == 1_00_000
    assert len(out["bills"]) == 2


def test_the_bills_come_back_oldest_first():
    db = _store()
    db.store["purchase_bills"].append(
        {**db.store["purchase_bills"][0], "id": "b0", "bill_no": "INV-0",
         "bill_date": "2025-04-01"})
    out = svc.for_financial_year(db, FIRM, CLIENT, FY)
    assert [b["bill_no"] for b in out["bills"]] == ["INV-0", "INV-1"]


def test_a_bill_with_no_date_does_not_break_the_sort():
    """`bill_date` is NOT NULL in the schema but arrives through `_iso`, which
    returns None on anything unparseable — and comparing None to a date raises
    TypeError in Python where Postgres sorted it happily."""
    db = _store()
    db.store["purchase_bills"].append(
        {**db.store["purchase_bills"][0], "id": "b9", "bill_date": "01-05-2025"})
    out = svc.for_financial_year(db, FIRM, CLIENT, FY)
    assert out["bills"][0]["bill_date"] is None


def test_the_hand_keyed_side_table_is_neither_read_nor_written():
    """THE POINT OF THE FIX. `msme_payments` is what the screen used to write
    and the working used to read. Dropping the table is a migration and an
    owner decision; not reading it is neither, and it is the half that stops
    the figure drifting from the books."""
    import ast
    import inspect
    # Comments and docstrings stripped first: this module NAMES the table in
    # its own docstring, explaining why it does not read it, and a guard
    # satisfied by a sentence about the contract is worse than no guard —
    # this codebase has been caught by that twice.
    tree = ast.parse(inspect.getsource(svc))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body[0].value.value = ""
    assert "msme_payments" not in ast.unparse(tree)


# ── the endpoint ─────────────────────────────────────────────────────────────

@pytest.fixture
def _wired(monkeypatch):
    db = _store()
    monkeypatch.setattr(it, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(it, "_db", lambda: db)
    return db


def test_the_endpoint_serves_the_working(_wired):
    out = it.msme_section_43bh(client_id=CLIENT, fy=FY, current_user=USER)
    assert out["success"] is True
    assert out["data"]["disallowed_paise"] == 1_00_000


def test_the_endpoint_is_client_scoped(monkeypatch):
    seen = {}
    monkeypatch.setattr(it, "assert_client_access",
                        lambda user, cid: seen.setdefault("cid", cid))
    monkeypatch.setattr(it, "_db", lambda: None)
    it.msme_section_43bh(client_id=CLIENT, fy=FY, current_user=USER)
    assert seen["cid"] == CLIENT


def test_the_endpoint_says_it_files_nothing():
    import inspect
    src = inspect.getsource(it.msme_section_43bh)
    assert "CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT" in src
    # And the trap that catches CAs out is on the endpoint's own docstring.
    assert "first proviso to" in src


def test_the_fy_is_validated_rather_than_taken_as_a_string():
    """`2026-28` passes a shape regex and then means 2026-27 — a wrong year,
    not a rejected request. models/fy.FYLabel is what refuses it."""
    import inspect
    sig = inspect.signature(it.msme_section_43bh)
    assert "FYLabel" in str(sig.parameters["fy"].annotation)


# ── the vendor's written agreement is recordable ─────────────────────────────

def test_the_agreement_days_can_be_recorded_and_taken_back():
    """A period recorded by mistake gives a supplier grace MSMED §2(b) does
    not, so un-recording it has to stay available — the same reason
    msme_status accepts null."""
    from routers.accounting import AgeingClassifyIn
    assert AgeingClassifyIn(client_id=CLIENT, target="vendor", target_id="v1",
                            msmed_agreement_days=45).msmed_agreement_days == 45
    body = AgeingClassifyIn(client_id=CLIENT, target="vendor", target_id="v1",
                            msmed_agreement_days=None)
    assert "msmed_agreement_days" in body.model_dump(exclude_unset=True)


@pytest.mark.parametrize("bad", [0, -1])
def test_a_non_positive_agreement_period_is_refused(bad):
    from services.ageing_schedule_service import classify
    with pytest.raises(HTTPException) as e:
        classify(None, FIRM, CLIENT, "vendor", "v1",
                 {"msmed_agreement_days": bad})
    assert e.value.status_code == 422
    assert "positive number" in str(e.value.detail)


def test_a_period_over_forty_five_is_STORED_and_capped_only_in_the_engine():
    """The proviso to §15 makes a longer period ineffective, not the contract
    void. Storing 60 and computing on 45 keeps the record true and the
    computation lawful; a CHECK at 45 would force the CA to record a period
    their own contract does not say."""
    from services.ageing_schedule_service import classify
    from domain.income_tax.section_43b_h import limit_days
    with pytest.raises(HTTPException) as e:      # no db configured — 503, not 422
        classify(None, FIRM, CLIENT, "vendor", "v1", {"msmed_agreement_days": 60})
    assert e.value.status_code == 503
    assert limit_days(60)[0] == 45


# ── MSMED §16 rides on the same working (PUR-15's remaining half) ─────────────
#
# §43B(h) defers a DEDUCTION; §16 makes the buyer liable to the SUPPLIER for
# compound interest with monthly rests at three times the RBI Bank Rate, which
# §23 then disallows outright. A working that reports only the add-back reports
# the smaller of the two numbers, so the service carries both.

def test_the_working_carries_the_section_16_debt_as_well_as_the_deferral():
    out = svc.for_financial_year(_store(), FIRM, CLIENT, FY)
    assert "msmed_interest" in out, (
        "§16 is a different number from §43B(h) and has to be one of them")
    interest = out["msmed_interest"]
    assert interest["amounts"], "the unpaid bill missed §15, so §16 reaches it"
    assert interest["amounts"][0]["from_date"] == "2025-05-17", (
        "§16 runs 'from the date immediately following' the appointed day, "
        "which §43B(h) already computed as 2025-05-16")


def test_without_a_bank_rate_the_charge_is_refused_and_the_working_survives():
    """A screen showing nothing until a rate is typed reads as broken, and a
    nil charge would read as 'nothing is owed'. Neither is true."""
    out = svc.for_financial_year(_store(), FIRM, CLIENT, FY)
    interest = out["msmed_interest"]
    assert interest["interest_paise"] is None
    assert interest["charged_rate_bps"] is None
    assert interest["gaps"], "the refusal names what to go and look up"
    assert interest["amounts"][0]["months"] >= 0, "the working is intact"


def test_a_supplied_bank_rate_is_tripled_and_charged():
    out = svc.for_financial_year(_store(), FIRM, CLIENT, FY, bank_rate_bps=675)
    interest = out["msmed_interest"]
    assert interest["bank_rate_bps"] == 675
    assert interest["charged_rate_bps"] == 2025, "§16 charges THREE times"
    assert interest["interest_paise"] is not None


def test_the_endpoint_passes_the_rate_through(_wired):
    out = it.msme_section_43bh(client_id=CLIENT, fy=FY, bank_rate_bps=675,
                               current_user=USER)
    assert out["data"]["msmed_interest"]["charged_rate_bps"] == 2025


def test_the_endpoint_answers_section_16_in_mock_mode_too(monkeypatch):
    """A screen reading `msmed_interest` must not have to branch on which
    backend answered — the `capital_wip` shape, where a key present on one
    path and absent on the other is a null nobody can tell from a nil."""
    monkeypatch.setattr(it, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(it, "_db", lambda: None)
    out = it.msme_section_43bh(client_id=CLIENT, fy=FY, current_user=USER)
    assert "msmed_interest" in out["data"]
    assert out["data"]["msmed_interest"]["interest_paise"] is None


def test_the_bank_rate_is_the_callers_and_is_never_defaulted():
    """It moves by RBI notification partway through a year, and a delay
    spanning a change is governed by more than one. A default would be a figure
    nobody read off a notification — and §16 triples it."""
    import inspect
    sig = inspect.signature(it.msme_section_43bh)
    assert sig.parameters["bank_rate_bps"].default is None
    assert inspect.signature(svc.for_financial_year).parameters[
        "bank_rate_bps"].default is None
