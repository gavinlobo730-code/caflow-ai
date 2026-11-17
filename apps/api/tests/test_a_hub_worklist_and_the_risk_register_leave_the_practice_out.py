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


# ── the firm hub's tiles agree with the worklists they open (an independent review, 17-11-2026) ─────────────────────────────────────
# The worklist behind each of five firm-hub tiles left the practice out (above) while the tile's own figure still counted it for a Partner,
# so a tile and the list it opens disagreed. Each of the five now equals the sum of its worklist's rows; the client hub is untouched.

from services import hub_service  # noqa: E402

_FIVE = ("banking", "sales", "purchases", "fixed_assets", "year_end")


def _both_clients(tile_rows: dict[str, list[dict]]) -> Double:
    tables: dict[str, list[dict]] = {"clients": [
        {"id": A, "firm_id": FIRM, "client_name": "Acme", "legal_name": None, "entity_type": "LLP"},
        {"id": P, "firm_id": FIRM, "client_name": "Our Practice", "legal_name": None, "entity_type": "Partnership", "is_internal": True},
    ]}
    tables.update(tile_rows)
    return Double(tables)


def _seed_every_tile() -> Double:
    rows: dict[str, list[dict]] = {"bank_transactions": [], "client_sales_invoices": [], "purchase_bills": [], "fixed_assets": [],
                                   "year_end_engagements": []}
    n = 0
    for cid, k in ((A, 1), (P, 3)):
        for _ in range(k):
            n += 1
            rows["bank_transactions"].append({"id": f"b{n}", "firm_id": FIRM, "client_id": cid, "entry_state": "needs_you"})
            rows["client_sales_invoices"].append({"id": f"s{n}", "firm_id": FIRM, "client_id": cid, "outstanding_paise": 1_000 * n,
                                                  "status": "issued", "deleted_at": None})
            rows["purchase_bills"].append({"id": f"p{n}", "firm_id": FIRM, "client_id": cid, "outstanding_paise": 700 * n,
                                           "status": "approved", "deleted_at": None})
            rows["fixed_assets"].append({"id": f"f{n}", "firm_id": FIRM, "client_id": cid, "depreciation_posted_through": None})
            rows["year_end_engagements"].append({"id": f"y{n}", "firm_id": FIRM, "client_id": cid, "status": "draft"})
    return _both_clients(rows)


@pytest.fixture
def hub_double(monkeypatch):
    d = _seed_every_tile()
    monkeypatch.setattr(hub_service, "_db", lambda: d)
    monkeypatch.setattr(hub_worklist_service, "_db", lambda: d)
    monkeypatch.setattr(hub_service, "effective_client_ids", lambda u: None)
    monkeypatch.setattr(hub_worklist_service, "effective_client_ids", lambda u: None)
    return d


def _tile(payload: dict, tile_id: str):
    return next(t for t in payload["tiles"] if t["id"] == tile_id)["signal"]


@pytest.mark.parametrize("tile_id", _FIVE)
def test_each_worklist_tile_of_the_firm_hub_equals_the_sum_of_its_worklist(hub_double, tile_id):
    from domain.banking import entry as bank_entry
    assert "needs_you" in bank_entry.OPEN_STATES
    payload = hub_service.hub({"firm_id": FIRM, "role": "Partner"})
    rows = hub_worklist_service.worklist({"firm_id": FIRM}, tile_id)["rows"]
    assert [r["client_id"] for r in rows] == [A], "the worklist leaves the practice out"
    assert _tile(payload, tile_id) == sum(r["signal"] for r in rows)


@pytest.mark.parametrize("tile_id", _FIVE)
def test_the_client_hub_of_the_practice_still_counts_the_practice(hub_double, tile_id):
    payload = hub_service.hub({"firm_id": FIRM, "role": "Partner"}, client_id=P)
    assert _tile(payload, tile_id) and _tile(payload, tile_id) > 0


def test_a_tile_whose_practice_read_fails_has_no_figure_rather_than_one_that_counts_the_practice(hub_double, monkeypatch):
    from services import hub_worklist_service as hws
    monkeypatch.setattr(hws, "_practice_ids", lambda db, firm_id: (_ for _ in ()).throw(RuntimeError("clients unreadable")))
    payload = hub_service.hub({"firm_id": FIRM, "role": "Partner"})
    assert all(_tile(payload, t) is None for t in _FIVE)
