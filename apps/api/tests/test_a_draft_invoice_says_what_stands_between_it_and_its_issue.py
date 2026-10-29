"""A draft sales invoice says what stands between it and its issue, before the click, and the refusal carries a code (POST-A-125).

The issue route used to refuse with one English sentence, the first that failed, after the editor had already saved the draft and
chained the issue. This holds the new contract on four sides:

  * the pure vocabulary (`domain/sales/issue_readiness`): every code offers the action it should, and the accounts the posting needs
    follow the tax heads the invoice carries;
  * the readiness list on invoices the API itself created (the positive control that matters most: a legitimate draft has no blocker),
    then broken one way at a time and several ways at once;
  * the issue route refusing from THAT list, with its first blocker, in the status and the words it always used, plus a code and an
    action (a missing chart of accounts stays an HTTP 200 with `success: false`, as it has always been);
  * the pre-flight reading and writing nothing.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.sales_invoices as si
from domain.sales import issue_readiness as ir
from models.invoices import InvoiceLineIn, SalesInvoiceIn
from services import issue_readiness_service as service
from services import period_lock_service
from services.period_validation_service import period_validation_service
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


# ── the pure vocabulary ─────────────────────────────────────────────────────────────────────────────────────────

def test_every_code_offers_the_action_it_should_and_only_known_ones():
    assert set(ir.ACTION_FOR) == set(ir.CODES), "a code without an entry in ACTION_FOR offers nothing by accident"
    for code, action in ir.ACTION_FOR.items():
        if action is not None:
            assert action["kind"] in ir.ACTION_KINDS, code
            assert action["label"].strip(), code
            if action["kind"] == ir.ACTION_FIX_IN_EDITOR:
                assert action["field"] in ir.EDITOR_FIELDS, code
    # A locked period and an issued document are not the editor's to fix: a Partner reopens the year, a later period's amendment
    # carries a correction, a credit note adjusts an issued invoice. Offering a button would be offering a way round them. A draft that
    # does not add up can be a tampered figure, a stale total or a carried-over flag, and re-saving the lines mends only the first.
    for code in (ir.NOT_A_DRAFT, ir.PERIOD_LOCKED, ir.DRAFT_DOES_NOT_ADD_UP):
        assert ir.ACTION_FOR[code] is None
    assert ir.ACTION_FOR[ir.COA_MISSING]["kind"] == ir.ACTION_SEED_CHART_OF_ACCOUNTS


def test_a_blocker_is_built_only_from_a_known_code():
    assert ir.blocker(ir.COA_MISSING, "x").as_dict() == {
        "code": "COA_MISSING", "message": "x", "action": {"kind": "seed_chart_of_accounts", "label": "Set up the chart of accounts"}}
    with pytest.raises(AssertionError):
        ir.blocker("SOMETHING_ELSE", "x")


@pytest.mark.parametrize("pos,expected", [("27", None), ("29", None), ("96", None), ("", ir.PLACE_OF_SUPPLY_MISSING),
                                          (None, ir.PLACE_OF_SUPPLY_MISSING), ("  ", ir.PLACE_OF_SUPPLY_MISSING),
                                          ("00", ir.PLACE_OF_SUPPLY_INVALID), ("2", ir.PLACE_OF_SUPPLY_INVALID),
                                          ("MH", ir.PLACE_OF_SUPPLY_INVALID)])
def test_the_place_of_supply_is_missing_invalid_or_fine(pos, expected):
    got = ir.place_of_supply_problem(pos)
    assert (got[0] if got else None) == expected
    if got:
        assert "Rule 46(n)" in got[1] and "Cannot issue" in got[1]
        assert ("missing" in got[1]) == (expected == ir.PLACE_OF_SUPPLY_MISSING)


def test_the_accounts_the_posting_needs_follow_the_heads_the_invoice_carries():
    def labels(**inv):
        return [a.label for a in ir.required_accounts(inv)]

    assert labels() == ["Trade Receivables", "Sales"]
    assert labels(cgst_paise=9, sgst_paise=9) == ["Trade Receivables", "Sales", "GST Output (CGST)", "GST Output (SGST)"]
    assert labels(igst_paise=18) == ["Trade Receivables", "Sales", "GST Output (IGST)"]
    assert labels(igst_paise=18, cess_paise=5, round_off_paise=-30) == [
        "Trade Receivables", "Sales", "GST Output (IGST)", "Compensation Cess Payable", "Round Off"]
    assert labels(igst_paise=None, cess_paise=0, round_off_paise=0) == ["Trade Receivables", "Sales"]


# ── the readiness list, on invoices the API created ────────────────────────────────────────────────────────────

def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2", "financial_year_start": "2025-04-01"})
    db.seed("customers", {"id": "CUST-CLI", "firm_id": FIRM, "client_id": "CLI", "name": "Acme", "is_active": True,
                          "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-CLI", "firm_id": FIRM, "client_id": "CLI", "name": "Goods", "kind": "good"})
    return db


def _new_invoice(no="INV-1", **kw):
    kw.setdefault("supply_state_code", "27")
    line = InvoiceLineIn(description="item", quantity=1, rate_paise=100_000, gst_rate_percent=18.0, service_catalogue_id="SVC-CLI")
    res = si.create_invoice(SalesInvoiceIn(client_id="CLI", customer_id="CUST-CLI", invoice_no=no, invoice_date="2025-06-01",
                                           lines=kw.pop("lines", [line]), **kw), CALLER)
    assert res["success"] is True, res
    return res["data"]["id"]


def _row(db, doc_id):
    return next(r for r in db.rows("client_sales_invoices") if r["id"] == doc_id)


def _preflight(invoice_id):
    res = si.issue_preflight(invoice_id, CALLER)
    assert res["success"] is True, res
    return res["data"]


def _codes(data):
    return [b["code"] for b in data["blockers"]]


def test_a_draft_the_api_created_has_no_blocker(monkeypatch):
    """THE POSITIVE CONTROL. A pre-flight that blocked a legitimate draft would be worse than none."""
    _setup(monkeypatch)
    data = _preflight(_new_invoice())
    assert data == {"ready": True, "blockers": []}


def test_the_pre_flight_and_the_issue_agree_a_ready_draft_is_issued(monkeypatch):
    _setup(monkeypatch)
    inv = _new_invoice()
    assert _preflight(inv)["ready"] is True
    assert si.issue_invoice(inv, CALLER)["success"] is True


def test_a_placeholder_number_is_a_blocker_with_an_editor_action(monkeypatch):
    db = _setup(monkeypatch)
    inv = _new_invoice("INV-PLACE")
    _row(db, inv)["invoice_no"] = "DRAFT-ABCDEFGHIJ"
    data = _preflight(inv)
    assert data["ready"] is False and _codes(data) == [ir.INVOICE_NO_PLACEHOLDER]
    blocker = data["blockers"][0]
    assert "placeholder number DRAFT-ABCDEFGHIJ" in blocker["message"]
    assert blocker["action"] == {"kind": "fix_in_editor", "field": "invoice_no", "label": "Enter the invoice number"}


def test_a_number_rule_46b_does_not_allow_is_a_blocker(monkeypatch):
    db = _setup(monkeypatch)
    inv = _new_invoice("INV-LEGAL")
    _row(db, inv)["invoice_no"] = "INV 2025/0001 #"
    assert _codes(_preflight(inv)) == [ir.INVOICE_NO_NOT_ALLOWED]


@pytest.mark.parametrize("value,code", [("", ir.PLACE_OF_SUPPLY_MISSING), ("99", ir.PLACE_OF_SUPPLY_INVALID)])
def test_a_missing_or_invalid_place_of_supply_is_a_blocker(monkeypatch, value, code):
    db = _setup(monkeypatch)
    inv = _new_invoice("INV-POS")
    _row(db, inv)["supply_state_code"] = value
    data = _preflight(inv)
    assert _codes(data) == [code]
    assert data["blockers"][0]["action"]["field"] == "supply_state"


def test_several_blockers_are_listed_in_the_order_the_route_refuses_in(monkeypatch):
    """Number first, then the place of supply: the order the issue route has always asked in, so the first entry is the refusal."""
    db = _setup(monkeypatch)
    inv = _new_invoice("INV-MANY")
    row = _row(db, inv)
    row["invoice_no"], row["supply_state_code"] = "DRAFT-ABCDEFGHIJ", ""
    assert _codes(_preflight(inv)) == [ir.INVOICE_NO_PLACEHOLDER, ir.PLACE_OF_SUPPLY_MISSING]


def test_a_draft_that_does_not_add_up_to_its_lines_is_a_blocker(monkeypatch):
    db = _setup(monkeypatch)
    inv = _new_invoice("INV-SUM")
    _row(db, inv)["total_paise"] += 1_000
    data = _preflight(inv)
    assert _codes(data) == [ir.DRAFT_DOES_NOT_ADD_UP] and "its total is" in data["blockers"][0]["message"]
    assert data["blockers"][0]["action"] is None


def test_a_carried_over_draft_is_a_blocker_that_offers_nothing_the_editor_could_do(monkeypatch):
    """The flag is not mended by re-saving the lines, so no button says it is."""
    db = _setup(monkeypatch)
    inv = _new_invoice("INV-OPEN")
    _row(db, inv)["is_opening"] = True
    data = _preflight(inv)
    assert _codes(data) == [ir.DRAFT_DOES_NOT_ADD_UP] and "carried-over" in data["blockers"][0]["message"]
    assert data["blockers"][0]["action"] is None


def test_a_missing_chart_of_accounts_names_the_accounts_and_offers_to_set_it_up(monkeypatch):
    db = _setup(monkeypatch)
    inv = _new_invoice("INV-COA")
    # Receivables, and every account the GST heads can be found by (the posting falls back to a name match when no key matches).
    db._tables["chart_of_accounts"] = [r for r in db.rows("chart_of_accounts")
                                       if r.get("system_account_key") != "ar" and "GST Output" not in r["account_name"]]
    data = _preflight(inv)
    assert _codes(data) == [ir.COA_MISSING]
    message = data["blockers"][0]["message"]
    assert "Trade Receivables" in message and "GST Output (CGST)" in message and "GST Output (SGST)" in message
    assert "GST Output (IGST)" not in message and ", Sales" not in message, "only what this invoice needs and lacks is named"
    assert "%" not in message, "the sentence names accounts a person knows, not the pattern the posting searched"
    assert data["blockers"][0]["action"]["kind"] == "seed_chart_of_accounts"


def test_an_issued_invoice_has_one_blocker_and_nothing_after_it_is_asked(monkeypatch):
    db = _setup(monkeypatch)
    inv = _new_invoice("INV-DONE")
    assert si.issue_invoice(inv, CALLER)["success"] is True
    _row(db, inv)["supply_state_code"] = ""
    data = _preflight(inv)
    assert _codes(data) == [ir.NOT_A_DRAFT] and data["blockers"][0]["message"] == "Only draft invoices can be issued"
    assert data["blockers"][0]["action"] is None


def test_a_locked_year_is_one_blocker_and_the_second_lock_is_not_asked(monkeypatch):
    """`assert_open` answers for the closures too, so it repeats a locked year. One cause is one blocker, in the lock's own words."""
    _setup(monkeypatch)
    inv = _new_invoice("INV-LOCK")
    asked = []

    def locked_year(firm_id, date):
        raise HTTPException(status_code=422, detail="Financial year 2025-26 is locked.")

    def second(db, firm_id, client_id, date, cache=None):
        asked.append(date)
        raise HTTPException(status_code=422, detail="Financial year 2025-26 is locked.")

    monkeypatch.setattr(period_validation_service, "validate_posting_date", locked_year)
    monkeypatch.setattr(period_lock_service, "assert_open", second)
    data = _preflight(inv)
    assert _codes(data) == [ir.PERIOD_LOCKED] and data["blockers"][0]["message"] == "Financial year 2025-26 is locked."
    assert data["blockers"][0]["action"] is None
    assert asked == [], "the client's lock repeats the firm's year, so it is asked only when the firm's year did not refuse"


def test_a_filed_return_or_a_finalised_year_is_a_blocker_with_no_editor_action(monkeypatch):
    _setup(monkeypatch)
    inv = _new_invoice("INV-FILED")

    def filed_return(db, firm_id, client_id, date, cache=None):
        raise HTTPException(status_code=422, detail="GSTR-1 for June 2025 has been filed.")

    monkeypatch.setattr(period_lock_service, "assert_open", filed_return)
    data = _preflight(inv)
    assert _codes(data) == [ir.PERIOD_LOCKED]
    assert data["blockers"][0]["message"] == "GSTR-1 for June 2025 has been filed." and data["blockers"][0]["action"] is None


def test_the_pre_flight_reads_and_writes_nothing(monkeypatch):
    db = _setup(monkeypatch)
    inv = _new_invoice("INV-READ")
    _row(db, inv)["supply_state_code"] = ""
    before = {t: [dict(r) for r in rows] for t, rows in db._tables.items()}
    _preflight(inv)
    _preflight(inv)
    after = {t: [dict(r) for r in rows] for t, rows in db._tables.items()}
    assert before == after, "every table is as it was, not only the ones the author thought of"


def test_an_unknown_invoice_is_a_404_in_the_words_a_missing_row_gets(monkeypatch):
    _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        si.issue_preflight("NO-SUCH-INVOICE", CALLER)
    assert e.value.status_code == 404 and e.value.detail == "Invoice NO-SUCH-INVOICE not found"


# ── the issue route refuses from the same list ──────────────────────────────────────────────────────────────────

def test_the_issue_refuses_with_the_first_blocker_and_carries_its_code_and_action(monkeypatch):
    db = _setup(monkeypatch)
    inv = _new_invoice("INV-REF")
    row = _row(db, inv)
    row["invoice_no"], row["supply_state_code"] = "DRAFT-ABCDEFGHIJ", ""
    first = _preflight(inv)["blockers"][0]
    with pytest.raises(HTTPException) as e:
        si.issue_invoice(inv, CALLER)
    assert e.value.status_code == 422
    assert e.value.detail == {"message": first["message"], "code": first["code"], "action": first["action"]}
    assert row["status"] == "draft" and not db.rows("journal_entries"), "nothing was posted"


def test_the_issue_keeps_the_words_the_route_always_used_for_a_place_of_supply(monkeypatch):
    db = _setup(monkeypatch)
    inv = _new_invoice("INV-WORDS")
    _row(db, inv)["supply_state_code"] = ""
    with pytest.raises(HTTPException) as e:
        si.issue_invoice(inv, CALLER)
    assert e.value.detail["code"] == ir.PLACE_OF_SUPPLY_MISSING
    assert e.value.detail["message"].startswith("Cannot issue — place of supply is missing. CGST Rule 46(n) requires it")


def test_a_missing_chart_of_accounts_stays_an_http_200_that_did_not_succeed_and_carries_its_code(monkeypatch):
    """The editor and the bulk callers branch on `success: false`, so the one refusal that was never an HTTP error keeps its shape."""
    db = _setup(monkeypatch)
    inv = _new_invoice("INV-COA2")
    db._tables["chart_of_accounts"] = []
    res = si.issue_invoice(inv, CALLER)
    assert res["success"] is False and res["error"].startswith("Cannot issue — the chart of accounts has no account for:")
    assert res["data"]["code"] == ir.COA_MISSING and res["data"]["action"]["kind"] == "seed_chart_of_accounts"
    assert _row(db, inv)["status"] == "draft"


def test_a_check_that_refused_with_an_http_error_becomes_an_entry_and_not_an_exception(monkeypatch):
    """A check that raised an HTTPException used to end the route; here each is caught and becomes an entry."""
    db = _setup(monkeypatch)
    inv = _new_invoice("INV-NORAISE")
    row = _row(db, inv)
    row["status"] = "issued"
    assert [b.code for b in service.blockers_for_sales_invoice(db, FIRM, row)] == [ir.NOT_A_DRAFT]
    row["status"], row["supply_state_code"] = "draft", ""
    assert [b.code for b in service.blockers_for_sales_invoice(db, FIRM, row)] == [ir.PLACE_OF_SUPPLY_MISSING]


def test_the_issue_stops_at_the_first_blocker_and_asks_no_later_check_the_preflight_asks_them_all(monkeypatch):
    """`first_only` is what keeps the issue as it always was: a bad number never reaches the reads after it (the draft's lines, the
    chart of accounts), so an error in one of those cannot turn a plain refusal into a generic failure."""
    db = _setup(monkeypatch)
    inv = _new_invoice("INV-FIRST")
    row = _row(db, inv)
    row["invoice_no"], row["supply_state_code"] = "DRAFT-ABCDEFGHIJ", ""
    later = []
    from services import draft_integrity_service
    from services.phase2_journal_service import phase2_journal_service
    monkeypatch.setattr(draft_integrity_service, "assert_draft_adds_up", lambda *a, **k: later.append("lines"))
    monkeypatch.setattr(phase2_journal_service, "missing_accounts_for_sales_invoice", lambda *a, **k: later.append("accounts") or [])
    first = service.blockers_for_sales_invoice(db, FIRM, row, first_only=True)
    assert [b.code for b in first] == [ir.INVOICE_NO_PLACEHOLDER] and later == []
    everything = service.blockers_for_sales_invoice(db, FIRM, row)
    assert [b.code for b in everything] == [ir.INVOICE_NO_PLACEHOLDER, ir.PLACE_OF_SUPPLY_MISSING] and later == ["lines", "accounts"]

    with pytest.raises(HTTPException):
        si.issue_invoice(inv, CALLER)
    assert later == ["lines", "accounts"], "the issue route added no call to the later checks"
