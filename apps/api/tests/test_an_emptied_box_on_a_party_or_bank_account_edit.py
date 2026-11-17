"""An emptied box on the customer, vendor and bank-account edits clears what it held, or is refused in words; never "saved" over the old value (POST-A-399).

WHAT WAS WRONG
    The three PATCH routes read their body with `model_dump(exclude_none=True)`. The vendor screens and the bank-account screen sent an emptied box as
    `undefined` or `null`, so it reached the route as nothing, the stored value stayed, and the screen said the record was saved. The customer screen sent
    an emptied box as "", which the route wrote: a contact particular was stored as "" rather than NULL, a credit limit emptied to "no limit" (null) was
    dropped, and an emptied GSTIN, PAN or TAN was stored as "" — silently turning every document already issued to the customer from a registered
    recipient's into an unregistered one's in every return not yet filed, because those returns read the customer's GSTIN live.

WHAT THIS HOLDS
    * a contact particular (e-mail, phone, address, city, state, PIN code) and the credit limit sent as null or blank are written NULL, on the customer
      and on the vendor, and in the customer's and the vendor's mock-mode branches;
    * on the vendor, the answers whose NULL is "nobody has said" (the payment terms, the treaty rate, the residential status, the GST registration
      status, the nature of income, the payee class) are cleared by a null;
    * a tax identifier a return reads (a party's GSTIN and state code, a vendor's PAN and foreign tax number) sent empty over a stored value is REFUSED
      with a sentence and nothing is written; sent empty over nothing it writes nothing (never a stored "");
    * a customer's PAN and TAN, which no return reads (the TAN steers only the 26AS deductor match, the PAN prints on the invoice and matches a related
      party), sent as null or blank are written NULL: the refusal's own reason, "every return not yet filed reads it", would be untrue of them;
    * what is not clearable still reads null as "not sent": the customer's credit days (NOT NULL), the vendor's no-PE declaration reference (evidence),
      the bank account's ledger link;
    * the bank account's IFSC sent as null is cleared, and the rest of the edit behaves as before;
    * a stored non-resident vendor's country cleared on its own is refused, because the row the edit would leave is one the model refuses.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.banking as bank
import routers.customers as cu
import routers.vendors as ve
from models.banking import BankAccountUpdateIn
from models.parties import CUSTOMER_IDENTIFIERS, PARTY_IDENTIFIERS, CustomerUpdateIn, VendorUpdateIn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "id": "u1", "email": "ca@firma.test", "role": "Partner"}
#: A GSTIN with a check digit that matches, from `tests/fixtures/gstin.json` (the shared Python and browser fixture).
GSTIN = "27AAPFU0939F1ZV"


CONTACT = {"email": "a@b.in", "phone": "9876543210", "address": "1 MG Road", "city": "Pune", "state": "Maharashtra", "pincode": "411001"}


def _row(db, table, row_id):
    return next(r for r in db.rows(table) if r["id"] == row_id)


# ── the customer ───────────────────────────────────────────────────────────────────────────────────────────────────

def _customer(monkeypatch, **over):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu])
    row = {"id": "CUST", "firm_id": FIRM, "client_id": "CLI", "name": "Acme", "gstin": GSTIN, "state_code": GSTIN[:2],
           "pan": GSTIN[2:12], "tan": "PNEA12345B", "credit_days": 15, "credit_limit_paise": 5_000_000, "opening_balance_paise": 0,
           "is_active": True, **CONTACT}
    row.update(over)
    db.seed("customers", row)
    return db


@pytest.mark.parametrize("sent", [None, ""])
def test_a_customers_contact_particulars_and_credit_limit_sent_empty_are_cleared(monkeypatch, sent):
    db = _customer(monkeypatch)
    body = {k: sent for k in CONTACT}
    out = cu.update_customer("CUST", CustomerUpdateIn(**body, credit_limit_paise=None), CALLER)
    assert out["success"] is True, out
    row = _row(db, "customers", "CUST")
    assert all(row[k] is None for k in CONTACT), {k: row[k] for k in CONTACT}
    assert row["credit_limit_paise"] is None, "an emptied credit limit is 'no limit recorded', and the screen said saved while the old limit stayed"
    assert row["gstin"] == GSTIN and row["credit_days"] == 15, "what was not sent is left alone"


def test_a_customers_credit_days_sent_as_null_are_not_a_clear(monkeypatch):
    db = _customer(monkeypatch)
    out = cu.update_customer("CUST", CustomerUpdateIn(credit_days=None, name="Acme Ltd"), CALLER)
    assert out["success"] is True and _row(db, "customers", "CUST")["credit_days"] == 15


@pytest.mark.parametrize("field", ["gstin", "state_code"])
@pytest.mark.parametrize("sent", [None, ""])
def test_a_customers_tax_identifier_emptied_over_a_stored_one_is_refused_and_nothing_is_written(monkeypatch, field, sent):
    db = _customer(monkeypatch)
    before = dict(_row(db, "customers", "CUST"))
    with pytest.raises(HTTPException) as e:
        cu.update_customer("CUST", CustomerUpdateIn(**{field: sent}, email="new@b.in"), CALLER)
    assert e.value.status_code == 422
    assert f"The {PARTY_IDENTIFIERS[field]} on file can be corrected but not removed" in e.value.detail
    assert _row(db, "customers", "CUST") == before, "a refused edit wrote something"


@pytest.mark.parametrize("sent", [None, ""])
def test_a_customers_pan_and_tan_sent_empty_are_cleared_because_no_return_reads_them(monkeypatch, sent):
    db = _customer(monkeypatch)
    out = cu.update_customer("CUST", CustomerUpdateIn(pan=sent, tan=sent), CALLER)
    assert out["success"] is True, out
    row = _row(db, "customers", "CUST")
    assert (row["pan"], row["tan"]) == (None, None), "an emptied PAN or TAN was refused or kept, with a reason (a return reads it) that is untrue of a customer"
    assert row["gstin"] == GSTIN and row["state_code"] == GSTIN[:2], "what was not sent is left alone"


def test_the_customer_edit_refuses_to_empty_only_what_a_return_reads():
    """The customer's refusal set is the GSTIN and the state code; the PAN and the TAN are clearable instead, and no field is both."""
    assert set(CUSTOMER_IDENTIFIERS) == {"gstin", "state_code"}
    assert {"pan", "tan"} <= CustomerUpdateIn.CLEARABLE
    assert not (set(CUSTOMER_IDENTIFIERS) & CustomerUpdateIn.CLEARABLE)


def test_a_customers_empty_identifier_over_nothing_writes_nothing_and_never_a_blank(monkeypatch):
    db = _customer(monkeypatch, gstin=None, pan=None, tan=None, state_code=None)
    out = cu.update_customer("CUST", CustomerUpdateIn(gstin="", pan="", tan="", state_code="", name="Acme"), CALLER)
    assert out["success"] is True, out
    row = _row(db, "customers", "CUST")
    assert (row["gstin"], row["pan"], row["tan"], row["state_code"]) == (None, None, None, None)


def test_a_customers_identifier_can_still_be_corrected(monkeypatch):
    db = _customer(monkeypatch)
    out = cu.update_customer("CUST", CustomerUpdateIn(tan="PNEB54321C"), CALLER)
    assert out["success"] is True and _row(db, "customers", "CUST")["tan"] == "PNEB54321C"


def test_the_mock_mode_branch_of_the_customer_edit_clears_too(monkeypatch):
    monkeypatch.setattr(cu, "_USE_MOCK", True)
    monkeypatch.setattr(cu, "MOCK_CUSTOMERS", [{"id": "M1", "firm_id": FIRM, "client_id": "CLI", "name": "M", "email": "m@b.in", "gstin": None}])
    monkeypatch.setattr(cu, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(cu, "_load_customer_or_404", lambda user, cid: next(c for c in cu.MOCK_CUSTOMERS if c["id"] == cid))
    out = cu.update_customer("M1", CustomerUpdateIn(email=None), CALLER)
    assert out["success"] is True and out["data"]["email"] is None


# ── the vendor ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _vendor(monkeypatch, **over):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [ve])
    row = {"id": "VEN", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier", "gstin": GSTIN, "state_code": GSTIN[:2],
           "pan": GSTIN[2:12], "credit_days": 30, "credit_limit_paise": 9_000_000, "opening_balance_paise": 0, "is_active": True,
           "residential_status": "resident", "gst_registration_status": "registered", "treaty_rate_bps": 1000, "country_of_residence": None,
           "tax_identification_number": "TIN-77", "no_pe_declaration_ref": "DECL-1", "tds_section": "194C", **CONTACT}
    row.update(over)
    db.seed("vendors", row)
    return db


def test_a_vendors_soft_particulars_and_unstated_answers_sent_as_null_are_cleared(monkeypatch):
    db = _vendor(monkeypatch)
    cleared = {**{k: None for k in CONTACT}, "credit_limit_paise": None, "credit_days": None, "treaty_rate_bps": None,
               "residential_status": None, "gst_registration_status": None}
    out = ve.update_vendor("VEN", VendorUpdateIn(**cleared), CALLER)
    assert out["success"] is True, out
    row = _row(db, "vendors", "VEN")
    assert all(row[k] is None for k in cleared), {k: row[k] for k in cleared}
    assert row["no_pe_declaration_ref"] == "DECL-1" and row["gstin"] == GSTIN


def test_a_vendors_no_pe_reference_is_evidence_and_a_null_for_it_is_not_a_clear(monkeypatch):
    db = _vendor(monkeypatch)
    out = ve.update_vendor("VEN", VendorUpdateIn(no_pe_declaration_ref=None, name="Supplier Ltd"), CALLER)
    assert out["success"] is True and _row(db, "vendors", "VEN")["no_pe_declaration_ref"] == "DECL-1"


@pytest.mark.parametrize("field", ["gstin", "pan", "state_code", "tax_identification_number"])
def test_a_vendors_tax_identifier_emptied_over_a_stored_one_is_refused(monkeypatch, field):
    db = _vendor(monkeypatch)
    before = dict(_row(db, "vendors", "VEN"))
    with pytest.raises(HTTPException) as e:
        ve.update_vendor("VEN", VendorUpdateIn(**{field: None}), CALLER)
    assert e.value.status_code == 422 and "can be corrected but not removed" in e.value.detail
    assert _row(db, "vendors", "VEN") == before


def test_a_stored_non_residents_country_cleared_alone_is_refused_because_the_row_would_lose_it(monkeypatch):
    """The model asks that a non-resident carries a country only of what one request sends; a PATCH clearing just the country never sends the
    status, so the route asks the row the edit would leave (Form 27Q reports the country on every deductee row, and Rule 37BC's relief from the
    s.206AA floor rests on it)."""
    from models.parties import NON_RESIDENT_NEEDS_COUNTRY

    db = _vendor(monkeypatch, residential_status="non_resident", country_of_residence="AE", tds_section=None)
    before = dict(_row(db, "vendors", "VEN"))
    # A null only: a blank country is refused by the model's two-letter check before the route is reached.
    with pytest.raises(HTTPException) as e:
        ve.update_vendor("VEN", VendorUpdateIn(country_of_residence=None), CALLER)
    assert e.value.status_code == 422 and e.value.detail == NON_RESIDENT_NEEDS_COUNTRY
    assert _row(db, "vendors", "VEN") == before, "a refused edit wrote something"


def test_a_non_residents_country_is_cleared_with_the_status_and_a_residents_alone(monkeypatch):
    db = _vendor(monkeypatch, residential_status="non_resident", country_of_residence="AE", tds_section=None)
    out = ve.update_vendor("VEN", VendorUpdateIn(country_of_residence=None, residential_status=None), CALLER)
    assert out["success"] is True, out
    row = _row(db, "vendors", "VEN")
    assert (row["residential_status"], row["country_of_residence"]) == (None, None)
    db = _vendor(monkeypatch, residential_status="resident", country_of_residence="IN")
    out = ve.update_vendor("VEN", VendorUpdateIn(country_of_residence=None), CALLER)
    assert out["success"] is True and _row(db, "vendors", "VEN")["country_of_residence"] is None


def test_the_mock_mode_branch_of_the_vendor_edit_clears_too(monkeypatch):
    monkeypatch.setattr(ve, "_USE_MOCK", True)
    monkeypatch.setattr(ve, "MOCK_VENDORS", [{"id": "M1", "firm_id": FIRM, "client_id": "CLI", "name": "M", "phone": "9876543210"}])
    monkeypatch.setattr(ve, "_load_vendor_or_404", lambda user, vid: next(v for v in ve.MOCK_VENDORS if v["id"] == vid))
    out = ve.update_vendor("M1", VendorUpdateIn(phone=None), CALLER)
    assert out["success"] is True and out["data"]["phone"] is None


# ── the bank account ───────────────────────────────────────────────────────────────────────────────────────────────

def _bank(monkeypatch):
    db = FakeDB()
    db.seed("bank_accounts", {"id": "BA", "firm_id": FIRM, "client_id": "CLI", "bank_name": "HDFC Bank", "ifsc": "HDFC0000123",
                              "account_type": "Current", "opening_balance_paise": 0, "coa_account_id": "COA-1", "is_active": True})
    monkeypatch.setattr(bank, "_db", lambda: db)
    return db


def test_a_bank_accounts_ifsc_sent_as_null_is_cleared_and_the_ledger_link_is_not(monkeypatch):
    db = _bank(monkeypatch)
    out = bank.update_bank_account("BA", BankAccountUpdateIn(bank_name="HDFC Bank", ifsc=None, coa_account_id=None), current_user=CALLER)
    assert out["success"] is True, out
    row = _row(db, "bank_accounts", "BA")
    assert row["ifsc"] is None, "the screen said the account was saved and the old IFSC stayed"
    assert row["coa_account_id"] == "COA-1", "the ledger link is not cleared by an edit"


def test_a_bank_account_edit_that_does_not_send_the_ifsc_leaves_it(monkeypatch):
    db = _bank(monkeypatch)
    out = bank.update_bank_account("BA", BankAccountUpdateIn(bank_name="HDFC"), current_user=CALLER)
    assert out["success"] is True and _row(db, "bank_accounts", "BA")["ifsc"] == "HDFC0000123"


# ── the screen says the server's sentence ────────────────────────────────────────────────────────────────────────

def test_the_screens_refusal_is_the_servers_sentence_word_for_word():
    """Held from the side that owns the sentence: the route's words, rendered for a label, are what `lib/forms/editedValue.removedIdentifierProblem` builds."""
    from pathlib import Path

    from models.clearable import removed_identifier_problem

    said = removed_identifier_problem(CustomerUpdateIn(gstin=""), {"gstin": GSTIN}, {"gstin": "<LABEL>"})
    assert said and said.count("<LABEL>") == 2
    first, second = said.split(". ", 1)
    ts = (Path(__file__).resolve().parents[2] / "web" / "lib" / "forms" / "editedValue.ts").read_text(encoding="utf-8")
    assert ("`" + first.replace("<LABEL>", "${label}") + ". `") in ts, "the screen's first sentence is not the server's"
    assert ('"' + second + '"') in ts, "the screen's second sentence is not the server's"
