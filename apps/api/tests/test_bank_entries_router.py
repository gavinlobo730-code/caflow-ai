"""
The entries endpoints and the trusted-rule gate, through the HTTP layer.

WHAT IS ASSERTED
    1. GET /entries, /entries/counts, POST /entries/redraft, /entries/pass-ready
       and POST /transactions/{id}/pass answer in the api_response envelope
       and drive the service the screen will drive.
    2. Promoting a rule to TRUSTED needs banking.approve: an Executive gets
       403, a Manager gets it and is recorded as trusted_by; a rule with no
       ledger cannot be trusted (422); demoting clears the record.
    3. Creating or editing a rule marks the client's open lines for
       re-proposal; toggling trust alone does not.
    4. A single-line pass that is refused is a 422 with the reason, not a 200
       carrying "failed".

Header auth (dev mode) so the caller's ROLE can vary per request; the
database is the triggered fake from test_bank_entry_service, injected in
place of routers.banking._db.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app
import routers.banking as rb
import services.bank_entry_service as bes
from tests.test_bank_entry_service import _db, _rule, _line, _row, _Poster, CHARGES, RENT
from tests.test_bank_matching import FIRM, CLIENT

pytestmark = pytest.mark.usefixtures("dev_header_auth")
client = TestClient(app)


def _h(role: str) -> dict:
    return {"X-User-Role": role, "X-Firm-Id": FIRM, "X-User-Id": f"{role}-1"}


@pytest.fixture
def db(monkeypatch):
    fake = _db()
    monkeypatch.setattr(rb, "_db", lambda: fake)
    return fake


@pytest.fixture
def poster(monkeypatch):
    p = _Poster()
    monkeypatch.setattr(bes.bank_posting_service, "post", p)
    return p


# ── 1. the entries endpoints ─────────────────────────────────────────────────

def test_the_screen_flow_redraft_counts_list_pass_ready(db, poster):
    _rule(db); _line(db, "t1", "NEFT CHARGES"); _line(db, "t2", "NOBODY KNOWS")
    r = client.post("/api/banking/entries/redraft", headers=_h("executive"),
                    json={"client_id": CLIENT})
    assert r.status_code == 200 and r.json()["success"]
    assert r.json()["data"]["drafted"] == 2 and r.json()["data"]["remaining"] == 0

    c = client.get("/api/banking/entries/counts", headers=_h("executive"),
                   params={"client_id": CLIENT}).json()["data"]
    assert c["ready"] == 1 and c["needs_you"] == 1 and c["to_do"] == 2 and c["undrafted"] == 0

    lst = client.get("/api/banking/entries", headers=_h("executive"),
                     params={"client_id": CLIENT, "state": "ready"}).json()["data"]
    assert lst["total"] == 1 and lst["rows"][0]["id"] == "t1"
    assert lst["rows"][0]["kind"] == "payment" and lst["rows"][0]["draft_label"] == "Bank Charges"

    p = client.post("/api/banking/entries/pass-ready", headers=_h("executive"),
                    json={"client_id": CLIENT}).json()["data"]
    assert p["passed"] == 1 and p["remaining"] == 0
    assert poster.calls[0]["txn_id"] == "t1" and poster.calls[0]["actor_id"] == "executive-1"


def test_an_invalid_state_is_a_422(db):
    r = client.get("/api/banking/entries", headers=_h("executive"),
                   params={"client_id": CLIENT, "state": "everything"})
    assert r.status_code == 422


def test_a_refused_single_pass_is_a_422_with_the_reason(db, monkeypatch):
    monkeypatch.setattr(bes.bank_posting_service, "post",
                        _Poster(refuse={"t1": "Financial year 2026-27 is locked."}))
    _rule(db); _line(db, "t1", "NEFT CHARGES")
    client.post("/api/banking/entries/redraft", headers=_h("executive"), json={"client_id": CLIENT})
    r = client.post("/api/banking/transactions/t1/pass", headers=_h("executive"))
    assert r.status_code == 422 and "locked" in r.json()["detail"]
    assert _row(db, "t1")["draft_error"].startswith("Financial year")


def test_a_single_pass_carries_the_gst_the_ca_chose(db, poster):
    _line(db, "t1", "NEFT CHARGES", account_id=CHARGES, category="Expense")
    r = client.post("/api/banking/transactions/t1/pass", headers=_h("executive"),
                    json={"gst_rate_bps": 1800, "is_interstate": False})
    assert r.status_code == 200, r.text
    assert poster.calls[0]["gst_rate_bps"] == 1800
    r = client.post("/api/banking/transactions/t1/pass", headers=_h("executive"),
                    json={"gst_rate_bps": 1234})
    assert r.status_code == 422


def test_get_entry_carries_what_only_the_detail_needs(db):
    _line(db, "t1", "UPI/DR/1/RAMESH KUMAR/HDFC", payee_name="RAMESH KUMAR")
    r = client.get("/api/banking/entries/t1", headers=_h("executive")).json()["data"]
    assert r["id"] == "t1" and "suggestions" in r and "history" in r and "transfer_candidate" in r


# ── 2-3. trusted rules ───────────────────────────────────────────────────────

def test_an_executive_cannot_trust_a_rule_but_a_manager_can(db):
    rule = _rule(db)
    r = client.patch("/api/banking/rules/r1", headers=_h("executive"), json={"is_trusted": True})
    assert r.status_code == 403
    assert rule["is_trusted"] is False and rule["trusted_by"] is None

    r = client.patch("/api/banking/rules/r1", headers=_h("manager"), json={"is_trusted": True})
    assert r.status_code == 200, r.text
    assert rule["is_trusted"] is True and rule["trusted_by"] == "manager-1" and rule["trusted_at"]

    r = client.patch("/api/banking/rules/r1", headers=_h("executive"), json={"is_trusted": False})
    assert r.status_code == 200
    assert rule["is_trusted"] is False and rule["trusted_by"] is None and rule["trusted_at"] is None


def test_a_rule_without_a_ledger_cannot_be_trusted(db):
    _rule(db, account=None, category="Expense")
    r = client.patch("/api/banking/rules/r1", headers=_h("partner"), json={"is_trusted": True})
    assert r.status_code == 422 and "ledger" in r.json()["detail"]


def test_creating_or_editing_a_rule_marks_open_lines_stale_but_trusting_does_not(db):
    _line(db, "t1", "NEFT CHARGES", drafted_at="2026-04-15T00:00:00Z")
    r = client.post("/api/banking/rules", headers=_h("executive"),
                    json={"client_id": CLIENT, "rule_name": "Charges",
                          "description_pattern": "CHARGES", "suggested_account_id": CHARGES})
    assert r.status_code == 200, r.text
    assert _row(db, "t1")["drafted_at"] is None

    _row(db, "t1")["drafted_at"] = "2026-04-15T00:00:00Z"
    rid = db.store["bank_matching_rules"][0]["id"]
    r = client.patch(f"/api/banking/rules/{rid}", headers=_h("manager"), json={"is_trusted": True})
    assert r.status_code == 200, r.text
    assert _row(db, "t1")["drafted_at"] == "2026-04-15T00:00:00Z"

    r = client.patch(f"/api/banking/rules/{rid}", headers=_h("executive"),
                     json={"suggested_account_id": RENT})
    assert r.status_code == 200, r.text
    assert _row(db, "t1")["drafted_at"] is None
