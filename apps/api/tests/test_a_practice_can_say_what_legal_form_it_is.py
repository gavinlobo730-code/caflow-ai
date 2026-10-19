"""A firm can say what legal form it is (ledger POST-A-210).

WHAT WAS WRONG
    The practice client is created with `entity_type = 'Partnership'` because sign-up never asks, and nothing could
    change it afterwards: `PATCH /api/practice/identity` carried only PAN, GSTIN and state, the generic client edit
    does accept an entity type, but the practice client is left out of every client list (guardrail G2), so no screen
    reaches that edit. A proprietorship, an LLP or a company running a CA practice had its own books typed as a
    partnership for good, and the notes to its accounts and the income-tax workings read that value.

WHAT IS HELD
    * the practice identity read serves the stored legal form and the list of forms the update accepts, in the
      model's own order, so the screen carries no list of its own;
    * the identity update sets the legal form, on the firm's own practice client only, and writes the old and the new
      value to the audit log (the edit log the Companies (Accounts) Rules 2014 Rule 3(1) proviso requires);
    * a legal form the model does not know is refused before anything is written, and an update that names no legal
      form leaves it alone (a PAN correction does not reset it to a default);
    * the same holds at sign-up: `POST /api/onboarding/firm` took the form as a bare string and a value the database's
      CHECK would refuse made the practice client silently not exist (the error was logged and swallowed), so it is
      the same `EntityType` there, and the form chosen is the form the practice client is created with;
    * the Practice screen shows the stored word, offers only the server's list, says what the default is and that
      the screen is left out when an API that does not send the list is still deployed.
"""
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

import routers.practice as practice
import services.internal_client_service as ics
from models.client import EntityType, PracticeIdentityUpdate
from tests.e2e_harness import FakeDB

FIRM, OTHER_FIRM = "FIRM-A", "FIRM-B"
PRACTICE, ORDINARY = "PRACTICE-A", "CLIENT-1"
WEB = Path(__file__).resolve().parents[2] / "web"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth-1", "email": "p@f.test", "role": "Partner"}


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(practice, "_db", lambda: db)
    monkeypatch.setattr(practice, "_USE_MOCK", False)
    monkeypatch.setattr(ics, "_db", lambda: db)
    monkeypatch.setattr(ics, "_USE_MOCK", False)
    db.seed("firms", {"id": FIRM, "pan": "AAAPL1234C", "internal_client_id": PRACTICE})
    db.seed("firms", {"id": OTHER_FIRM, "pan": "BBBPL1234C", "internal_client_id": "PRACTICE-B"})
    base = {"pan": "AAAPL1234C", "gstin": None, "state": "Maharashtra", "state_code": "27"}
    db.seed("clients", {"id": PRACTICE, "firm_id": FIRM, "is_internal": True, "entity_type": "Partnership", **base})
    db.seed("clients", {"id": ORDINARY, "firm_id": FIRM, "is_internal": False, "entity_type": "Partnership", **base})
    db.seed("clients", {"id": "PRACTICE-B", "firm_id": OTHER_FIRM, "is_internal": True,
                        "entity_type": "Partnership", **base})
    events: list = []
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: events.append((a, k)))
    return db, events


def _stored(db, client_id):
    return next(r for r in db.rows("clients") if r["id"] == client_id)


def _patch(**fields):
    return practice.update_practice_identity(PracticeIdentityUpdate(**fields), current_user=CALLER)


# ── the read ────────────────────────────────────────────────────────────────

def test_the_read_serves_the_stored_form_and_the_forms_the_update_accepts(world):
    db, _ = world
    _stored(db, PRACTICE)["entity_type"] = "LLP"
    res = practice.get_practice(current_user=CALLER)
    assert res["success"] is True
    data = res["data"]
    assert data["identity"]["entity_type"] == "LLP"
    assert data["entity_types"] == [e.value for e in EntityType]


def test_the_list_served_is_the_one_the_database_and_the_tax_table_know():
    from services.compliance_obligation_service import CLIENT_ENTITY_TYPES
    assert [e.value for e in EntityType] == list(CLIENT_ENTITY_TYPES)


# ── the write ───────────────────────────────────────────────────────────────

def test_the_update_sets_the_form_on_the_firms_own_practice_client_only(world):
    db, _ = world
    res = _patch(entity_type="LLP")
    assert res["success"] is True and res["data"]["fields"] == ["entity_type"]
    assert _stored(db, PRACTICE)["entity_type"] == "LLP"
    # The firm's ordinary client and another firm's practice client are not touched.
    assert _stored(db, ORDINARY)["entity_type"] == "Partnership"
    assert _stored(db, "PRACTICE-B")["entity_type"] == "Partnership"


def test_the_stored_value_is_the_plain_word_not_the_enum_member(world):
    db, _ = world
    _patch(entity_type=EntityType.PRIVATE_LIMITED)
    stored = _stored(db, PRACTICE)["entity_type"]
    assert stored == "Private Limited" and type(stored) is str


def test_the_old_and_the_new_form_reach_the_audit_log(world):
    _, events = world
    _patch(entity_type="Proprietorship")
    assert len(events) == 1
    args, kwargs = events[0]
    assert args[:4] == (FIRM, "client", PRACTICE, "update")
    assert kwargs["old_data"]["entity_type"] == "Partnership"
    assert kwargs["new_data"] == {"entity_type": "Proprietorship"}


def test_an_update_that_names_no_form_leaves_the_form_alone(world):
    db, _ = world
    _stored(db, PRACTICE)["entity_type"] = "Trust"
    res = _patch(state="Karnataka")
    assert res["success"] is True and "entity_type" not in res["data"]["fields"]
    assert _stored(db, PRACTICE)["entity_type"] == "Trust"


def test_the_form_alone_is_a_valid_update_and_derives_no_state_code(world):
    db, _ = world
    _stored(db, PRACTICE)["state_code"] = "29"
    res = _patch(entity_type="Society")
    assert res["success"] is True
    assert _stored(db, PRACTICE)["state_code"] == "29"


def test_an_update_with_nothing_in_it_is_still_refused(world):
    res = _patch()
    assert res["success"] is False and "No identity fields" in res["error"]


@pytest.mark.parametrize("word", ["Sole Trader", "partnership", "llp", "Company", "", "Pvt Ltd"])
def test_a_form_the_model_does_not_know_is_refused_before_anything_is_written(world, word):
    db, events = world
    with pytest.raises(ValidationError):
        PracticeIdentityUpdate(entity_type=word)
    assert _stored(db, PRACTICE)["entity_type"] == "Partnership" and not events


# ── the screen ──────────────────────────────────────────────────────────────

def _page() -> str:
    return (WEB / "app" / "practice" / "page.tsx").read_text(encoding="utf-8")


def test_the_screen_offers_the_servers_list_and_holds_no_list_of_its_own():
    src = _page()
    assert "entity_types" in src and "entityTypes.map" in src
    for word in ("Proprietorship", "Private Limited", "Public Limited", '"LLP"', '"HUF"'):
        assert word not in src, f"the practice screen spells {word!r} itself; the list is the server's"


def test_the_screen_names_the_default_the_server_really_records():
    src = re.sub(r"\s+", " ", _page())
    assert ics.DEFAULT_INTERNAL_ENTITY_TYPE == "Partnership"
    assert f"A practice is first recorded as a {ics.DEFAULT_INTERNAL_ENTITY_TYPE}" in src


def test_the_screen_leaves_the_control_out_when_the_server_sent_no_list():
    src = _page()
    assert "entityTypes.length > 0" in src, "the select must wait for the list"
    assert "identity?.entity_type !== undefined" in src, "an absent value is not shown as 'Not recorded'"


# ── sign-up ─────────────────────────────────────────────────────────────────

def _firm(**extra):
    import routers.onboarding as onboarding
    return onboarding.FirmCreate(firm_name="Mehta & Co", firm_email="mehta@mehta-and-co.in", partner_name="A Mehta", **extra)


@pytest.mark.parametrize("word", ["Sole Trader", "partnership", "Company", "Pvt Ltd"])
def test_sign_up_refuses_a_legal_form_the_database_would_refuse(word):
    with pytest.raises(ValidationError) as refused:
        _firm(entity_type=word)
    # Refused for the form and for nothing else: a request that fails on its email address would pass this vacuously.
    assert [e["loc"] for e in refused.value.errors()] == [("entity_type",)]


def _sign_up(monkeypatch, **extra):
    import routers.onboarding as onboarding
    import services.coa_seed_service as coa
    db = FakeDB()
    monkeypatch.setattr(onboarding, "get_service_supabase", lambda: db)
    monkeypatch.setattr(coa, "seed_firm_coa", lambda *a, **k: None)
    seen: dict = {}
    monkeypatch.setattr(ics, "provision", lambda *a, **k: seen.update(args=a, kwargs=k) or "PRACTICE-NEW")
    res = onboarding.create_firm(_firm(pan="AAAPL1234C", **extra), jwt_user={"auth_user_id": "auth-new"})
    return res, seen


def test_the_form_chosen_at_sign_up_is_the_form_the_practice_client_is_created_with(monkeypatch):
    res, seen = _sign_up(monkeypatch, entity_type="LLP")
    assert res["success"] is True
    assert seen["kwargs"]["entity_type"] == "LLP" and type(seen["kwargs"]["entity_type"]) is str


def test_a_sign_up_that_names_no_form_creates_the_practice_as_the_default(monkeypatch):
    _, seen = _sign_up(monkeypatch)
    assert seen["kwargs"]["entity_type"] == ics.DEFAULT_INTERNAL_ENTITY_TYPE
