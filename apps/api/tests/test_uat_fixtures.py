"""
Phase 5.2 WS-2 — verify the repeatable demo fixtures build correctly and are
usable by the real code paths (so the UAT data package is trustworthy).
"""
from tests.e2e_harness import FakeDB, wire_e2e
from tests.uat_fixtures import build_demo_dataset, demo_callers


def test_demo_dataset_builds_with_expected_shape():
    db = FakeDB()
    ids = build_demo_dataset(db)
    assert ids["users"]["partner"] == "u-priya"
    assert len(db.rows("firms")) == 2                       # two firms
    assert len(db.rows("users")) == 5                       # 4 Firm-A staff + Firm-B partner
    assert {c["id"] for c in db.rows("clients")} == {"C1", "C2", "C9"}
    # COA seeded for both Firm-A clients (14 accounts each — incl. the 2 FX
    # gain/loss accounts added in Multi-Currency Phase 4).
    assert len([a for a in db.rows("chart_of_accounts") if a["client_id"] == "C1"]) == 14
    # Assignment scope: Reviewer → C2 only.
    assert {"user_id": "u-reena", "client_id": "C2"} in [
        {"user_id": a["user_id"], "client_id": a["client_id"]} for a in db.rows("user_client_assignments")]


def test_demo_dataset_is_deterministic():
    a, b = build_demo_dataset(FakeDB()), build_demo_dataset(FakeDB())
    assert a == b                                           # same ids every run


def test_demo_dataset_is_usable_and_isolated(monkeypatch):
    import routers.customers as cu
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu])
    build_demo_dataset(db)
    callers = demo_callers()

    # Firm-A partner can read a Firm-A customer…
    resp = cu.get_customer("CU-NW", callers["partner"])
    assert resp["success"] and resp["data"]["name"] == "Northwind"
    # …but cannot read Firm-B's customer (cross-firm 404).
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        cu.get_customer("CU-Z", callers["partner"])
    assert ei.value.status_code == 404
