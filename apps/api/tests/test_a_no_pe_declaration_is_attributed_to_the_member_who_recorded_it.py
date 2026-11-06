"""
A no-PE declaration is attributed to the member who recorded it, so the register's gap can be cleared (POST-A-401).

`tds_register_service` adds GAP_NO_PE_DECLARATION_UNDATED to every s.195 bill whose supplier has the declaration ticked and does not
hold BOTH a date and a member (`no_pe_declaration_by`, migration 311). The supplier form wrote the date and nothing wrote the member,
so a CA who did what the sentence asks ("record the date and the reference on the vendor") was told on every bill that nobody had
recorded who obtained it, for ever. These tests hold the rule (`domain/tds/no_pe_declaration.declarant_write`), the three doors that
write a supplier (create, bulk import, edit) and the end of it: a declaration recorded through a door clears the gap on the next bill.
"""
from __future__ import annotations

import pytest

import routers.vendors as ve
from domain.tds.no_pe_declaration import DECLARANT_COLUMN, DECLARATION_FIELDS, declarant_write
from domain.tds.residency import GAP_NO_PE_DECLARATION_UNDATED
from models.parties import VendorIn, VendorUpdateIn

ME = "user-internal-id"            # users.id, which is what the column references
SOMEONE_ELSE = "an-earlier-member"
TICKED = {"no_pe_declaration_on_file": True, "no_pe_declaration_on": "2026-05-01", "no_pe_declaration_ref": "Letter 7"}


# ── the rule ────────────────────────────────────────────────────────────────

def test_a_request_that_ticks_and_dates_the_declaration_names_the_member():
    assert declarant_write(sent=dict(TICKED), stored=None, actor_id=ME) == {DECLARANT_COLUMN: ME}
    assert declarant_write(sent=dict(TICKED), stored={"name": "Helvetica AG"}, actor_id=ME) == {DECLARANT_COLUMN: ME}


def test_a_request_that_carries_none_of_the_three_fields_never_writes_the_column():
    stored = {**TICKED, DECLARANT_COLUMN: SOMEONE_ELSE}
    assert declarant_write(sent={"name": "Renamed"}, stored=stored, actor_id=ME) == {}
    assert declarant_write(sent={"phone": "1"}, stored={**TICKED}, actor_id=ME) == {}      # an unattributed legacy row is left alone too


@pytest.mark.parametrize("missing", ["no_pe_declaration_on_file", "no_pe_declaration_on"])
def test_a_declaration_that_is_not_on_file_or_has_no_date_names_nobody(missing):
    sent = {**TICKED}
    sent[missing] = False if missing == "no_pe_declaration_on_file" else None
    assert declarant_write(sent=sent, stored=None, actor_id=ME) == {}


def test_taking_the_declaration_off_file_empties_the_name_that_stood_on_it():
    stored = {**TICKED, DECLARANT_COLUMN: SOMEONE_ELSE}
    assert declarant_write(sent={"no_pe_declaration_on_file": False}, stored=stored, actor_id=ME) == {DECLARANT_COLUMN: None}
    # …and so does a request that leaves it with no date (no door sends one today, PATCH refuses a blank date and drops a null, but the rule is total
    # and a name on an undated declaration attributes nothing)
    assert declarant_write(sent={"no_pe_declaration_on": ""}, stored=stored, actor_id=ME) == {DECLARANT_COLUMN: None}


def test_a_save_that_leaves_an_attributed_declaration_exactly_as_it_was_keeps_its_declarant():
    """The supplier form sends the three fields on every save. Whoever saves the form to change a phone number did not
    record the declaration, and must not take it over."""
    stored = {**TICKED, DECLARANT_COLUMN: SOMEONE_ELSE}
    assert declarant_write(sent=dict(TICKED), stored=stored, actor_id=ME) == {}


@pytest.mark.parametrize("change", [
    {"no_pe_declaration_on": "2026-06-01"},
    {"no_pe_declaration_ref": "Letter 8"},
])
def test_a_save_that_changes_the_date_or_the_reference_is_the_recording_of_that_member(change):
    stored = {**TICKED, DECLARANT_COLUMN: SOMEONE_ELSE}
    assert declarant_write(sent={**TICKED, **change}, stored=stored, actor_id=ME) == {DECLARANT_COLUMN: ME}


def test_a_ticked_and_dated_declaration_nobody_is_named_on_is_named_by_the_next_save_that_carries_it():
    """A supplier recorded before the column was written has a date and no member (migration 311: backfilling would be
    inventing evidence, so nothing sweeps them). A person saving the form with the declaration ticked and dated is the first
    to put a name on it; a save that carries none of its fields does not."""
    stored = {**TICKED, DECLARANT_COLUMN: None}
    assert declarant_write(sent=dict(TICKED), stored=stored, actor_id=ME) == {DECLARANT_COLUMN: ME}
    assert declarant_write(sent={"name": "x"}, stored=stored, actor_id=ME) == {}


def test_a_request_with_no_member_names_nobody_rather_than_something_unreadable():
    assert declarant_write(sent=dict(TICKED), stored=None, actor_id=None) == {}
    assert declarant_write(sent=dict(TICKED), stored=None, actor_id="") == {}


def test_the_fields_and_the_column_are_the_ones_migration_311_and_the_model_carry():
    assert DECLARANT_COLUMN == "no_pe_declaration_by"
    for field in DECLARATION_FIELDS:
        assert field in VendorIn.model_fields and field in VendorUpdateIn.model_fields, field
    assert DECLARANT_COLUMN not in VendorIn.model_fields, "the column is the server's to write, never a field a caller sends"
    assert DECLARANT_COLUMN not in VendorUpdateIn.model_fields, "nor one an edit sends"


# ── the three doors ─────────────────────────────────────────────────────────

USER = {"id": ME, "firm_id": "F", "role": "Partner", "auth_user_id": "auth-id-not-the-internal-one"}


@pytest.fixture
def doors(monkeypatch):
    monkeypatch.setattr(ve, "can_access_client", lambda u, c: True)
    monkeypatch.setattr(ve, "assert_client_access", lambda u, c: None)
    monkeypatch.setattr(ve, "_USE_MOCK", True)
    monkeypatch.setattr(ve, "MOCK_VENDORS", [])
    return ve


def _vendor(**over):
    base = dict(client_id="C1", name="Helvetica AG", residential_status="non_resident", country_of_residence="CH",
                tax_identification_number="CH-123")
    base.update(over)
    return VendorIn(**base)


def test_create_stamps_the_member_the_internal_id_and_not_the_sign_in_id(doors):
    out = doors.create_vendor(_vendor(**TICKED), current_user=USER)
    assert out["data"][DECLARANT_COLUMN] == ME
    assert out["data"][DECLARANT_COLUMN] != USER["auth_user_id"]
    assert doors.MOCK_VENDORS[0][DECLARANT_COLUMN] == ME


def test_create_without_the_declaration_writes_no_name(doors):
    out = doors.create_vendor(_vendor(), current_user=USER)
    assert not out["data"].get(DECLARANT_COLUMN)
    out = doors.create_vendor(_vendor(name="Dated only", no_pe_declaration_on="2026-05-01"), current_user=USER)
    assert not out["data"].get(DECLARANT_COLUMN), "a date with the box unticked is not a declaration on file"


def test_the_bulk_import_stamps_the_member_too(doors):
    item = {"client_id": "C1", "name": "Bulk GmbH", "residential_status": "non_resident", "country_of_residence": "DE",
            "tax_identification_number": "DE-1", **TICKED}
    out = doors.create_vendors_bulk(ve.VendorBulkIn(vendors=[item]), current_user=USER)
    assert out["data"]["created"], out
    assert doors.MOCK_VENDORS[0][DECLARANT_COLUMN] == ME


def _stored(doors, **over):
    row = {"id": "V1", "firm_id": "F", "client_id": "C1", "name": "Helvetica AG", "residential_status": "non_resident",
           "country_of_residence": "CH", "tax_identification_number": "CH-123", **over}
    doors.MOCK_VENDORS.append(row)
    return row


def test_edit_that_records_the_declaration_stamps_the_member(doors):
    _stored(doors)
    out = doors.update_vendor("V1", VendorUpdateIn(no_pe_declaration_on_file=True, no_pe_declaration_on="2026-05-01"), current_user=USER)
    assert out["data"][DECLARANT_COLUMN] == ME


def test_edit_that_does_not_touch_the_declaration_leaves_the_name(doors):
    _stored(doors, **TICKED, **{DECLARANT_COLUMN: SOMEONE_ELSE})
    out = doors.update_vendor("V1", VendorUpdateIn(name="Renamed AG"), current_user=USER)
    assert out["data"][DECLARANT_COLUMN] == SOMEONE_ELSE


def test_edit_that_takes_the_declaration_off_file_empties_the_name(doors):
    _stored(doors, **TICKED, **{DECLARANT_COLUMN: SOMEONE_ELSE})
    out = doors.update_vendor("V1", VendorUpdateIn(no_pe_declaration_on_file=False), current_user=USER)
    assert out["data"][DECLARANT_COLUMN] is None


def test_a_caller_cannot_name_the_declarant_through_any_door(doors):
    """The column is the server's to write: a forged `no_pe_declaration_by` in a create, a bulk item or an edit is dropped by the models and the stored value is
    the member of the request (or, for an edit that does not touch the declaration, what was stored)."""
    forged = "someone-who-never-recorded-it"
    created = doors.create_vendor(VendorIn(**{**_vendor(**TICKED).model_dump(), DECLARANT_COLUMN: forged}), current_user=USER)
    assert created["data"][DECLARANT_COLUMN] == ME
    item = {"client_id": "C1", "name": "Bulk GmbH", "residential_status": "non_resident", "country_of_residence": "DE",
            "tax_identification_number": "DE-1", **TICKED, DECLARANT_COLUMN: forged}
    doors.create_vendors_bulk(ve.VendorBulkIn(vendors=[item]), current_user=USER)
    assert [v[DECLARANT_COLUMN] for v in doors.MOCK_VENDORS] == [ME, ME]
    _stored(doors, **TICKED, **{DECLARANT_COLUMN: SOMEONE_ELSE})
    edited = doors.update_vendor("V1", VendorUpdateIn(**{"name": "Renamed AG", DECLARANT_COLUMN: forged}), current_user=USER)
    assert edited["data"][DECLARANT_COLUMN] == SOMEONE_ELSE


def test_edit_that_resaves_an_unchanged_attributed_declaration_keeps_its_declarant(doors):
    _stored(doors, **TICKED, **{DECLARANT_COLUMN: SOMEONE_ELSE})
    out = doors.update_vendor("V1", VendorUpdateIn(**TICKED), current_user=USER)
    assert out["data"][DECLARANT_COLUMN] == SOMEONE_ELSE


# ── the end of it: the gap clears ───────────────────────────────────────────

class _RegisterDB:
    def table(self, _): return self
    def upsert(self, *a, **k): return self
    def delete(self): return self
    def eq(self, *a): return self
    def execute(self): return type("R", (), {"data": []})()


def _gaps_on_a_nil_195_bill(vendor: dict) -> list[str]:
    from services.tds_register_service import sync_for_bill
    bill = {"id": "b1", "client_id": "c1", "status": "received", "bill_date": "2025-10-25", "taxable_amount_paise": 10_00_000_00,
            "tds_paise": 0, "tds_rate_bps": 0, "tds_section": "195", "form_15ca_ack_no": "ACK123"}
    out = sync_for_bill(_RegisterDB(), "f1", "c1", bill, vendor)
    return list(out.get("statutory_gaps", []))


def test_a_declaration_recorded_through_a_door_clears_the_gap_on_the_next_bill(doors):
    """The ledger's test: before this, the gap stood after the CA had done everything its sentence asks."""
    # ticked and dated, the way the form sent it before: the gap stands
    assert GAP_NO_PE_DECLARATION_UNDATED in _gaps_on_a_nil_195_bill(
        {"id": "v1", "name": "Helvetica AG", "residential_status": "non_resident", "country_of_residence": "CH",
         "tax_identification_number": "T1", **TICKED})
    # recorded through the create door: the stored row carries the member, and the gap is gone
    stored = doors.create_vendor(_vendor(**TICKED), current_user=USER)["data"]
    assert GAP_NO_PE_DECLARATION_UNDATED not in _gaps_on_a_nil_195_bill({**stored, "id": "v1"})
