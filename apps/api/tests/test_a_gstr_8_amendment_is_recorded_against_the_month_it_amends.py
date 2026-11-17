"""GSTR-8 Table 4 and Table 4.1: an amendment is recorded against the earlier month it amends and checked as the offline utility checks it
(POST-A-056, migration 617).

WHAT WAS MISSING
    Migration 421 recorded what an e-commerce operator's sellers supplied in ONE month (Table 3, Table 3.1) and named the other two tables of
    the return as not built: Table 4 and Table 4.1, which amend a row an EARLIER month declared. A correction had nowhere to go but a fresh
    row in the current month, which declares a second supply instead of correcting the first.

WHAT IS HELD
    * the shape is the utility's own, read from the committed VBA (the source pin below fails if the file stops saying what this module
      transcribes from it);
    * the original month must be EARLIER than the statement's, by the order a return period sorts in and not by the raw string;
    * Table 3's tax rules apply to a revised row against the ORIGINAL month: the exact-1% / band fork and the place-of-supply boundary are
      read off the amended row's own month, not the statement's;
    * an amendment is recorded and checked and never netted against the row it amends, and the statement says so; a statement with no
      amendment is exactly what it was;
    * the doors: the API refuses a month that is not earlier, a GSTIN that is not one, a negative amount and an action that is neither of the
      utility's two, a second call for the same amended row corrects it, and a row of a sibling client is not reachable under this one.

NEGATIVE CONTROL: against the code before this change none of the amendment names exists, so every case here fails.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.ecommerce_operator as eco_router
from core.auth import get_current_user
from domain.gst import gstr8
from domain.gst.registrations import TCS_COLLECTOR
from tests.e2e_harness import FakeDB, wire_e2e

API = Path(__file__).resolve().parents[1]
SOURCES = API.parent.parent / "docs" / "compliance" / "sources" / "gst-offline-utilities" / "gstr8"

FIRM = "11111111-1111-1111-1111-111111111111"
A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
OPERATOR = "27AAACA1234C1ZG"          # the three are valid GSTINs: the check digit is asked at the door
SELLER = "29AABCU9603R1ZJ"
OTHER_SELLER = "07AAACN2345C1ZZ"
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}


# ── the source the shape is read from ────────────────────────────────────────────────────────────────────────────────────

def test_the_shape_is_the_one_the_committed_utility_source_states():
    """The module transcribes the utility's Table 4 / 4.1 and must stay tied to the file it read, so a replaced source that no longer says
    these things fails here instead of leaving a doc claim standing on nothing."""
    export = (SOURCES / "ExportMod.bas.txt").read_text()
    validate = (SOURCES / "ValidateMod.bas.txt").read_text()
    for token in ('"tcsa"', '"urda"', '"ofp"', '"ostin"', '"opos"', '"oeid"', '"eid"', '"flag"', '"grsval"', '"supret"'):
        assert token in export, token
    assert 'jsonDictionary("flag") = "A"' in export and 'jsonDictionary("flag") = "D"' in export
    assert "Month and Year in Amend Sheet should be lesser than in Home Sheet" in validate
    assert "POS is not applicable for return periods prior to April 2025" in validate
    assert "Duplicate Combination of month , year and GSTIN found" in validate
    assert "Total tax value must be between 0.5% to 1% of net amount liable for TCS" in validate


# ── the rule ───────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("original,statement,earlier", [
    ("042026", "062026", True),        # two months back, one year
    ("122025", "012026", True),        # across the calendar year: '122025' sorts AFTER '012026' as a string
    ("062025", "012026", True),        # the raw strings say 062025 > 012026 and are wrong
    ("062026", "062026", False),       # its own month is not an earlier one
    ("072026", "062026", False),
    ("012026", "062025", False),       # a later year, which the raw strings call earlier
])
def test_the_original_month_must_be_earlier_by_return_period_order_not_by_string(original, statement, earlier):
    assert (gstr8.original_period_problem(original, statement) is None) is earlier


def test_the_refusal_names_both_months_in_words():
    sentence = gstr8.original_period_problem("072026", "062026")
    assert "07/2026" in sentence and "06/2026" in sentence and "earlier" in sentence and "paise" not in sentence


def _amend(**over):
    base = dict(original_period="042026", original_supplier_gstin=SELLER, original_place_of_supply="29",
                supplier_gstin=SELLER, place_of_supply="29",
                gross_registered_paise=1_00_000, returns_registered_paise=0,
                gross_unregistered_paise=0, returns_unregistered_paise=0,
                igst_paise=1_000, cgst_paise=0, sgst_paise=0, action="add")
    base.update(over)
    return gstr8.AmendmentRow(**base)


def _statement(amendments=(), unregistered=(), period="062026", **kw):
    return gstr8.compute_gstr8(period=period, supply_rows=[], unregistered_rows=[],
                               amendment_rows=list(amendments), unregistered_amendment_rows=list(unregistered), **kw)


def _problems(stmt):
    return [p for f in stmt.amendment_findings for p in f.problems]


def test_the_net_amount_is_derived_as_table_3_derives_it():
    row = _amend(gross_registered_paise=10_00_000, returns_registered_paise=2_00_000,
                 gross_unregistered_paise=5_00_000, returns_unregistered_paise=1_00_000)
    assert row.net_liable_paise == 12_00_000
    assert row.tax_collected_paise == 1_000
    assert gstr8.UnregisteredAmendmentRow("042026", "E1", "E1", 9_000, 4_000, "add").net_liable_paise == 5_000


def test_a_clean_amendment_has_no_finding_and_is_counted():
    stmt = _statement([_amend()])
    assert stmt.amendment_count == 1 and stmt.unregistered_amendment_count == 0
    assert stmt.amendment_findings == [], _problems(stmt)


def test_a_statement_with_no_amendment_is_exactly_what_it_was():
    stmt = _statement()
    assert (stmt.amendment_count, stmt.unregistered_amendment_count, stmt.amendment_findings, stmt.amendment_note) == (0, 0, [], None)
    assert stmt.total_net_liable_paise == stmt.total_igst_paise == 0


def test_an_amendment_is_never_added_to_table_3s_totals_and_the_statement_says_so():
    supplies = [gstr8.SupplyRow(supplier_gstin=SELLER, place_of_supply="29", gross_registered_paise=1_00_000,
                                returns_registered_paise=0, gross_unregistered_paise=0, returns_unregistered_paise=0,
                                igst_paise=1_000, cgst_paise=0, sgst_paise=0)]
    plain = gstr8.compute_gstr8(period="062026", supply_rows=supplies, unregistered_rows=[])
    with_amendments = gstr8.compute_gstr8(period="062026", supply_rows=supplies, unregistered_rows=[], amendment_rows=[_amend()],
                                          unregistered_amendment_rows=[gstr8.UnregisteredAmendmentRow("042026", "E1", "E1", 50_000, 0, "add")])
    for field in ("total_net_liable_paise", "total_igst_paise", "total_cgst_paise", "total_sgst_paise", "total_unregistered_net_paise"):
        assert getattr(with_amendments, field) == getattr(plain, field), field
    assert with_amendments.amendment_note == gstr8.AMENDMENT_NOT_NETTED_NOTE
    assert "NOT netted" in with_amendments.amendment_note and "portal" in with_amendments.amendment_note
    assert plain.amendment_note is None


@pytest.mark.parametrize("over,needle", [
    (dict(original_period="062026"), "not earlier"),                                  # its own month
    (dict(original_period="072026"), "not earlier"),                                  # a later month
    (dict(action="remove"), "neither Add nor Delete"),
    (dict(cgst_paise=500, sgst_paise=400, igst_paise=0), "does not equal SGST"),
    (dict(igst_paise=0), "no tax is recorded"),                                       # a positive net with no tax
    (dict(gross_registered_paise=0, igst_paise=100), "nil or negative"),              # tax on a nil net
    (dict(original_place_of_supply=None), "original place of supply is not recorded"),
    (dict(place_of_supply=None), "revised place of supply is not recorded"),
])
def test_each_rule_of_the_utilitys_table_4_is_a_finding_beside_the_row(over, needle):
    problems = _problems(_statement([_amend(**over)]))
    assert any(needle in p for p in problems), problems


def test_the_finding_names_the_original_supplier():
    stmt = _statement([_amend(igst_paise=0)])
    assert [f.supplier_gstin for f in stmt.amendment_findings] == [SELLER]


def test_the_rate_fork_is_read_off_the_ORIGINAL_month_not_the_statements():
    """Tax at 0.5% of a net of ₹1,00,000 is ₹500. The statement month is 2026, where a band 0.5%-1% accepts it; an original month before
    July 2024 needs EXACTLY 1%, so the same row is wrong there, and right for an original from July 2024. The utility keys on the amended
    row's own year and month."""
    half_percent = dict(gross_registered_paise=1_00_000, igst_paise=500, original_place_of_supply=None, place_of_supply=None)
    before = _problems(_statement([_amend(original_period="062024", **half_percent)], period="062026"))
    after = _problems(_statement([_amend(original_period="072024", **half_percent)], period="062026"))
    assert any("outside the expected range" in p for p in before), before
    assert not any("outside the expected range" in p for p in after), after
    exact = dict(gross_registered_paise=1_00_000, igst_paise=1_000, original_place_of_supply=None, place_of_supply=None)
    assert not any("outside" in p for p in _problems(_statement([_amend(original_period="062024", **exact)], period="062026")))


@pytest.mark.parametrize("original,pos,clean", [
    ("032025", None, True),          # FY 2024-25: the utility's schema has no place of supply
    ("032025", "29", False),         # ... and it refuses one
    ("042025", "29", True),          # FY 2025-26 onward: asked
    ("042025", None, False),
])
def test_the_place_of_supply_is_asked_from_fy_2025_26_by_the_original_month(original, pos, clean):
    row = _amend(original_period=original, original_place_of_supply=pos, place_of_supply=pos, igst_paise=1_000)
    problems = [p for p in _problems(_statement([row], period="062026")) if "place of supply" in p]
    assert (problems == []) is clean, problems


def test_table_4_1_checks_the_month_and_the_action_and_names_the_original_enrolment_id():
    ok = gstr8.UnregisteredAmendmentRow("042026", "123456789012ESA", "123456789012ESA", 9_000, 0, "delete")
    late = gstr8.UnregisteredAmendmentRow("062026", "123456789012ESB", "123456789012ESB", 9_000, 0, "add")
    odd = gstr8.UnregisteredAmendmentRow("042026", "123456789012ESC", "123456789012ESC", 9_000, 0, "later")
    stmt = _statement(unregistered=[ok, late, odd])
    assert stmt.unregistered_amendment_count == 3
    assert [f.supplier_gstin for f in stmt.amendment_findings] == ["123456789012ESB", "123456789012ESC"]
    assert "not earlier" in stmt.amendment_findings[0].problems[0] and "neither Add nor Delete" in stmt.amendment_findings[1].problems[0]


# ── the doors ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _body(**over):
    base = dict(client_id=A, gstin=OPERATOR, period="062026", original_period="042026", original_supplier_gstin=SELLER,
                original_place_of_supply="29", supplier_gstin=SELLER, place_of_supply="29", gross_registered_paise=1_00_000,
                igst_paise=1_000, action="add")
    base.update(over)
    return base


def _ubody(**over):
    base = dict(client_id=A, gstin=OPERATOR, period="062026", original_period="042026", original_enrolment_id="E-1",
                enrolment_id="E-1", gross_value_paise=9_000, returns_paise=1_000, action="add")
    base.update(over)
    return base


@pytest.fixture()
def world(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [eco_router])
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    import services.audit_service as audit
    logged: list[tuple] = []
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: logged.append((a, k)))
    import services.client_gst_registration_service as regs
    monkeypatch.setattr(regs, "resolve", lambda _db, _firm, _client, gstin=None: SimpleNamespace(
        gstin=gstin or OPERATOR, registration_type=TCS_COLLECTOR))
    db.logged = logged
    return db


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(eco_router.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def test_an_amendment_is_stored_under_the_firm_the_client_and_the_registration(world):
    res = _client().post("/api/ecommerce-operator/amendments", json=_body())
    assert res.status_code == 200 and res.json()["success"] is True, res.text
    (row,) = world.rows("ecommerce_operator_supply_amendments")
    assert (row["firm_id"], row["client_id"], row["gstin"], row["period"]) == (FIRM, A, OPERATOR, "062026")
    assert (row["original_period"], row["original_supplier_gstin"], row["action"], row["created_by"]) == ("042026", SELLER, "add", "u1")
    assert world.logged and world.logged[-1][0][1] == "ecommerce_operator_supply_amendment"


def test_a_second_call_for_the_same_amended_row_corrects_it_and_a_different_row_adds_one(world):
    client = _client()
    client.post("/api/ecommerce-operator/amendments", json=_body(gross_registered_paise=1_00_000))
    client.post("/api/ecommerce-operator/amendments", json=_body(gross_registered_paise=3_00_000, igst_paise=3_000, action="delete"))
    (row,) = world.rows("ecommerce_operator_supply_amendments")
    assert (row["gross_registered_paise"], row["action"]) == (3_00_000, "delete")
    client.post("/api/ecommerce-operator/amendments", json=_body(original_supplier_gstin=OTHER_SELLER))
    client.post("/api/ecommerce-operator/amendments", json=_body(original_period="052026"))
    assert len(world.rows("ecommerce_operator_supply_amendments")) == 3


def test_a_missing_original_place_of_supply_is_a_value_of_the_key_not_a_wildcard(world):
    """Before FY 2025-26 the field does not exist; two calls for the same original month and seller with none are one row, and a row with
    one is another (the utility's key, and migration 617's unique index, which reads NULL as '')."""
    client = _client()
    plain = _body(original_period="022025", period="062025", original_place_of_supply=None, place_of_supply=None)
    client.post("/api/ecommerce-operator/amendments", json=plain)
    client.post("/api/ecommerce-operator/amendments", json={**plain, "gross_registered_paise": 2_00_000, "igst_paise": 2_000})
    (row,) = world.rows("ecommerce_operator_supply_amendments")
    assert row["gross_registered_paise"] == 2_00_000 and row["original_place_of_supply"] is None
    client.post("/api/ecommerce-operator/amendments", json={**plain, "original_place_of_supply": "29", "place_of_supply": "29"})
    assert len(world.rows("ecommerce_operator_supply_amendments")) == 2


@pytest.mark.parametrize("over,needle", [
    (dict(original_period="062026"), "not earlier"),
    (dict(original_period="072026"), "not earlier"),
    (dict(original_supplier_gstin="29AABCU9603R1ZZ"), "check digit"),      # well-formed, wrong check digit
    (dict(supplier_gstin="not-a-gstin"), "GSTIN"),
    (dict(igst_paise=-1), "greater than or equal to 0"),
    (dict(action="remove"), "add"),
    (dict(place_of_supply="ZZ"), "state code"),
])
def test_the_door_refuses_what_the_utility_refuses_and_stores_nothing(world, over, needle):
    res = _client().post("/api/ecommerce-operator/amendments", json=_body(**over))
    assert res.status_code == 422 and needle in res.text, res.text
    assert world.rows("ecommerce_operator_supply_amendments") == []


def test_table_4_1_is_stored_corrected_and_refused_the_same_way(world):
    client = _client()
    assert client.post("/api/ecommerce-operator/unregistered-amendments", json=_ubody()).status_code == 200
    client.post("/api/ecommerce-operator/unregistered-amendments", json=_ubody(gross_value_paise=20_000, action="delete"))
    (row,) = world.rows("ecommerce_operator_unregistered_supply_amendments")
    assert (row["gross_value_paise"], row["action"], row["original_enrolment_id"]) == (20_000, "delete", "E-1")
    for over in (dict(original_period="062026"), dict(original_enrolment_id="  "), dict(enrolment_id=""), dict(returns_paise=-5),
                 dict(action="x")):
        assert client.post("/api/ecommerce-operator/unregistered-amendments", json=_ubody(**over)).status_code == 422, over
    assert len(world.rows("ecommerce_operator_unregistered_supply_amendments")) == 1


def test_the_list_returns_the_amendments_the_statements_month_declares_and_no_other_months(world):
    client = _client()
    client.post("/api/ecommerce-operator/amendments", json=_body(period="062026"))
    client.post("/api/ecommerce-operator/amendments", json=_body(period="072026"))
    client.post("/api/ecommerce-operator/unregistered-amendments", json=_ubody(period="062026"))
    data = client.get("/api/ecommerce-operator/supplies", params={"client_id": A, "period": "062026", "gstin": OPERATOR}).json()["data"]
    assert [r["period"] for r in data["amendments"]] == ["062026"] and len(data["unregistered_amendments"]) == 1
    # the screen sums nothing: each listed row carries the net the domain derives (gross less returns, both recipient kinds)
    assert [r["net_liable_paise"] for r in data["amendments"]] == [1_00_000]
    assert [r["net_liable_paise"] for r in data["unregistered_amendments"]] == [8_000]
    assert data["registered"] == [] and data["unregistered"] == []


def test_an_amendment_of_a_sibling_client_is_not_reached_under_this_one(world):
    world.seed("ecommerce_operator_supply_amendments", {"id": "row-b", "firm_id": FIRM, "client_id": B, "gstin": OPERATOR, "period": "062026",
                                                        "deleted_at": None})
    res = _client().delete("/api/ecommerce-operator/amendments/row-b", params={"client_id": A})
    assert res.status_code == 404 and res.json()["detail"] == "Entry not found."
    assert world.rows("ecommerce_operator_supply_amendments")[0]["deleted_at"] is None
    assert _client().delete("/api/ecommerce-operator/amendments/row-b", params={"client_id": B}).status_code == 200
    assert world.rows("ecommerce_operator_supply_amendments")[0]["deleted_at"] is not None


def test_in_mock_mode_the_refusals_still_apply_and_nothing_is_stored(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    app = FastAPI()
    app.include_router(eco_router.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    monkeypatch.setattr(eco_router, "assert_client_access", lambda *_a, **_k: None)
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post("/api/ecommerce-operator/amendments", json=_body(original_period="062026")).status_code == 422
    assert client.post("/api/ecommerce-operator/amendments", json=_body()).json()["data"]["id"] == "mock-amendment"


# ── the statement ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_statement_carries_the_amendments_their_findings_and_the_note(world):
    from services import gst_return_service as grs
    client = _client()
    client.post("/api/ecommerce-operator/amendments", json=_body())
    client.post("/api/ecommerce-operator/amendments", json=_body(original_supplier_gstin=OTHER_SELLER, igst_paise=0))
    client.post("/api/ecommerce-operator/unregistered-amendments", json=_ubody())
    out = grs.gstr8_statement(world, FIRM, A, "062026", OPERATOR)
    assert (out["amendment_count"], out["unregistered_amendment_count"]) == (2, 1)
    assert out["amendment_note"] == gstr8.AMENDMENT_NOT_NETTED_NOTE
    by_row = {f["supplier_gstin"]: f["problems"] for f in out["amendment_findings"]}
    assert any("no tax is recorded" in p for p in by_row[OTHER_SELLER])
    # The fixtures' seller is of State 29 and its Enrolment ID is "E-1", which the utility's own row checks refuse beside the row
    # (POST-A-458): a supplier of another State than the operator's 27, and an Enrolment ID not of its shape.
    assert sorted(by_row) == sorted([SELLER, OTHER_SELLER, "E-1"])
    assert all("of another State" in " ".join(by_row[g]) for g in (SELLER, OTHER_SELLER))
    assert all("Enrolment ID (E-1) is not in the form" in " ".join(by_row["E-1"]) for _ in (0,))
    assert len(out["amendments"]) == 2 and len(out["unregistered_amendments"]) == 1
    assert out["total_net_liable_paise"] == 0 and out["supplier_count"] == 0, "an amendment is not a Table 3 row"


def test_a_statement_with_no_amendment_says_nothing_about_them(world):
    from services import gst_return_service as grs
    out = grs.gstr8_statement(world, FIRM, A, "062026", OPERATOR)
    assert (out["amendment_count"], out["unregistered_amendment_count"], out["amendment_findings"], out["amendment_note"]) == (0, 0, [], None)
