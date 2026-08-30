"""Regenerating notes must not destroy a note a partner locked.

WHAT WAS WRONG
    generate_notes deleted every note on the engagement and re-inserted the
    freshly generated set:

        db.table("year_end_notes").delete().eq("engagement_id", eid).execute()

    year_end_notes carries is_locked, and the UPDATE path refuses to modify a
    locked note ("Note is locked and cannot be modified"). So a partner would
    review the related-party wording, lock it, and then anyone with
    year_end:write clicking "Generate Notes" replaced it with the empty
    auto-generated placeholder — no warning, no record of what it had said,
    and no way back.

    A lock that holds on one path and not the other is not a lock. Nothing
    statutory turns on this; it is the module's own promise, and losing a
    partner's reviewed disclosure wording is real work destroyed.
"""
from __future__ import annotations

import pytest

import routers.year_end_notes as m
import routers.year_end as ye
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "F1"
ENG = "eng-locked-notes"

PARTNER = {"role": "Partner", "firm_id": FIRM, "auth_user_id": "u1",
           "email": "p@firm.in", "id": "u1"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [m])
    ye._MOCK_ENGAGEMENTS[ENG] = {
        "id": ENG, "firm_id": FIRM, "client_id": "C1",
        "financial_year": "2025-26", "status": "draft",
    }
    monkeypatch.setattr(m, "_assert_engagement_scope",
                        lambda user, eid: ye._MOCK_ENGAGEMENTS[eid])
    return d


def _seed_note(db, note_type: str, *, locked: bool, content: str):
    db.seed("year_end_notes", {
        "id": f"note-{note_type}", "engagement_id": ENG, "firm_id": FIRM,
        "note_type": note_type, "sequence_no": 1, "title": note_type,
        "content": content, "note_data": {}, "is_locked": locked,
        "is_auto_generated": False,
    })


def _rows(db, note_type: str):
    return [r for r in db.rows("year_end_notes")
            if r.get("note_type") == note_type]


def test_a_locked_note_survives_regeneration(db):
    _seed_note(db, "related_party", locked=True,
               content="Reviewed by the partner. Do not overwrite.")
    m.generate_notes(ENG, PARTNER)

    survivors = _rows(db, "related_party")
    assert len(survivors) == 1, "the locked note was deleted and re-created"
    assert survivors[0]["content"] == "Reviewed by the partner. Do not overwrite."
    assert survivors[0]["is_locked"] is True


def test_an_unlocked_note_is_still_regenerated(db):
    """The other half — the feature has to keep working. A lock that froze
    everything would be as wrong as a lock that froze nothing."""
    _seed_note(db, "fixed_assets", locked=False, content="stale draft wording")
    m.generate_notes(ENG, PARTNER)

    rows = _rows(db, "fixed_assets")
    assert len(rows) == 1
    assert rows[0]["content"] != "stale draft wording"


def test_regeneration_does_not_duplicate_a_locked_note(db):
    """The locked note is kept AND not re-inserted, so the engagement ends
    with exactly one note of that type rather than two contradicting ones."""
    _seed_note(db, "related_party", locked=True, content="partner wording")
    m.generate_notes(ENG, PARTNER)
    m.generate_notes(ENG, PARTNER)

    assert len(_rows(db, "related_party")) == 1


def test_the_response_reports_only_what_it_wrote(db):
    _seed_note(db, "related_party", locked=True, content="partner wording")
    resp = m.generate_notes(ENG, PARTNER)

    assert resp["success"] is True
    returned = {n["note_type"] for n in resp["data"]}
    assert "related_party" not in returned, (
        "a locked note was reported as regenerated when it was preserved"
    )
