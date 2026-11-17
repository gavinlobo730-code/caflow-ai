"""A payee typed with no supplier and no usable PAN is never added up by its name, and the year's earlier payments typed under the same name
are NAMED on the answer with their figures (POST-A-078, the second decision).

WHAT WAS WRONG
    A deduction typed on the TDS screen for a payee with no supplier and no usable PAN is charged as the payee's first payment of the year,
    every time, because nothing keys such a payee. Twelve Rs 15,000 commissions to one agent typed with no PAN were each "the first of the
    year", and the answer said only that the year was not looked for, so the CA was never shown that the register held eleven more.

THE DECISION, AND WHAT IS HELD
    * a NAME IS NEVER A KEY: two payees can share a name and one payee can be typed under two spellings, so the charge stays the
      first-payment charge (adding up by name would push a stranger's payments over another's threshold, the wrong deduction and wrong
      credit `usable_pan_key` exists to stop);
    * the year's earlier typed payments under the same name (case and spacing folded), the same parent section, with no supplier and no
      usable PAN, are named in a sentence with their count, taxable value and tax withheld, and with the two ways to make the year add up;
    * a bill's or an advance's row, a row that names a supplier, a row with a real PAN, another section, another year, another client and
      the row being corrected are not counted; a payee with a key is not asked this at all.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
from domain.tds import manual_register
from domain.tds.manual_register import GAP_SAME_NAME_WITHOUT_A_PAN, same_name_key, same_name_without_a_pan
from tests.e2e_harness import FakeDB

FIRM, CLIENT = "F1", "C1"
EXEC = {"id": "u2", "firm_id": FIRM, "role": "Executive", "email": "e@f1.test", "auth_user_id": "auth-exec"}
DAY = "2025-06-15"


def test_the_name_is_folded_for_comparison_only():
    assert same_name_key("  Ravi   Kumar ") == same_name_key("ravi kumar") == "ravi kumar"
    assert same_name_key("") is None and same_name_key(None) is None and same_name_key("   ") is None
    assert same_name_key("Ravi Kumar") != same_name_key("Ravi Kumaar")


def _row(db, **over):
    row = {"firm_id": FIRM, "client_id": CLIENT, "section": "194H", "deductee_name": "Ravi Kumar", "deductee_pan": None,
           "transaction_date": "2025-05-10", "payment_amount_paise": 15_000_00, "tds_paise": 0, "vendor_id": None,
           "purchase_bill_id": None, "purchase_payment_id": None}
    row.update(over)
    return db.seed("tds_deductions", row)


def _ask(db, name="ravi  KUMAR", section="194H", on=date(2025, 6, 15), exclude_id=None):
    return same_name_without_a_pan(db, firm_id=FIRM, client_id=CLIENT, section=section, deductee_name=name, on=on, exclude_id=exclude_id)


def test_earlier_typed_payments_under_the_same_name_are_counted_and_summed():
    db = FakeDB()
    _row(db)
    _row(db, deductee_pan="PANNOTAVBL", tds_paise=1_00, transaction_date="2025-04-02")
    assert _ask(db) == (2, 30_000_00, 1_00)


@pytest.mark.parametrize("label, over", [
    ("a bill's row", {"purchase_bill_id": "b1"}),
    ("an advance's row", {"purchase_payment_id": "p1"}),
    ("a row that names a supplier", {"vendor_id": "v1"}),
    ("a row with a real PAN", {"deductee_pan": "AAGCP7788R"}),
    ("another section", {"section": "194C"}),
    ("another year", {"transaction_date": "2025-03-31"}),
    ("another client", {"client_id": "C2"}),
    ("another name", {"deductee_name": "Ravi Kumaar"}),
])
def test_what_is_not_the_same_typed_payee_is_not_counted(label, over):
    db = FakeDB()
    _row(db, **over)
    assert _ask(db) == (0, 0, 0), label


def test_the_limbs_of_a_section_are_one_section_and_the_row_being_corrected_is_left_out():
    db = FakeDB()
    _row(db, section="194J(b)")
    mine = _row(db, section="194J(a)")
    assert _ask(db, section="194J(a)")[0] == 2
    assert _ask(db, section="194J(a)", exclude_id=mine["id"])[0] == 1


def test_a_blank_name_asks_nothing():
    db = FakeDB()
    _row(db, deductee_name="")
    assert _ask(db, name="  ") == (0, 0, 0)


@pytest.fixture
def app_db(monkeypatch):
    import routers.tds_workspace as mod
    db = FakeDB()
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    monkeypatch.setattr(mod, "log_event", lambda *a, **k: None)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    monkeypatch.setattr("core.db_provider.service_db_or_none", lambda: None)
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: EXEC
    return TestClient(app, raise_server_exceptions=False), db


def _post(client, path="/api/tds-workspace/deductions", **over):
    body = {"client_id": CLIENT, "deductee_name": "Ravi Kumar", "deductee_pan": None, "section": "194H",
            "payment_amount_paise": 15_000_00, "transaction_date": DAY}
    body.update(over)
    return client.post(path, json=body).json()["data"]


def test_the_second_payment_to_a_same_named_payee_is_charged_alone_and_says_the_first_exists(app_db):
    client, _db = app_db
    first = _post(client)
    assert GAP_SAME_NAME_WITHOUT_A_PAN not in first["explain"]["gaps"]
    second = _post(client, deductee_name=" ravi kumar ")
    ex = second["explain"]
    assert ex["fy_prior_taxable_paise"] == 0 and second["tds_paise"] == first["tds_paise"], "a name is never a key"
    assert GAP_SAME_NAME_WITHOUT_A_PAN in ex["gaps"]
    sentence = [m for m in ex["gap_messages"] if "same payee name" in m]
    assert len(sentence) == 1 and "1 other payment" in sentence[0] and "₹15,000.00" in sentence[0]
    assert "NOT added" in sentence[0] and "pick the supplier or record the payee's PAN" in sentence[0]


def test_the_preview_says_it_too_and_a_payee_with_a_pan_is_not_asked(app_db):
    client, _db = app_db
    _post(client)
    preview = _post(client, path="/api/tds-workspace/deductions/preview")["explain"]
    assert GAP_SAME_NAME_WITHOUT_A_PAN in preview["gaps"]
    with_pan = _post(client, deductee_pan="AAGCP7788R")["explain"]
    assert GAP_SAME_NAME_WITHOUT_A_PAN not in with_pan["gaps"]


def test_the_sentence_carries_its_own_figures_and_is_not_a_fixed_message():
    assert GAP_SAME_NAME_WITHOUT_A_PAN not in manual_register.GAP_MESSAGES
    assert "3 other payments" in manual_register.same_name_sentence(3, 45_000_00, 0)
