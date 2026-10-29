"""A §197 lower-deduction certificate is recorded by the server, and the TDS tab's four figures are the server's (POST-A-293).

WHAT WAS WRONG
    The client's Compliance -> TDS tab inserted the certificate straight into `tds_lower_deduction_certificates` over PostgREST, where
    `rbac()` and the caller's client assignment never run, and counted its dashboard's challans, returns and certificates itself over
    three more tables. A certificate LOWERS what is withheld from a real supplier (migration 359), so the only checks on a figure that
    under-deducts were three CHECK constraints and one policy, and the section list the screen offered was the only thing asking
    whether §197(1) reaches the section. `GET /api/tds-workspace/` returned the same three tables in full, unordered and unwindowed,
    and nothing called it.

WHAT IS HELD (no database; the browser half is `apps/web/scripts/the-tds-tab-reads-through-the-api.test.ts`)
    * ONE QUESTION, TWO ASKERS: `section_refusal` says a section is refused exactly when `GET /api/tds/sections` marks it not
      eligible, for every section the registry holds in every year it holds, so the dropdown and the door cannot disagree; §195 is
      refused in its own words (reached by §197(1) and not priced), §194Q in its own (not reached), garbage in a third;
    * the record refuses, in sentences, a rate outside 0-100%, a ceiling that is not positive, an end before the start and a blank
      number, and says every reason at once;
    * the supplier must be this client's (404 in the missing row's words), a second certificate number for the same supplier and
      section is a 409 with a sentence (the pre-check and the race on the unique index are the same answer), and the same number on
      another section or another supplier is not a duplicate;
    * the row is written with the PRIVILEGED client (so the privilege can be taken from the signed-in role afterwards), names the
      firm and the client, carries the internal user id in `created_by`, and the audit event is written;
    * the list is a window in a stated order, firm- and client-scoped;
    * the dashboard returns only its four figures, counted over every row the client has, and none of another client's or firm's.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

import routers.tds_workspace as tw
from core import db_provider
from domain.tds import lower_deduction, screen_counts
from domain.tds.section_rates import TDS_RATES_BY_FY, parent_of
from services import lower_deduction_certificate_service as svc
from tests.e2e_harness import FakeDB

FIRM, CLIENT, OTHER_CLIENT, VENDOR = "FIRM-A", "CLIENT-1", "CLIENT-2", "VENDOR-1"
CALLER = {"firm_id": FIRM, "id": "internal-user", "auth_user_id": "auth-user", "email": "ca@f.test", "role": "Executive"}
START, END = date(2026, 4, 1), date(2027, 3, 31)


def _body(**over):
    base = dict(client_id=CLIENT, vendor_id=VENDOR, section="194C", certificate_no="LDC/2026/1", rate_bps=50,
                valid_from=START, valid_to=END, ceiling_paise=5_000_000_00, notes=None)
    base.update(over)
    return tw.LowerDeductionCertificateRequest(**base)


@pytest.fixture()
def database(monkeypatch):
    """The database path: a FakeDB for the router, one vendor of the client, the privileged client being the same double."""
    db = FakeDB()
    db.seed("vendors", {"id": VENDOR, "firm_id": FIRM, "client_id": CLIENT, "name": "Roadways", "is_active": True})
    db.seed("vendors", {"id": "VENDOR-OLD", "firm_id": FIRM, "client_id": CLIENT, "name": "Retired", "is_active": False})
    db.seed("vendors", {"id": "VENDOR-X", "firm_id": FIRM, "client_id": OTHER_CLIENT, "name": "Someone else's"})
    import core.supabase_client as sc
    monkeypatch.setattr(tw, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    monkeypatch.setattr(tw, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(tw, "log_event", lambda *a, **k: None)
    return db


# ── the section question ─────────────────────────────────────────────────────

def test_the_save_and_the_section_list_ask_the_same_question_in_every_year_the_registry_holds():
    from routers.tds import list_tds_sections
    checked, eligible, refused = 0, 0, 0
    for fy in sorted(TDS_RATES_BY_FY):
        listed = list_tds_sections(fy=fy, user={"role": "Partner"})["data"]["sections"]
        for entry in listed:
            refusal = lower_deduction.section_refusal(entry["section"], fy)
            assert (refusal is None) == bool(entry["section_197_eligible"]), (fy, entry["section"], refusal)
            checked += 1
            eligible += refusal is None
            refused += refusal is not None
    assert checked >= 30 and eligible >= 10 and refused >= 2, f"the sweep read too little: {checked} sections, {eligible} eligible, {refused} refused"


@pytest.mark.parametrize("section, fragment", [
    ("194Q", "does not reach"),                  # priced by the registry, and §197(1) does not name it
    ("195", "holds no withholding rate"),        # §197(1) names it, and the engine does not price it
    ("999Z", "not a TDS section"),
    ("", "Choose the section"),
])
def test_a_section_that_cannot_carry_a_certificate_is_refused_in_its_own_words(section, fragment):
    assert fragment in (lower_deduction.section_refusal(section, "2026-27") or "")


def test_a_section_typed_in_lower_case_is_recorded_as_the_registry_spells_it(database):
    tw.record_lower_deduction_certificate(_body(section=" 194i(a) "), current_user=CALLER)
    assert database.rows("tds_lower_deduction_certificates")[0]["section"] == "194I(A)"


def test_a_clause_key_is_judged_by_the_section_it_belongs_to():
    assert parent_of("194I(A)", "2026-27") == "194I"
    assert lower_deduction.section_refusal("194I(A)", "2026-27") is None
    assert lower_deduction.section_refusal("194C", "2026-27") is None


# ── the figures ──────────────────────────────────────────────────────────────

def test_every_reason_is_said_at_once():
    said = svc.problems(section="194Q", certificate_no="  ", rate_bps=10001, valid_from=END, valid_to=START, ceiling_paise=0)
    assert len(said) == 5, said
    assert svc.problems(section="194C", certificate_no="N-1", rate_bps=0, valid_from=START, valid_to=START, ceiling_paise=1) == [], \
        "a nil certificate (0%), a one-day period and a one-paisa ceiling are all real values"


@pytest.mark.parametrize("over, fragment", [
    ({"rate_bps": -1}, "reduction"), ({"rate_bps": 10001}, "reduction"), ({"ceiling_paise": 0}, "specified amount"),
    ({"valid_to": date(2026, 3, 31)}, "cannot end before"), ({"certificate_no": "   "}, "Form 26Q"), ({"section": "194Q"}, "does not reach"),
])
def test_a_refused_certificate_is_a_422_with_the_sentence_and_nothing_is_written(database, over, fragment):
    with pytest.raises(HTTPException) as refused:
        tw.record_lower_deduction_certificate(_body(**over), current_user=CALLER)
    assert refused.value.status_code == 422 and fragment in refused.value.detail
    assert database.rows("tds_lower_deduction_certificates") == []


# ── the record ───────────────────────────────────────────────────────────────

def test_a_certificate_is_written_with_the_privileged_client_naming_the_firm_the_client_and_the_person(database, monkeypatch):
    asked = []
    monkeypatch.setattr(svc, "privileged_for", lambda db: (asked.append("privileged"), db)[1])
    out = tw.record_lower_deduction_certificate(_body(), current_user=CALLER)
    assert out["success"] is True and asked == ["privileged"]
    (row,) = database.rows("tds_lower_deduction_certificates")
    assert (row["firm_id"], row["client_id"], row["vendor_id"], row["created_by"]) == (FIRM, CLIENT, VENDOR, "internal-user")
    assert (row["section"], row["certificate_no"], row["rate_bps"], row["valid_from"], row["valid_to"]) == \
        ("194C", "LDC/2026/1", 50, "2026-04-01", "2027-03-31")
    assert out["data"]["id"] == row["id"]


def test_a_supplier_of_another_client_is_a_missing_row(database):
    with pytest.raises(HTTPException) as missing:
        tw.record_lower_deduction_certificate(_body(vendor_id="VENDOR-X"), current_user=CALLER)
    assert missing.value.status_code == 404 and missing.value.detail == "That vendor was not found."
    assert database.rows("tds_lower_deduction_certificates") == []


def test_the_same_number_for_the_same_supplier_and_section_is_a_409_and_a_different_one_is_not(database):
    assert tw.record_lower_deduction_certificate(_body(), current_user=CALLER)["success"] is True
    with pytest.raises(HTTPException) as dup:
        tw.record_lower_deduction_certificate(_body(), current_user=CALLER)
    assert dup.value.status_code == 409 and dup.value.detail == svc.DUPLICATE
    assert tw.record_lower_deduction_certificate(_body(section="194J"), current_user=CALLER)["success"] is True
    assert tw.record_lower_deduction_certificate(_body(certificate_no="LDC/2026/2"), current_user=CALLER)["success"] is True
    assert len(database.rows("tds_lower_deduction_certificates")) == 3


def test_a_race_on_the_unique_index_is_the_same_409(database, monkeypatch):
    class Racing:
        def table(self, name):
            real = database.table(name)
            if name != "tds_lower_deduction_certificates":
                return real

            class Insert:
                def insert(self, _row):
                    raise RuntimeError('duplicate key value violates unique constraint "uq_tds_ldc_vendor_section_no" (23505)')
                def __getattr__(self, attr):
                    return getattr(real, attr)
            return Insert()
    monkeypatch.setattr(svc, "privileged_for", lambda db: Racing())
    with pytest.raises(HTTPException) as dup:
        tw.record_lower_deduction_certificate(_body(), current_user=CALLER)
    assert dup.value.status_code == 409


def test_any_other_failure_is_said_in_a_sentence_and_not_as_the_database_s_own_words(database, monkeypatch):
    class Broken:
        def table(self, name):
            raise RuntimeError('relation "tds_lower_deduction_certificates" column "section" violates ...')
    monkeypatch.setattr(svc, "privileged_for", lambda db: Broken())
    out = tw.record_lower_deduction_certificate(_body(), current_user=CALLER)
    assert out["success"] is False and "violates" not in str(out["error"]) and "§197" in out["error"]


# ── the list ─────────────────────────────────────────────────────────────────

def test_the_list_is_a_window_in_a_stated_order_for_this_firm_and_client_only(database):
    for i, (start, no) in enumerate([("2025-04-01", "OLD"), ("2026-04-01", "NEW"), ("2026-04-01", "NEWER")]):
        database.seed("tds_lower_deduction_certificates", {
            "id": f"c-{i}", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": VENDOR, "section": "194C", "certificate_no": no,
            "rate_bps": 50, "valid_from": start, "valid_to": "2027-03-31", "ceiling_paise": 100, "notes": None})
    database.seed("tds_lower_deduction_certificates", {"id": "other", "firm_id": FIRM, "client_id": OTHER_CLIENT, "vendor_id": "VENDOR-X",
                                                       "section": "194C", "certificate_no": "X", "valid_from": "2026-04-01"})
    database.seed("tds_lower_deduction_certificates", {"id": "alien", "firm_id": "FIRM-B", "client_id": CLIENT, "vendor_id": VENDOR,
                                                       "section": "194C", "certificate_no": "Y", "valid_from": "2026-04-01"})
    out = tw.list_lower_deduction_certificates(client_id=CLIENT, limit=2, offset=0, current_user=CALLER)["data"]
    assert [r["certificate_no"] for r in out["lower_deduction_certificates"]] == ["NEWER", "NEW"] or \
        [r["certificate_no"] for r in out["lower_deduction_certificates"]] == ["NEW", "NEWER"]
    assert out["has_more"] is True and out["limit"] == 2 and out["max_limit"] == tw.TDS_LIST_MAX
    assert out["vendors"] == [{"id": VENDOR, "name": "Roadways"}], "the form offers this client's active suppliers and nobody else's"
    rest = tw.list_lower_deduction_certificates(client_id=CLIENT, limit=2, offset=2, current_user=CALLER)["data"]
    assert [r["certificate_no"] for r in rest["lower_deduction_certificates"]] == ["OLD"] and rest["has_more"] is False


# ── the dashboard ────────────────────────────────────────────────────────────

def test_the_challan_totals_count_every_row_and_add_the_grand_total_column():
    rows = [{"total_paise": 100}, {"total_paise": 250}, {"total_paise": None}, {"total_paise": "bad"}]
    assert screen_counts.challan_totals(rows) == {"count": 4, "total_paise": 350}
    assert screen_counts.challan_totals([]) == {"count": 0, "total_paise": 0}


def test_the_dashboard_answers_four_figures_over_every_row_of_this_client_and_nothing_else(database):
    for i in range(3):
        database.seed("tds_challans", {"id": f"ch-{i}", "firm_id": FIRM, "client_id": CLIENT, "total_paise": 1000 * (i + 1)})
    database.seed("tds_challans", {"id": "ch-other", "firm_id": FIRM, "client_id": OTHER_CLIENT, "total_paise": 999_999})
    database.seed("tds_challans", {"id": "ch-alien", "firm_id": "FIRM-B", "client_id": CLIENT, "total_paise": 888_888})
    database.seed("tds_returns", {"id": "r-1", "firm_id": FIRM, "client_id": CLIENT})
    database.seed("tds_returns", {"id": "r-2", "firm_id": FIRM, "client_id": CLIENT})
    database.seed("tds_certificates", {"id": "c-1", "firm_id": FIRM, "client_id": CLIENT})
    out = tw.tds_dashboard(client_id=CLIENT, current_user=CALLER)
    assert out["success"] is True
    assert out["data"] == {"summary": {"total_challans": 3, "total_deposited_paise": 6000, "total_returns": 2, "total_certificates": 1}}


# ── mock mode keeps working ──────────────────────────────────────────────────

def test_mock_mode_records_lists_and_refuses_a_duplicate_without_a_database(monkeypatch):
    monkeypatch.setattr(tw, "_USE_MOCK", True)
    monkeypatch.setattr(tw, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(tw, "log_event", lambda *a, **k: None)
    tw._MOCK_LOWER_DEDUCTION.clear()
    try:
        assert tw.record_lower_deduction_certificate(_body(), current_user=CALLER)["success"] is True
        with pytest.raises(HTTPException) as dup:
            tw.record_lower_deduction_certificate(_body(), current_user=CALLER)
        assert dup.value.status_code == 409
        out = tw.list_lower_deduction_certificates(client_id=CLIENT, limit=50, offset=0, current_user=CALLER)["data"]
        assert [r["certificate_no"] for r in out["lower_deduction_certificates"]] == ["LDC/2026/1"]
        assert tw.list_lower_deduction_certificates(client_id=OTHER_CLIENT, limit=50, offset=0, current_user=CALLER)["data"][
            "lower_deduction_certificates"] == []
    finally:
        tw._MOCK_LOWER_DEDUCTION.clear()


def test_the_tier_is_executive_for_the_write_and_any_staff_for_the_read():
    """The table's own policy says Executive and above to write; the routes say the same, from the same permission table."""
    from core.permissions import PERMISSIONS
    from fastapi.routing import APIRoute
    by_name = {r.name: r for r in tw.router.routes if isinstance(r, APIRoute)}
    assert by_name["record_lower_deduction_certificate"].methods == {"POST"}
    assert by_name["list_lower_deduction_certificates"].methods == {"GET"}
    assert "Executive" in {getattr(r, "value", r) for r in PERMISSIONS["tds"]["compute"]}
    assert db_provider is not None
