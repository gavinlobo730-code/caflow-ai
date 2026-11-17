"""A hub worklist and the firm's risk register leave the firm's own practice out of the clients they count and list (POST-A-457, Guardrail G2).

WHAT WAS WRONG
    The firm's own practice is a `clients` row (`is_internal = true`), and G2 says it is not one of the firm's clients to count, list, score or
    chase. The POST-A-169 census found two reads that did: `hub_worklist_service._client_count` counted it among the clients a hub worklist
    examined (and the rows, from `hub_client_worklist`, listed it for a Partner and for the API's own call), and
    `risk_register_service.build_register` listed it on the firm's risk register like any client.

WHAT IS HELD (mock mode; migration 706's SQL half is held by `tests/test_706_..._pg.py`)
    * the Python twin of the worklist leaves the practice's rows out, and the count beside them does not count it;
    * the risk register lists nothing of the practice (no overdue filing, no inactivity, no loan, no notice), says so in a note when there
      was something to leave out, and says nothing when there was not.
"""
from __future__ import annotations

import pytest

from services import hub_worklist_service
from services import risk_register_service as service
from tests._hub_worklist_double import Double
from tests.e2e_harness import FakeDB

FIRM = "firm-g2"
A, P = "client-a", "client-practice"


def _double() -> Double:
    return Double({
        "fixed_assets": [
            {"id": "1", "firm_id": FIRM, "client_id": A, "depreciation_posted_through": None},
            {"id": "2", "firm_id": FIRM, "client_id": P, "depreciation_posted_through": None},
            {"id": "3", "firm_id": FIRM, "client_id": P, "depreciation_posted_through": None},
        ],
        "clients": [
            {"id": A, "firm_id": FIRM, "client_name": "Acme", "legal_name": None, "entity_type": "LLP"},
            {"id": P, "firm_id": FIRM, "client_name": "Our Practice", "legal_name": None, "entity_type": "Partnership",
             "is_internal": True},
        ],
    })


def test_the_worklist_twin_leaves_the_practice_out_of_its_rows_and_its_count(monkeypatch):
    d = _double()
    monkeypatch.setattr(hub_worklist_service, "_db", lambda: d)
    monkeypatch.setattr(hub_worklist_service, "effective_client_ids", lambda u: None)
    out = hub_worklist_service.worklist({"firm_id": FIRM}, "fixed_assets")
    assert [(r["client_id"], r["signal"]) for r in out["rows"]] == [(A, 1)]
    assert out["clients_examined"] == 1


def _register_db(with_practice_rows: bool = True) -> FakeDB:
    db = FakeDB()
    db.seed("clients", {"id": A, "firm_id": FIRM, "client_name": "Acme Ltd", "gstin": "", "pan": "AABCU9603R", "is_internal": False})
    db.seed("clients", {"id": P, "firm_id": FIRM, "client_name": "Our Practice", "gstin": "", "pan": "AABFP1234Q", "is_internal": True})
    if with_practice_rows:
        db.seed("compliance_calendar", {"id": "cal-p", "firm_id": FIRM, "client_id": P, "compliance_type": "GSTR3B",
                                        "due_date": "2020-01-20", "filing_status": "pending"})
        db.seed("loans", {"id": "loan-p", "firm_id": FIRM, "client_id": P, "lender_name": "Bank", "loan_type": "term",
                          "outstanding_paise": 100_000_00, "status": "overdue"})
        db.seed("government_notices", {"id": "n-p", "firm_id": FIRM, "client_id": P, "notice_type": "income_tax",
                                       "authority": "Income Tax Dept", "reference_no": None, "issue_date": "2026-10-01",
                                       "response_due_date": "2026-10-30", "status": "open", "ca_approved": False})
    db.seed("compliance_calendar", {"id": "cal-a", "firm_id": FIRM, "client_id": A, "compliance_type": "GSTR3B",
                                    "due_date": "2020-01-20", "filing_status": "pending"})
    return db


def test_the_risk_register_lists_nothing_of_the_practice_and_says_so():
    payload = service.build_register(_register_db(), FIRM, None)
    assert {r["client_id"] for r in payload["rows"] if r["client_id"]} == {A}
    assert not any(r["client_name"] == "Our Practice" for r in payload["rows"])
    assert any("own practice is not on this register" in n for n in payload["notes"])


def test_a_register_with_nothing_of_the_practice_carries_no_note_about_it():
    payload = service.build_register(_register_db(with_practice_rows=False), FIRM, None)
    assert not any("own practice" in n for n in payload["notes"])
    assert P not in {r["client_id"] for r in payload["rows"]}


@pytest.mark.parametrize("scope", [None, {A, P}])
def test_the_practice_is_left_out_whatever_scope_names_it(scope):
    payload = service.build_register(_register_db(), FIRM, scope)
    assert P not in {r["client_id"] for r in payload["rows"]}
