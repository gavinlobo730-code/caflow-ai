"""A deduction typed on the TDS screen may name its supplier, and then it is charged in that supplier's year (POST-A-078).

WHAT WAS WRONG
    A typed deduction carried a name and a PAN and was added up with other typed deductions for the PAN only, while the supplier's purchase
    bills and advances were added up per supplier (services/vendor_tds.aggregate_so_far). The two halves of one payee's year never met: a
    typed professional fee and the supplier's bills each judged the s.194J yearly threshold on their own half, and the tax withheld on one
    half was not credited (s.200) on the other. A typed deduction also missed the supplier's s.197 certificate and s.194A class, and was not
    capped at the payment, all of which the bill path applies.

WHAT THIS HOLDS (mock mode, through the real routes on the in-memory database)
    * A typed deduction that names a supplier is charged on the supplier's year: its bills count toward the threshold the typed payment is
      judged against, and a later bill counts the typed payment and credits its tax.
    * A typed deduction naming no supplier is counted in a supplier's year only while that supplier is the ONE active supplier holding its
      PAN; two holders leave it to neither. A row a bill or an advance wrote is never read as a typed one.
    * The supplier is picked by id, or matched by PAN when exactly one active supplier holds it; two holders and an inactive holder are
      said, not guessed. Another client's supplier is refused; a non-resident supplier is refused (s.195 is a bill's).
    * The certificate number reaches the register; a s.194A class does not reach a payment under another section; the tax is capped at
      the payment and the shortfall said; a supplier not subject to TDS is accepted with a sentence; a bill or an advance on the same day
      for the same amount is named; a person kept out of purchase documents is not shown the year's figures.
    * A correction that retypes the payee re-resolves the supplier from the request; one that does not keeps it.
    * The supplier's permanent delete counts its typed deductions.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.e2e_harness import FakeDB
from core.auth import get_current_user

FIRM = "F1"
CLIENT = "C1"
OTHER_CLIENT = "C2"
EXEC = {"id": "u2", "firm_id": FIRM, "role": "Executive", "email": "e@f1.test", "auth_user_id": "auth-exec"}
PARTNER = {"id": "u0", "firm_id": FIRM, "role": "Partner", "email": "p@f1.test", "auth_user_id": "auth-partner"}

PAN = "AAACA1234A"            # a company: the non-individual limb
SUPPLIER = "00000000-0000-4000-8000-000000000001"
SECOND = "00000000-0000-4000-8000-000000000002"   # a second supplier holding the same PAN
OTHER = "00000000-0000-4000-8000-000000000003"    # a supplier with another PAN
DAY = "2026-06-15"
FY = "2026-27"


@pytest.fixture
def app_db(monkeypatch):
    import routers.tds_workspace as mod
    db = FakeDB()
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    monkeypatch.setattr(mod, "log_event", lambda *a, **k: None)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    monkeypatch.setattr("core.supabase_client.get_service_supabase", lambda: db)
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    app = FastAPI()
    app.include_router(mod.router)
    return app, db


def _supplier(db, vid=SUPPLIER, *, client=CLIENT, pan=PAN, section="194J", **extra):
    row = {"id": vid, "firm_id": FIRM, "client_id": client, "name": f"Supplier {vid}", "pan": pan, "tds_section": section,
           "tds_applicable": True, "is_active": True, "residential_status": "resident"}
    row.update(extra)
    return db.seed("vendors", row)


def _bill(db, bid, taxable, *, vendor=SUPPLIER, tds=0, day=DAY, section="194J", status="received", total=None):
    return db.seed("purchase_bills", {"id": bid, "firm_id": FIRM, "client_id": CLIENT, "vendor_id": vendor, "bill_date": day,
                                      "taxable_amount_paise": taxable, "total_paise": total if total is not None else taxable,
                                      "tds_paise": tds, "tds_section": section,
                                      "tds_advance_adjusted_paise": 0, "status": status, "deleted_at": None})


def _post(app, user=EXEC, path="/api/tds-workspace/deductions", **over):
    body = {"client_id": CLIENT, "deductee_name": "Typed name", "deductee_pan": PAN, "section": "194J",
            "payment_amount_paise": 1_00_000_00, "transaction_date": DAY}
    body.update(over)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False).post(path, json=body)


def _engine(taxable, prior=0, prior_tds=0, *, section="194J", fy=FY):
    from domain.tds.tds_computer import TDSComputer
    return TDSComputer().resolve_tds(section=section, taxable_paise=taxable, fy_prior_taxable_paise=prior, fy_prior_tds_paise=prior_tds,
                                     is_company=True, fy=fy, has_pan=True)


def _threshold(section="194J"):
    from domain.tds.section_rates import tds_rates_for
    rule = tds_rates_for(FY).sections[section]
    return rule.aggregate_threshold_paise or rule.single_threshold_paise


# ── one year for one supplier ──────────────────────────────────────────────────────────────────────────────────────

def test_a_typed_payment_that_names_its_supplier_is_judged_with_the_suppliers_bills(app_db):
    app, db = app_db
    _supplier(db)
    half = _threshold() // 2
    _bill(db, "B1", half)                                    # below the threshold on its own, nothing withheld
    typed = half + 10_000_00                                 # below on its own too; over it with the bill
    d = _post(app, vendor_id=SUPPLIER, payment_amount_paise=typed).json()["data"]
    expected = _engine(typed, prior=half)
    assert expected.applies and expected.tds_paise > 0
    assert d["vendor_id"] == SUPPLIER and d["tds_paise"] == min(expected.tds_paise, typed)
    assert d["explain"]["fy_prior_taxable_paise"] == half
    assert _engine(typed).tds_paise == 0, "on its own the typed payment withholds nothing: the bill is what crosses the threshold"


def test_a_bill_after_a_typed_payment_counts_it_and_credits_its_tax(app_db):
    app, db = app_db
    from services import vendor_tds
    _supplier(db)
    paid = _threshold() + 10_000_00
    d = _post(app, vendor_id=SUPPLIER, payment_amount_paise=paid).json()["data"]
    assert d["tds_paise"] > 0
    agg = vendor_tds.aggregate_so_far(db, firm_id=FIRM, vendor_id=SUPPLIER, section="194J", on_date=DAY, client_id=CLIENT, vendor_pan=PAN)
    assert (agg.base_paise, agg.tds_paise, agg.typed_count) == (paid, d["tds_paise"], 1)
    w = vendor_tds.resolve_resident_tds(db.rows("vendors")[0], "194J", 50_000_00, DAY, FIRM, db, client_id=CLIENT)
    assert w.fy_prior_paise == paid and w.fy_prior_tds_paise == d["tds_paise"]
    assert "deductions typed on the TDS screen" in w.why, "the bill's sentence says a typed deduction moved its figure"


def test_a_typed_row_with_no_supplier_counts_only_while_one_active_supplier_holds_its_pan(app_db):
    app, db = app_db
    from services import vendor_tds
    db.seed("tds_deductions", {"id": "T1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": None, "deductee_pan": PAN,
                               "section": "194J", "transaction_date": DAY, "payment_amount_paise": 40_000_00, "tds_paise": 4_000_00,
                               "purchase_bill_id": None, "purchase_payment_id": None})
    _supplier(db)
    agg = vendor_tds.aggregate_so_far(db, firm_id=FIRM, vendor_id=SUPPLIER, section="194J", on_date=DAY, client_id=CLIENT, vendor_pan=PAN)
    assert (agg.typed_count, agg.typed_base_paise, agg.typed_tds_paise) == (1, 40_000_00, 4_000_00)
    _supplier(db, SECOND)                                       # a second active supplier with the same PAN
    agg = vendor_tds.aggregate_so_far(db, firm_id=FIRM, vendor_id=SUPPLIER, section="194J", on_date=DAY, client_id=CLIENT, vendor_pan=PAN)
    assert agg.typed_count == 0, "two suppliers hold the PAN: the row is given to neither"


def test_an_inactive_second_holder_does_not_take_the_row_away(app_db):
    _app, db = app_db
    from services import vendor_tds
    db.seed("tds_deductions", {"id": "T1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": None, "deductee_pan": PAN,
                               "section": "194J", "transaction_date": DAY, "payment_amount_paise": 40_000_00, "tds_paise": 0,
                               "purchase_bill_id": None, "purchase_payment_id": None})
    _supplier(db)
    _supplier(db, SECOND, is_active=False)
    agg = vendor_tds.aggregate_so_far(db, firm_id=FIRM, vendor_id=SUPPLIER, section="194J", on_date=DAY, client_id=CLIENT, vendor_pan=PAN)
    assert agg.typed_count == 1


def test_a_row_a_bill_or_an_advance_wrote_is_never_read_as_typed(app_db):
    _app, db = app_db
    from services import vendor_tds
    _supplier(db)
    for rid, doc in (("R1", {"purchase_bill_id": "B9"}), ("R2", {"purchase_payment_id": "P9"})):
        db.seed("tds_deductions", {"id": rid, "firm_id": FIRM, "client_id": CLIENT, "vendor_id": None, "deductee_pan": PAN,
                                   "section": "194J", "transaction_date": DAY, "payment_amount_paise": 40_000_00, "tds_paise": 4_000_00,
                                   "purchase_bill_id": None, "purchase_payment_id": None, **doc})
    agg = vendor_tds.aggregate_so_far(db, firm_id=FIRM, vendor_id=SUPPLIER, section="194J", on_date=DAY, client_id=CLIENT, vendor_pan=PAN)
    assert agg.typed_count == 0 and agg.base_paise == 0


def test_another_section_and_another_year_are_not_in_the_typed_count(app_db):
    _app, db = app_db
    from services import vendor_tds
    _supplier(db)
    for rid, sec, day in (("T1", "194C", DAY), ("T2", "194J", "2025-06-15")):
        db.seed("tds_deductions", {"id": rid, "firm_id": FIRM, "client_id": CLIENT, "vendor_id": SUPPLIER, "deductee_pan": PAN,
                                   "section": sec, "transaction_date": day, "payment_amount_paise": 40_000_00, "tds_paise": 0,
                                   "purchase_bill_id": None, "purchase_payment_id": None})
    agg = vendor_tds.aggregate_so_far(db, firm_id=FIRM, vendor_id=SUPPLIER, section="194J", on_date=DAY, client_id=CLIENT, vendor_pan=PAN)
    assert agg.typed_count == 0


# ── which supplier ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_one_active_supplier_holding_the_pan_is_named_for_an_import_row(app_db):
    app, db = app_db
    _supplier(db)
    d = _post(app).json()["data"]
    assert d["vendor_id"] == SUPPLIER and d["deductee_name"] == f"Supplier {SUPPLIER}", "the supplier's own name is stored, not the typed one"
    assert d["explain"]["supplier"] == {"id": SUPPLIER, "name": f"Supplier {SUPPLIER}"}


def test_two_active_holders_are_said_and_neither_is_chosen(app_db):
    app, db = app_db
    _supplier(db)
    _supplier(db, SECOND)
    d = _post(app).json()["data"]
    assert d["vendor_id"] is None and "2 suppliers of this client hold PAN" in d["explain"]["supplier_note"]
    assert "tds_deduction_names_no_supplier" in d["explain"]["gaps"]


def test_an_inactive_only_holder_is_said_and_not_chosen(app_db):
    app, db = app_db
    _supplier(db, is_active=False)
    d = _post(app).json()["data"]
    assert d["vendor_id"] is None and "marked inactive" in d["explain"]["supplier_note"]


def test_a_pan_held_only_by_a_non_resident_supplier_is_said_and_not_chosen(app_db):
    """A payment to a non-resident is withheld under s.195, on a bill; the typed door does not charge it, so the PAN does not pick one."""
    app, db = app_db
    _supplier(db, residential_status="non_resident")
    d = _post(app).json()["data"]
    assert d["vendor_id"] is None
    assert "non-resident" in d["explain"]["supplier_note"] and "section 195" in d["explain"]["supplier_note"]
    assert "tds_deduction_names_no_supplier" in d["explain"]["gaps"]


def test_the_inactive_sentence_asks_for_what_the_form_can_do(app_db):
    """The picker lists active suppliers only, so the sentence does not ask the CA to pick the inactive one."""
    app, db = app_db
    _supplier(db, is_active=False)
    note = _post(app).json()["data"]["explain"]["supplier_note"]
    assert "Mark the supplier active again" in note and "Pick it" not in note


def test_one_rule_says_which_supplier_a_pan_names_for_the_door_and_for_the_year(app_db):
    _app, db = app_db
    from services import vendor_tds
    resident, abroad, retired = ({"id": "a", "is_active": True, "residential_status": "resident"},
                                 {"id": "b", "is_active": True, "residential_status": "non_resident"},
                                 {"id": "c", "is_active": False, "residential_status": None})
    assert vendor_tds.sole_holder([resident, abroad, retired]) is resident
    assert vendor_tds.sole_holder([abroad, retired]) is None
    assert vendor_tds.sole_holder([resident, {**resident, "id": "d"}]) is None
    db.seed("tds_deductions", {"id": "T1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": None, "deductee_pan": PAN,
                               "section": "194J", "transaction_date": DAY, "payment_amount_paise": 40_000_00, "tds_paise": 0,
                               "purchase_bill_id": None, "purchase_payment_id": None})
    _supplier(db)
    _supplier(db, SECOND, residential_status="non_resident")
    year = lambda v: vendor_tds.aggregate_so_far(db, firm_id=FIRM, vendor_id=v, section="194J", on_date=DAY, client_id=CLIENT,
                                                 vendor_pan=PAN).typed_count
    assert (year(SUPPLIER), year(SECOND)) == (1, 0), "a non-resident second holder does not take the row from the resident one"


def test_a_supplier_id_that_is_not_one_is_refused_at_the_door_in_words(app_db):
    app, db = app_db
    _supplier(db)
    for path in ("/api/tds-workspace/deductions", "/api/tds-workspace/deductions/preview"):
        r = _post(app, path=path, vendor_id="V1")
        assert r.status_code == 422 and "not a supplier's id" in r.text, (path, r.status_code, r.text)
    assert db.rows("tds_deductions") == []


def test_a_picked_inactive_supplier_is_still_named(app_db):
    """A supplier marked inactive is still the person the money went to: picked by id, it is named."""
    app, db = app_db
    _supplier(db, is_active=False)
    assert _post(app, vendor_id=SUPPLIER).json()["data"]["vendor_id"] == SUPPLIER


def test_another_clients_supplier_is_refused_in_words(app_db):
    app, db = app_db
    _supplier(db, client=OTHER_CLIENT)
    r = _post(app, vendor_id=SUPPLIER)
    assert r.status_code == 404 and "not one of this client's suppliers" in r.json()["detail"]
    assert db.rows("tds_deductions") == []


def test_a_non_resident_supplier_is_refused_because_section_195_is_a_bills(app_db):
    app, db = app_db
    _supplier(db, residential_status="non_resident")
    r = _post(app, vendor_id=SUPPLIER)
    assert r.status_code == 422 and "section 195" in r.json()["detail"]
    assert db.rows("tds_deductions") == []


# ── what the bill path applies, applied ────────────────────────────────────────────────────────────────────────────

def test_the_suppliers_certificate_lowers_the_rate_and_its_number_reaches_the_register(app_db):
    app, db = app_db
    _supplier(db)
    db.seed("tds_lower_deduction_certificates", {"id": "LDC1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": SUPPLIER,
                                                 "certificate_no": "LDC-001", "section": "194J", "rate_bps": 100,
                                                 "valid_from": "2026-04-01", "valid_to": "2027-03-31", "ceiling_paise": 50_00_000_00})
    d = _post(app, vendor_id=SUPPLIER, payment_amount_paise=_threshold() + 10_000_00).json()["data"]
    stored = db.rows("tds_deductions")[0]
    assert stored["is_lower_deduction"] is True and stored["lower_deduction_cert"] == "LDC-001"
    assert d["tds_rate_pct"] == 1.0 and "LDC-001" in d["explain"]["why"]
    basis = d["explain"]["rate_basis"]
    assert "section 197 certificate LDC-001" in basis and not basis.startswith("Charged at the non-individual"), \
        "the rate sentence says the certificate's rate, not the limb the PAN would have picked"


def test_a_class_recorded_for_section_194a_does_not_reach_a_payment_under_another_section(app_db):
    app, db = app_db
    _supplier(db, section="194A", interest_threshold_class="bank_deposit")
    r = _post(app, vendor_id=SUPPLIER, section="194J")
    assert r.status_code == 200, r.text            # the engine refuses a class on a section with one limit; it is not passed
    assert r.json()["data"]["tds_paise"] == min(_engine(1_00_000_00).tds_paise, 1_00_000_00)


def test_the_tax_is_capped_at_the_payment_and_the_shortfall_is_said(app_db):
    app, db = app_db
    _supplier(db)
    big = _threshold() * 4
    _bill(db, "B1", big)                                     # a large earlier bill that withheld nothing
    small = 1_000_00
    d = _post(app, vendor_id=SUPPLIER, payment_amount_paise=small).json()["data"]
    due = _engine(small, prior=big).tds_paise
    assert due > small
    assert d["tds_paise"] == small and d["explain"]["shortfall_paise"] == due - small
    assert "tds_deduction_capped_at_the_payment" in d["explain"]["gaps"]


def test_the_shortfall_is_part_of_the_year_a_blocked_person_is_not_shown(app_db):
    """The shortfall is the year's tax less this payment, and with the rate it gives the supplier's billed total back exactly."""
    app, db = app_db
    _supplier(db)
    _bill(db, "B1", _threshold() * 4, status="draft")
    blocked = {**EXEC, "permission_overrides": {"accounting:read": False}}
    d = _post(app, user=blocked, path="/api/tds-workspace/deductions/preview", vendor_id=SUPPLIER, payment_amount_paise=1_000_00).json()["data"]
    assert d["tds_paise"] == 1_000_00 and d["explain"]["shortfall_paise"] is None
    assert "tds_deduction_capped_at_the_payment" in d["explain"]["gaps"], "the cap is still said, without its figure"


def test_below_the_threshold_the_rate_stated_is_nil_whichever_door(app_db):
    app, db = app_db
    _supplier(db)
    small = 1_000_00
    named = _post(app, path="/api/tds-workspace/deductions/preview", vendor_id=SUPPLIER, payment_amount_paise=small).json()["data"]
    typed = _post(app, path="/api/tds-workspace/deductions/preview", deductee_pan="AAACZ1111Z", payment_amount_paise=small).json()["data"]
    assert not named["explain"]["applies"] and not typed["explain"]["applies"]
    assert named["explain"]["rate_pct"] == 0 and typed["explain"]["rate_pct"] == 0


def test_a_supplier_recorded_as_not_subject_to_tds_is_accepted_with_a_sentence(app_db):
    app, db = app_db
    _supplier(db, tds_applicable=False)
    d = _post(app, vendor_id=SUPPLIER).json()["data"]
    assert d["vendor_id"] == SUPPLIER
    assert "tds_supplier_recorded_not_subject_to_tds" in d["explain"]["gaps"]


def test_a_bill_on_the_same_day_for_the_same_amount_is_named(app_db):
    app, db = app_db
    _supplier(db)
    _bill(db, "B1", 1_00_000_00)
    d = _post(app, vendor_id=SUPPLIER, payment_amount_paise=1_00_000_00).json()["data"]
    assert "tds_deduction_mirrors_a_document" in d["explain"]["gaps"]
    d2 = _post(app, vendor_id=SUPPLIER, payment_amount_paise=99_000_00).json()["data"]
    assert "tds_deduction_mirrors_a_document" not in d2["explain"]["gaps"]


def test_a_typed_amount_equal_to_a_bills_total_is_named_too(app_db):
    """The box has long been labelled the gross payment, so a CA who types the bill's total is caught as well as one who types its value."""
    app, db = app_db
    _supplier(db)
    _bill(db, "B1", 1_00_000_00, total=1_18_000_00)
    d = _post(app, vendor_id=SUPPLIER, payment_amount_paise=1_18_000_00).json()["data"]
    assert "tds_deduction_mirrors_a_document" in d["explain"]["gaps"]


def test_a_person_kept_out_of_purchase_documents_is_not_shown_the_years_figures(app_db):
    app, db = app_db
    _supplier(db)
    _bill(db, "B1", _threshold())
    blocked = {**EXEC, "permission_overrides": {"accounting:read": False}}
    d = _post(app, user=blocked, path="/api/tds-workspace/deductions/preview", vendor_id=SUPPLIER).json()["data"]
    assert d["explain"]["fy_prior_taxable_paise"] is None and d["explain"]["fy_prior_tds_paise"] is None
    assert "not open to you" in d["explain"]["why"]
    seen = _post(app, path="/api/tds-workspace/deductions/preview", vendor_id=SUPPLIER).json()["data"]
    assert seen["explain"]["fy_prior_taxable_paise"] == _threshold() and d["tds_paise"] == seen["tds_paise"]


def test_the_year_is_said_to_be_added_up_for_a_supplier_with_no_pan(app_db):
    app, db = app_db
    _supplier(db, pan=None)
    d = _post(app, vendor_id=SUPPLIER, deductee_pan=None).json()["data"]
    assert "tds_aggregate_not_read_without_a_pan" not in d["explain"]["gaps"], "the supplier is the key: its year was read"


# ── a correction ───────────────────────────────────────────────────────────────────────────────────────────────────

def _patch(app, rid, user=EXEC, **body):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False).patch(f"/api/tds-workspace/deductions/{rid}", json=body)


def test_a_correction_that_retypes_the_payee_re_resolves_the_supplier_and_one_that_does_not_keeps_it(app_db):
    app, db = app_db
    _supplier(db)
    _supplier(db, OTHER, pan="AAACB5678B")
    rid = _post(app, vendor_id=SUPPLIER).json()["data"]["id"]
    kept = _patch(app, rid, payment_amount_paise=2_00_000_00).json()["data"]
    assert kept["vendor_id"] == SUPPLIER, "a correction that does not touch the payee keeps the supplier"
    moved = _patch(app, rid, deductee_pan="AAACB5678B").json()["data"]
    assert moved["vendor_id"] == OTHER and moved["deductee_pan"] == "AAACB5678B", "the retyped PAN decides, not the stored supplier"
    none = _patch(app, rid, deductee_pan="AAACZ9999Z").json()["data"]
    assert none["vendor_id"] is None, "a PAN no supplier holds leaves the deduction without one"


def test_a_correction_of_the_name_alone_keeps_the_supplier_picked(app_db):
    """Two suppliers hold the PAN, so the supplier was picked; a name sent, the stored name sent back, or the same PAN in other letters is
    not a different payee, and must not drop the row into the PAN's pool."""
    app, db = app_db
    _supplier(db)
    _supplier(db, SECOND)
    rid = _post(app, vendor_id=SUPPLIER).json()["data"]["id"]
    for body in ({"deductee_name": "Retyped name"}, {"deductee_name": f"Supplier {SUPPLIER}", "deductee_pan": PAN},
                 {"deductee_pan": " " + PAN.lower() + " "}):
        got = _patch(app, rid, **body).json()["data"]
        assert got["vendor_id"] == SUPPLIER, body
        assert got["deductee_name"] == f"Supplier {SUPPLIER}", "the name on a supplier's row is the supplier's own"


def test_a_correction_leaves_the_row_out_of_its_own_year(app_db):
    app, db = app_db
    _supplier(db)
    paid = _threshold() + 10_000_00
    rid = _post(app, vendor_id=SUPPLIER, payment_amount_paise=paid).json()["data"]["id"]
    again = _patch(app, rid, payment_amount_paise=paid).json()["data"]
    assert again["explain"]["fy_prior_taxable_paise"] == 0, "the row being corrected is not counted as an earlier payment of its own year"


# ── the supplier's permanent delete ────────────────────────────────────────────────────────────────────────────────

def test_the_suppliers_delete_counts_its_typed_deductions():
    from routers.vendors import _VENDOR_DEPENDENCY_TABLES
    from services.party_erasure import _RECORD_WORDS
    assert ("tds_register", "tds_deductions", None) in _VENDOR_DEPENDENCY_TABLES   # undated: blocks on referential grounds
    assert "TDS" in _RECORD_WORDS["tds_register"]
