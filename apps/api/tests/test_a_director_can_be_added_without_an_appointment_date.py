"""
A director can be added without an appointment date, and a refusal says why.

WHAT WAS WRONG
    `mca_directors.date_of_appointment` is a NULLABLE DATE (migration 038), but
    CreateDirectorRequest made it a required `str`. The Add Director form sends
    "" for an empty box; pydantic accepted it, Postgres refused it (22007,
    invalid date), and the handler swallowed that into "Unable to complete MCA
    operation. Please try again." — so leaving an optional field blank made the
    director impossible to add, retrying could never help, and a DIN already on
    file (UNIQUE (client_id, din)) read exactly the same.

WHAT IS ASSERTED — by calling the model and the handler
    * "" is no date; a real date parses; a DD/MM/YYYY one is refused naming the
      field, before anything reaches the database;
    * the insert carries ISO text or NULL — never a Python date, which the
      PostgREST JSON body could not carry;
    * a repeated DIN says so; another refusal the database names is said as
      that sentence rather than "please try again".
"""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

import core.supabase_client as sc
import routers.mca_workspace as mw
from routers.mca_workspace import CreateDirectorRequest, create_director

PARTNER = {"firm_id": "F-mca", "id": "u1", "auth_user_id": "a1", "role": "Partner"}


def _req(**over) -> CreateDirectorRequest:
    base = {"client_id": "C-mca", "din": "01234567", "name": "Asha Rao",
            "designation": "Director", "date_of_appointment": ""}
    base.update(over)
    return CreateDirectorRequest(**base)


@pytest.fixture(autouse=True)
def _clean_store():
    mw._MOCK_DIRECTORS.clear()
    yield
    mw._MOCK_DIRECTORS.clear()


# ── The model ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("blank", ["", "   "])
def test_an_empty_box_is_no_date(blank):
    assert _req(date_of_appointment=blank).date_of_appointment is None


def test_leaving_the_field_out_is_no_date_too():
    body = {"client_id": "C-mca", "din": "01234567", "name": "Asha Rao",
            "designation": "Director"}
    assert CreateDirectorRequest(**body).date_of_appointment is None


def test_a_real_date_parses():
    assert _req(date_of_appointment="2024-04-01").date_of_appointment == date(2024, 4, 1)


@pytest.mark.parametrize("bad", ["01/04/2024", "2024-02-30", "yesterday"])
def test_a_malformed_date_is_refused_naming_the_field(bad):
    with pytest.raises(ValidationError) as e:
        _req(date_of_appointment=bad)
    assert "date_of_appointment" in str(e.value)


# ── The handler ─────────────────────────────────────────────────────────────

def test_a_director_with_no_appointment_date_is_added():
    res = create_director(_req(), PARTNER)
    assert res["success"] is True, res
    assert res["data"]["date_of_appointment"] is None


class _PgError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__({"code": code, "message": message})


class _DB:
    """Records the insert payload, or raises what the database would."""
    def __init__(self, error=None):
        self.error, self.inserted = error, []

    def table(self, name):
        assert name == "mca_directors"
        return self

    def insert(self, payload):
        self.inserted.append(payload)
        return self

    def execute(self):
        if self.error:
            raise self.error
        return type("R", (), {"data": list(self.inserted)})()


@pytest.fixture
def against(monkeypatch):
    def _use(db):
        monkeypatch.setattr(mw, "_USE_MOCK", False)
        monkeypatch.setattr(sc, "get_supabase", lambda: db)
        monkeypatch.setattr(mw, "log_event", lambda *_a, **_k: None)
        return db
    return _use


def test_the_insert_carries_iso_text_or_null_never_a_date_object(against):
    import json
    db = against(_DB())
    create_director(_req(date_of_appointment="2024-04-01"), PARTNER)
    create_director(_req(din="07654321"), PARTNER)
    first, second = db.inserted
    assert first["date_of_appointment"] == "2024-04-01"
    assert second["date_of_appointment"] is None
    json.dumps(db.inserted)   # what PostgREST's JSON body has to be able to do


def test_a_din_already_on_file_says_so(against):
    against(_DB(_PgError("23505", 'duplicate key value violates unique '
                                  'constraint "mca_directors_client_id_din_key"')))
    res = create_director(_req(), PARTNER)
    assert res["success"] is False
    assert res["error"] == "This DIN is already recorded for this client."


def test_another_refusal_the_database_names_is_said_rather_than_retried(against):
    against(_DB(_PgError("23514", 'new row for relation "mca_directors" violates '
                                  'check constraint "mca_directors_kyc_status_check"')))
    res = create_director(_req(kyc_status="expired"), PARTNER)
    assert res["success"] is False
    assert "try again" not in res["error"].lower()
    assert "not allowed" in res["error"]
