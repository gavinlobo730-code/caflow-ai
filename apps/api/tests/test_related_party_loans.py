"""
Related-party loans (Companies Act s.185 / s.186) write to their own table.

WHAT WAS WRONG
    routers/relationships.py wrote its loans to `loans` and could not: it names
    entity_id, interest_rate, sanction_date, due_date, section_185_flagged,
    section_186_flagged and updated_at, none of which that table has, plus
    loan_type values ('to_director', 'inter_company') its CHECK rejects. Four of
    the five loans queries in that router were broken, including
    POST /relationships/loans, the s.185 report and the client-level rollup.
    The feature had never worked against a real database.

WHY A SEPARATE TABLE (migration 273)
    Two unrelated things had collided on one name, and both are live.
    `loans` is a client's BORROWINGS register — lender_name, account_number,
    emi_paise, outstanding_paise — which the browser reads and writes directly
    from /accounting/loans, /risks and /reports/cash-flow. A related-party loan
    has no lender, no EMI and no account number; a bank borrowing has no
    director. Bolting seven columns onto `loans` would have left every row
    carrying permanently-null halves of the other concept.

WHAT IS ASSERTED
    That the router writes and reads related_party_loans and never `loans`;
    that the s.185/s.186 flags are derived from loan_type; and that the input
    model rejects bad values with a 422 naming the field rather than letting
    the table's CHECK come back as a 500.

The double refuses any column outside the real schema and any value outside a
CHECK — including on `loans`, which is listed too, so a regression that pointed
this feature back at the borrowings table fails here rather than in production.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _schema_checked_db import (  # noqa: E402
    CheckViolation, PhantomColumn, SchemaCheckedDB,
)

import routers.relationships as rel  # noqa: E402
from core.auth import get_current_user  # noqa: E402

FIRM = "firm-1"
CLIENT = "client-1"
ENTITY = "entity-1"
USER = {"id": "u1", "auth_user_id": "auth-u1", "firm_id": FIRM,
        "role": "Partner", "email": "p@f.in"}


def _loan(loan_type: str = "to_director", **kw) -> dict:
    body = {
        "client_id": CLIENT, "entity_id": ENTITY, "loan_type": loan_type,
        "principal_paise": 5_00_00_000_00, "interest_rate": 9.5,
        "sanction_date": "2026-04-01", "due_date": "2027-03-31",
        "notes": "Board resolution 12/2026",
    }
    body.update(kw)
    return body


@pytest.fixture()
def client(monkeypatch):
    """TestClient whose relationships router talks to a SchemaCheckedDB.

    monkeypatch rather than a bare attribute assignment — an unscoped one
    survives the test and leaks into every later module that imports this
    router (learned the hard way in #273)."""
    def _build(db: SchemaCheckedDB) -> TestClient:
        monkeypatch.setattr(rel, "_db", lambda: db)
        app = FastAPI()
        app.include_router(rel.router)
        app.dependency_overrides[get_current_user] = lambda: USER
        return TestClient(app, raise_server_exceptions=False)
    return _build


def _seeded() -> SchemaCheckedDB:
    return SchemaCheckedDB({
        "entities": [{"id": ENTITY, "firm_id": FIRM, "full_name": "A Director"}],
        "related_party_loans": [],
    })


# ── The write goes to the right table, with the right columns ────────────────

def test_creating_a_loan_writes_related_party_loans(client):
    db = _seeded()
    res = client(db).post("/api/relationships/loans", json=_loan())

    assert res.status_code == 200, "the insert named columns `loans` does not have"
    assert db.rows["related_party_loans"], "nothing was written to related_party_loans"
    assert not db.rows.get("loans"), "a related-party loan must never land in the borrowings register"

    row = db.rows["related_party_loans"][0]
    assert row["entity_id"] == ENTITY
    assert row["client_id"] == CLIENT
    assert row["principal_paise"] == 5_00_00_000_00
    assert row["created_by"] == "u1", "created_by FKs to users.id, not the auth id"


def test_a_director_loan_is_flagged_under_section_185(client):
    db = _seeded()
    client(db).post("/api/relationships/loans", json=_loan("to_director"))
    row = db.rows["related_party_loans"][0]
    assert row["section_185_flagged"] is True
    assert row["section_186_flagged"] is False


def test_an_inter_company_loan_is_flagged_under_section_186(client):
    db = _seeded()
    client(db).post("/api/relationships/loans", json=_loan("inter_company"))
    row = db.rows["related_party_loans"][0]
    assert row["section_186_flagged"] is True
    assert row["section_185_flagged"] is False


def test_an_ordinary_loan_is_flagged_under_neither(client):
    db = _seeded()
    client(db).post("/api/relationships/loans", json=_loan("other"))
    row = db.rows["related_party_loans"][0]
    assert row["section_185_flagged"] is False
    assert row["section_186_flagged"] is False


# ── The reads too ────────────────────────────────────────────────────────────

def test_the_section_185_report_reads_related_party_loans(client):
    db = _seeded()
    db.rows["related_party_loans"] = [
        {"id": "l1", "firm_id": FIRM, "client_id": CLIENT, "entity_id": ENTITY,
         "loan_type": "to_director", "principal_paise": 1_00_00_000_00,
         "section_185_flagged": True, "section_186_flagged": False,
         "created_at": "2026-04-01"},
        {"id": "l2", "firm_id": FIRM, "client_id": CLIENT, "entity_id": ENTITY,
         "loan_type": "other", "principal_paise": 50_00_000_00,
         "section_185_flagged": False, "section_186_flagged": False,
         "created_at": "2026-04-02"},
    ]
    res = client(db).get("/api/relationships/loans/section-185-report")

    assert res.status_code == 200, "the report queried a column `loans` does not have"
    data = res.json()["data"]
    assert data["count"] == 1
    assert data["flagged_loans"][0]["id"] == "l1"
    assert data["total_principal_paise"] == 1_00_00_000_00  # integer paise


def test_listing_loans_reads_related_party_loans(client):
    db = _seeded()
    db.rows["related_party_loans"] = [
        {"id": "l1", "firm_id": FIRM, "client_id": CLIENT, "entity_id": ENTITY,
         "loan_type": "to_director", "principal_paise": 100, "created_at": "2026-04-01",
         "section_185_flagged": True, "section_186_flagged": False},
    ]
    res = client(db).get("/api/relationships/loans")
    assert res.status_code == 200
    assert [r["id"] for r in res.json()["data"]] == ["l1"]


# ── Bad input is a 422 naming the field, not a 500 from the CHECK ────────────

def test_an_unknown_loan_type_is_rejected_before_the_database(client):
    db = _seeded()
    res = client(db).post("/api/relationships/loans", json=_loan("to_the_dog"))
    assert res.status_code == 422, (
        "an unknown loan_type must be named as a field error, not reach Postgres "
        "and come back as an opaque 500 from the table's CHECK"
    )
    assert not db.rows["related_party_loans"]


def test_a_zero_principal_is_rejected_before_the_database(client):
    db = _seeded()
    res = client(db).post("/api/relationships/loans", json=_loan(principal_paise=0))
    assert res.status_code == 422
    assert not db.rows["related_party_loans"]


def test_a_negative_principal_is_rejected(client):
    db = _seeded()
    res = client(db).post("/api/relationships/loans", json=_loan(principal_paise=-1))
    assert res.status_code == 422


# ── The two tables must not be confused again ────────────────────────────────

def test_the_borrowings_register_rejects_a_related_party_shape():
    """Pins the original defect. `loans` has no entity_id and no section flags;
    writing this feature's row there is what produced the 42703."""
    db = SchemaCheckedDB({"loans": []})
    with pytest.raises(PhantomColumn):
        db.table("loans").insert({
            "firm_id": FIRM, "client_id": CLIENT, "entity_id": ENTITY,
            "loan_type": "other", "principal_paise": 100,
        }).execute()


def test_the_borrowings_register_rejects_to_director_as_a_loan_type():
    """The other half of the original defect: even the loan_type was invalid
    there. `loans` is for bank products."""
    db = SchemaCheckedDB({"loans": []})
    with pytest.raises(CheckViolation):
        db.table("loans").insert({
            "firm_id": FIRM, "client_id": CLIENT, "loan_type": "to_director",
            "principal_paise": 100,
        }).execute()


def test_the_router_no_longer_names_the_borrowings_table():
    src = Path(rel.__file__).read_text(encoding="utf-8")
    assert 'db.table("loans")' not in src, (
        "related-party loans belong in related_party_loans; `loans` is the "
        "client's own borrowings register"
    )
    assert rel.LOANS_TABLE == "related_party_loans"
