"""An emptied box on a relationship entity, a lead or an HSN library code is cleared, and an entity's PAN and GSTIN are corrected
and never removed (POST-A-399, fifth slice).

WHAT WAS WRONG
    Three edit screens send an emptied box as an explicit null (`email: editForm.email.trim() || null`, `phone: lead.phone || null`,
    `gst_rate_pct: gstRate === "" ? null : gstRate`) to a route that dropped every null from its body. So a person who emptied a
    prospect's phone number, an entity's email or a code's rate hint and pressed Save was told it was saved, and the old value was
    still there. The survey of 22-11-2026 found these among the five edit routes where the defect can really happen from a screen
    (the other seventeen either have no screen that sends an optional field through them or already send "" and keep it).

WHAT IS ASSERTED
    * each route clears exactly the fields its model names in `CLEARABLE` when they are SENT null or blank, and writes NULL;
    * a field that is NOT sent is left as it was, and a null for a field outside `CLEARABLE` still reads "not sent";
    * an entity's PAN and GSTIN are not removed by an edit: emptying one that is on file is refused in one sentence and nothing is
      written, correcting one is taken, and an empty one over nothing is neither refused nor stored as "";
    * the screen's own sentence for that refusal is the server's (the page is read, so this file is one the browser-contract job runs).

Driven through each handler with its stand-in store (the store the route itself falls back to when no database is configured), and
for the entity through the database path as well, on the shared in-memory client.
"""
from __future__ import annotations

import pathlib

import pytest
from fastapi import HTTPException

import routers.firm_hsn_library as hsn
import routers.lifecycle as lifecycle
import routers.relationships as rel
from models.clearable import clearable_fields
from models.firm_hsn_library import FirmHsnLibraryUpdateIn
from tests.e2e_harness import FakeDB

FIRM = "firm-clear-5"
PARTNER = {"id": "u-p", "firm_id": FIRM, "role": "Partner", "auth_user_id": "a-p", "email": "p@firm.test"}
WEB = pathlib.Path(__file__).resolve().parents[2] / "web"
ENTITY_PAGE = WEB / "app" / "relationships" / "[entity_id]" / "EntityDetailClient.tsx"   # apps/web/app/relationships/[entity_id]/EntityDetailClient.tsx


def test_what_each_of_the_three_may_clear():
    assert clearable_fields(rel.EntityUpdateIn()) == {"email", "phone", "address", "notes"}
    assert clearable_fields(lifecycle.LeadUpdateIn()) == {"email", "phone", "notes"}
    assert clearable_fields(FirmHsnLibraryUpdateIn()) == {"gst_rate_pct", "notes"}


# ── the relationship entity ─────────────────────────────────────────────────────────────────────────────────────────────

def _entity(**more):
    return {"id": "ent-1", "firm_id": FIRM, "full_name": "Asha Rao", "entity_type": "Individual", "pan": "ABCPR1234F",
            "gstin": None, "email": "asha@x.test", "phone": "9800000000", "address": "12 MG Road", "notes": "director", **more}


@pytest.fixture(params=["stand-in", "database"])
def entity_store(request, monkeypatch):
    """The entity route against its own stand-in list and against a database client: one behaviour, two paths."""
    monkeypatch.setattr(rel, "_assert_entity_visible", lambda *a, **k: None)
    if request.param == "stand-in":
        monkeypatch.setattr(rel, "_db", lambda: None)
        monkeypatch.setattr(rel, "_MOCK_ENTITIES", [_entity()])
        return lambda: rel._MOCK_ENTITIES[0]
    db = FakeDB()
    db.seed("entities", _entity())
    monkeypatch.setattr(rel, "_db", lambda: db)
    return lambda: db.rows("entities")[0]


def _edit_entity(**sent):
    return rel.update_entity("ent-1", rel.EntityUpdateIn(**sent), current_user=PARTNER)


def test_an_emptied_email_and_phone_are_cleared_and_what_was_not_sent_stays(entity_store):
    out = _edit_entity(full_name="Asha Rao", email=None, phone="   ")
    assert out["success"] is True
    row = entity_store()
    assert row["email"] is None and row["phone"] is None, "an emptied contact particular is still on file"
    assert row["address"] == "12 MG Road" and row["notes"] == "director", "a field the request did not send was changed"
    assert row["pan"] == "ABCPR1234F"


def test_a_typed_value_is_stored_and_a_null_for_a_field_that_cannot_be_cleared_reads_not_sent(entity_store):
    _edit_entity(email="new@x.test", full_name=None, entity_type=None)
    row = entity_store()
    assert row["email"] == "new@x.test" and row["full_name"] == "Asha Rao" and row["entity_type"] == "Individual"


@pytest.mark.parametrize("emptied", [None, "", "   "])
def test_a_pan_on_file_is_not_removed_by_an_edit_and_nothing_is_written(entity_store, emptied):
    with pytest.raises(HTTPException) as refused:
        _edit_entity(pan=emptied, email=None)
    assert refused.value.status_code == 422
    assert refused.value.detail == ("The PAN on file can be corrected but not removed: enter the corrected PAN. "
                                    "The register tells one person or company from another across the firm's clients by it.")
    row = entity_store()
    assert row["pan"] == "ABCPR1234F" and row["email"] == "asha@x.test", "a refused edit wrote part of itself"


def test_a_pan_is_corrected_and_an_empty_gstin_over_nothing_is_neither_refused_nor_stored_as_blank(entity_store):
    _edit_entity(pan="abcpr1234g", gstin="")
    row = entity_store()
    assert row["pan"] == "ABCPR1234G"
    assert row.get("gstin") is None, "an empty identifier over nothing was stored as a blank"


# ── the lead ────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def lead(monkeypatch):
    monkeypatch.setattr(lifecycle, "_db", lambda: None)
    monkeypatch.setattr(lifecycle, "_MOCK_LEADS", [{"id": "lead-1", "firm_id": FIRM, "company_name": "Rao Traders", "contact_name": "Asha",
                                                    "email": "asha@rao.test", "phone": "9800000000", "source": "referral", "stage": "new",
                                                    "estimated_value_paise": 500000, "notes": "{}"}])
    monkeypatch.setattr(lifecycle.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(lifecycle, "log_event", lambda *a, **k: None)
    return lifecycle._MOCK_LEADS[0]


def test_an_emptied_email_and_phone_of_a_lead_are_cleared_as_the_pipeline_screen_sends_them(lead):
    """The pipeline screen sends the whole lead on every save, with `email: lead.email || null` for an emptied box."""
    out = lifecycle.update_lead("lead-1", lifecycle.LeadUpdateIn(company_name="Rao Traders", contact_name="Asha", email=None, phone=None,
                                                                 source="referral", stage="new", estimated_value_paise=500000, notes="{}"),
                                current_user=PARTNER)
    assert out["success"] is True
    assert lead["email"] is None and lead["phone"] is None, "an emptied email or phone of a prospect is still on file"
    assert lead["company_name"] == "Rao Traders" and lead["estimated_value_paise"] == 500000 and lead["notes"] == "{}"


def test_a_lead_field_that_was_not_sent_stays_and_a_null_outside_the_set_reads_not_sent(lead):
    lifecycle.update_lead("lead-1", lifecycle.LeadUpdateIn(stage="contacted", source=None, estimated_value_paise=None), current_user=PARTNER)
    assert lead["stage"] == "contacted" and lead["email"] == "asha@rao.test" and lead["phone"] == "9800000000"
    assert lead["source"] == "referral" and lead["estimated_value_paise"] == 500000


# ── the HSN library code ────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def code(monkeypatch):
    monkeypatch.setattr(hsn, "_USE_MOCK", True)
    monkeypatch.setattr(hsn, "MOCK_LIBRARY", [{"id": "code-1", "firm_id": FIRM, "hsn_code": "998211", "hsn_type": "sac",
                                               "description": "Legal advisory", "gst_rate_pct": 18.0, "uqc": None, "notes": "checked", "is_active": True}])
    return hsn.MOCK_LIBRARY[0]


def test_an_emptied_rate_hint_is_cleared_as_the_library_screen_sends_it(code):
    """The edit sends `{ description, gst_rate_pct: null }` for an emptied rate box."""
    out = hsn.update_code("code-1", FirmHsnLibraryUpdateIn(description="Legal advisory", gst_rate_pct=None), current_user=PARTNER)
    assert out["success"] is True
    assert code["gst_rate_pct"] is None, "an emptied rate hint is still on file"
    assert code["notes"] == "checked" and code["description"] == "Legal advisory"


def test_a_rate_that_was_not_sent_stays_and_a_typed_one_is_stored(code):
    hsn.update_code("code-1", FirmHsnLibraryUpdateIn(is_active=False), current_user=PARTNER)
    assert code["gst_rate_pct"] == 18.0 and code["is_active"] is False
    hsn.update_code("code-1", FirmHsnLibraryUpdateIn(gst_rate_pct=5), current_user=PARTNER)
    assert code["gst_rate_pct"] == 5


# ── the screen says the same sentence before anything is sent ───────────────────────────────────────────────────────────

def test_the_entity_screen_refuses_an_emptied_identifier_in_the_servers_words_and_sends_no_null_for_one():
    page = ENTITY_PAGE.read_text()
    assert rel.ENTITY_IDENTIFIER_WHY in page, "the entity screen's reason for refusing an emptied PAN or GSTIN is not the server's"
    flat = " ".join(page.split())
    assert 'removedIdentifierProblem("PAN", entity?.pan, editForm.pan, ENTITY_IDENTIFIER_WHY)' in flat
    assert 'removedIdentifierProblem("GSTIN", entity?.gstin, editForm.gstin, ENTITY_IDENTIFIER_WHY)' in flat
    assert "email: editedText(editForm.email, entity?.email)" in flat and "phone: editedText(editForm.phone, entity?.phone)" in flat
    assert "pan: editForm.pan.trim().toUpperCase() || null" not in flat and "gstin: editForm.gstin.trim().toUpperCase() || null" not in flat
