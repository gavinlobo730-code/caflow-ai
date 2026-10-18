"""A CA can correct what the model read from a notice before approving it (POST-A-053).

WHAT WAS WRONG
    A staged notice offered `POST /notices/{id}/approve` and a status change, and nothing between. Approval creates the response task
    with the due date on the reading and tells the partners, so a reading the model got wrong (a day, a digit, the wrong kind of
    notice) could only be rejected and extracted again, or approved wrong.

WHAT IS HELD
    * `PATCH /notices/{id}/reading` changes only what was sent, through the rule that checks the model's reading: the notice-type
      vocabulary, ISO dates, the length limits, and `validate_notice_dates` on the MERGED pair; a typo is REFUSED with a sentence
      (422), never demoted to `other` or to "unread"; an empty string clears a reference or a date; the authority cannot be emptied;
      a field this door does not correct is refused; a correction that changes nothing is refused;
    * the model's own reading is kept: `extracted_data` is not overwritten and each correction is appended to
      `extracted_data["corrections"]` with when, by whom and from what to what; the audit log records it;
    * it creates no task, timeline event or alert (approval still does, from the corrected reading);
    * an approved notice is refused (409), and a correction that races an approval loses cleanly (the write is conditional on
      `ca_approved = false`); an unknown notice or one outside the caller's clients is a 404;
    * the door asks compliance:write; the browser's list of notice types is the server's.
"""
from __future__ import annotations

import copy
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.document_intelligence_v2 as v2
from core.auth import get_current_user
from domain.ai import extraction_schemas as X
from tests.test_a_notice_reading_stages_and_a_ca_approves import CLIENT, PARTNER, READING, FakeDB

API = Path(__file__).resolve().parents[1]
WEB = API.parent / "web"
TODAY = date(2026, 10, 1)
CURRENT = {**READING, "notice_type": "gst_scrutiny"}


# ── the pure rule ───────────────────────────────────────────────────────────────────────────────────

def _correct(patch, current=None):
    return X.correct_notice(current or CURRENT, patch, today=TODAY)


def test_a_corrected_date_changes_only_that_field_and_records_from_and_to():
    fields, changes = _correct({"response_due_date": "2026-10-20"})
    assert fields == {"response_due_date": "2026-10-20"}
    assert changes == {"response_due_date": {"from": "2026-10-15", "to": "2026-10-20"}}


def test_several_fields_and_a_type_written_the_way_a_person_would_type_it():
    fields, changes = _correct({"notice_type": "Income Tax Notice", "authority": "  Income Tax Department ", "reference_no": " 143(2)/9 "})
    assert fields == {"notice_type": "income_tax_notice", "authority": "Income Tax Department", "reference_no": "143(2)/9"}
    assert set(changes) == {"notice_type", "authority", "reference_no"}


@pytest.mark.parametrize("value", ["", "   ", None])
def test_an_empty_value_clears_a_reference_or_a_date(value):
    fields, _ = _correct({"reference_no": value, "response_due_date": value})
    assert fields == {"reference_no": None, "response_due_date": None}


@pytest.mark.parametrize("patch,needle", [
    ({"notice_type": "scrutiny"}, "must be one of"),
    ({"response_due_date": "20-10-2026"}, "must be written YYYY-MM-DD"),
    ({"issue_date": "2026-13-45"}, "must be written YYYY-MM-DD"),
    ({"authority": "   "}, "cannot be left empty"),
    ({"authority": "x" * 201}, "longer than 200"),
    ({"reference_no": "x" * 101}, "longer than 100"),
    ({"description": "x" * 1001}, "longer than 1000"),
    ({"status": "closed"}, "cannot be corrected"),
    ({"response_due_date": "2026-10-15"}, "Nothing was changed"),
    ({"authority": "GSTN", "reference_no": " ASMT-10/42 "}, "Nothing was changed"),
])
def test_a_typo_or_a_no_op_is_refused_with_a_sentence_and_422(patch, needle):
    with pytest.raises(X.ExtractionRefused) as refused:
        _correct(patch)
    assert needle in refused.value.sentence and refused.value.http_status == 422


@pytest.mark.parametrize("patch", [
    {"response_due_date": "2026-09-01"},      # before the issue date held (2026-09-20)
    {"issue_date": "2026-10-30"},             # after the response date held (2026-10-15)
    {"issue_date": "2030-01-01"},             # in the future
    {"response_due_date": "2036-01-01"},      # more than two years out
])
def test_dates_are_judged_as_a_pair_against_what_is_held_and_the_wording_speaks_to_a_person(patch):
    with pytest.raises(X.ExtractionRefused) as refused:
        _correct(patch)
    assert "correction was refused" in refused.value.sentence and "The correction was not saved" in refused.value.sentence
    assert "pasted" not in refused.value.sentence


def test_both_dates_may_move_together_past_what_either_alone_could_be():
    fields, _ = _correct({"issue_date": "2026-10-01", "response_due_date": "2026-11-15"})
    assert fields == {"issue_date": "2026-10-01", "response_due_date": "2026-11-15"}


def test_the_extraction_wording_is_unchanged():
    with pytest.raises(X.ExtractionRefused) as refused:
        X.validate_notice_dates(date(2026, 9, 20), date(2026, 9, 1), TODAY)
    assert "reading was refused" in refused.value.sentence and "Check the text you pasted" in refused.value.sentence


# ── the route ───────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def env(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(v2, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    monkeypatch.setattr(v2, "_GROQ_KEY", "k")
    monkeypatch.setattr(v2.ist_clock, "ist_today", lambda: TODAY)
    audit, timeline = [], []
    monkeypatch.setattr(v2, "log_event", lambda *a, **k: audit.append((a, k)))
    monkeypatch.setattr(v2.timeline_service, "log_timeline_event", lambda **k: timeline.append(k))
    monkeypatch.setattr(v2, "_run_notice_extraction", lambda text, **kw: (copy.deepcopy(READING), None, 200))
    app = FastAPI()
    app.include_router(v2.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    client = TestClient(app, raise_server_exceptions=False)
    return type("E", (), {"db": db, "audit": audit, "timeline": timeline, "client": client})


def _stage(env):
    r = env.client.post("/api/document-intelligence-v2/notices/extract", json={"client_id": CLIENT, "document_text": "A notice."})
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


def _patch(env, notice_id, body):
    return env.client.patch(f"/api/document-intelligence-v2/notices/{notice_id}/reading", json=body)


def test_a_correction_changes_the_row_keeps_the_models_reading_and_logs_who_and_what(env):
    notice_id = _stage(env)
    r = _patch(env, notice_id, {"response_due_date": "2026-10-20", "reference_no": "ASMT-10/43"})
    assert r.status_code == 200, r.text
    (row,) = env.db.rows["government_notices"]
    assert row["response_due_date"] == "2026-10-20" and row["reference_no"] == "ASMT-10/43"
    assert row["ca_approved"] is False
    # the model's own reading is what it was, and the correction is appended beside it
    assert row["extracted_data"]["response_due_date"] == "2026-10-15" and row["extracted_data"]["reference_no"] == "ASMT-10/42"
    [correction] = row["extracted_data"]["corrections"]
    assert correction["by"] == PARTNER["id"] and correction["at"]
    assert correction["changes"] == {"response_due_date": {"from": "2026-10-15", "to": "2026-10-20"},
                                     "reference_no": {"from": "ASMT-10/42", "to": "ASMT-10/43"}}
    assert [a[0][3] for a in env.audit] == ["create", "reading_corrected"]
    body = r.json()["data"]
    assert body["review_state"] == "pending_review" and body["response_due_date"] == "2026-10-20"


def test_a_second_correction_is_appended_not_substituted(env):
    notice_id = _stage(env)
    assert _patch(env, notice_id, {"response_due_date": "2026-10-20"}).status_code == 200
    assert _patch(env, notice_id, {"response_due_date": "2026-10-22"}).status_code == 200
    (row,) = env.db.rows["government_notices"]
    assert [c["changes"]["response_due_date"]["to"] for c in row["extracted_data"]["corrections"]] == ["2026-10-20", "2026-10-22"]
    assert row["extracted_data"]["corrections"][1]["changes"]["response_due_date"]["from"] == "2026-10-20"


def test_a_correction_creates_no_task_no_timeline_event_and_no_alert(env):
    notice_id = _stage(env)
    _patch(env, notice_id, {"authority": "Income Tax Department"})
    assert env.db.rows["tasks"] == [] and env.db.rows["notifications"] == [] and env.timeline == []


def test_approval_afterwards_makes_the_task_from_the_corrected_date(env):
    notice_id = _stage(env)
    _patch(env, notice_id, {"response_due_date": "2026-10-20"})
    assert env.client.post(f"/api/document-intelligence-v2/notices/{notice_id}/approve").status_code == 200
    (task,) = env.db.rows["tasks"]
    assert task["due_date"] == "2026-10-20"


def test_a_refused_correction_stores_nothing(env):
    notice_id = _stage(env)
    r = _patch(env, notice_id, {"response_due_date": "2026-09-01"})
    assert r.status_code == 422 and r.json()["success"] is False and "correction was refused" in r.json()["error"]
    (row,) = env.db.rows["government_notices"]
    assert row["response_due_date"] == "2026-10-15" and "corrections" not in row["extracted_data"]
    assert [a[0][3] for a in env.audit] == ["create"]


def test_an_approved_notice_cannot_be_corrected(env):
    notice_id = _stage(env)
    env.client.post(f"/api/document-intelligence-v2/notices/{notice_id}/approve")
    r = _patch(env, notice_id, {"response_due_date": "2026-10-20"})
    assert r.status_code == 409 and "Correct the task instead" in r.json()["error"]
    assert env.db.rows["government_notices"][0]["response_due_date"] == "2026-10-15"


def test_a_correction_that_races_an_approval_loses_cleanly(env, monkeypatch):
    notice_id = _stage(env)
    stale = copy.deepcopy(env.db.rows["government_notices"][0])          # what the handler read: unapproved
    env.db.rows["government_notices"][0]["ca_approved"] = True            # somebody approved in the meantime
    monkeypatch.setattr(v2, "_assert_notice_scope", lambda user, nid: stale)
    r = _patch(env, notice_id, {"response_due_date": "2026-10-20"})
    assert r.status_code == 409 and "approved while you were correcting it" in r.json()["error"]
    assert env.db.rows["government_notices"][0]["response_due_date"] == "2026-10-15"
    assert [a[0][3] for a in env.audit] == ["create"], "no correction was logged for a write that did not happen"


def test_an_unknown_notice_and_one_outside_the_callers_clients_are_the_same_404(env, monkeypatch):
    assert _patch(env, "no-such-id", {"authority": "X"}).status_code == 404
    notice_id = _stage(env)
    monkeypatch.setattr(v2, "can_access_client", lambda user, client_id: False)
    r = _patch(env, notice_id, {"authority": "X"})
    assert r.status_code == 404 and r.json()["error"] == "Notice not found"


def test_the_door_asks_compliance_write_and_forbids_a_field_it_does_not_correct(env):
    route = next(r for r in v2.router.routes if getattr(r, "path", "").endswith("/notices/{notice_id}/reading"))
    names = [getattr(getattr(d, "call", None), "__name__", "") for d in route.dependant.dependencies]
    assert "rbac_compliance_write" in names
    notice_id = _stage(env)
    r = _patch(env, notice_id, {"status": "closed"})
    assert r.status_code == 422


def test_the_browsers_notice_type_list_is_the_servers_in_order():
    src = (WEB / "lib/compliance/noticeReading.ts").read_text(encoding="utf-8")
    block = src[src.index("export const NOTICE_TYPE_OPTIONS"):src.index("];", src.index("export const NOTICE_TYPE_OPTIONS"))]
    assert tuple(re.findall(r'value: "(\w+)"', block)) == X.NOTICE_TYPES
