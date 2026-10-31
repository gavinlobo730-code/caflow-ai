"""A statutory deposit recorded as filed can be reopened, with a written reason, and nothing else can (POST-A-267, item 3).

WHAT WAS WRONG
    The compliance calendar let a Filed obligation go to Completed and a Completed one go nowhere (`VALID_TRANSITIONS`). Every
    closer built for POST-A-267 (the TDS deposit, advance tax, ESI) closes an obligation from a payment record a person typed, so
    a wrong amount, a wrong month or a wrong date left the calendar saying a deposit was made that was not, with no way to take
    it back from any screen. The product's own retraction note for an ESI entry had to say "this product cannot reopen a filed
    obligation yet".

WHAT THIS HOLDS
    * a Filed or Completed deposit obligation goes back to Ready To File, its filing date, acknowledgement number and completion
      time are cleared, and the reason is on the row's notes and in the audit log;
    * the reason is required (empty, blank and over-long are refused in words) and an obligation that is not filed has nothing to
      reopen;
    * only the statutory deposits are reopenable. Every other obligation the generators emit (a GST return, an ITR, a TDS
      statement, an MCA filing, a GST payment challan, a tax audit) is refused in words and left exactly as it was, because
      reopening only the calendar line would leave a return's record disagreeing, and a GSTR-3B's filing record is what locks the
      period. The refusal is derived from what the generators really emit, not from names typed here;
    * the door is `compliance.approve` (Manager and above), a step above marking filed: an Executive and a Reviewer are refused,
      a per-person grant is honoured;
    * a reopened obligation can be recorded as filed again, with a new date;
    * a record of another firm is a 404;
    * the browser is told which types are reopenable by the server and holds no list of its own;
    * the repository can write a NULL only into the three columns a filing sets.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
from domain import compliance_record_service as crs
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories import compliance_records_repository as repo_module
from repositories.compliance_records_repository import compliance_records_repo
from services import compliance_obligation_service as obligations
from tests.e2e_harness import FakeDB

def _user(role="Partner", **extra):
    return {"id": "u1", "firm_id": "F1", "role": role, "email": f"{role.lower()}@f1.test",
            "auth_user_id": f"auth-{role.lower()}", **extra}


@pytest.fixture
def world(monkeypatch):
    import routers.compliance_ops as ops
    import services.audit_service as au
    import services.timeline_service as ts
    MOCK_COMPLIANCE_RECORDS.clear()
    db = FakeDB()
    db.seed("firms", {"id": "F1", "name": "F1", "locked_financial_years": []})
    monkeypatch.setattr(crs, "_filing_db", lambda: db)
    audited: list = []
    timeline: list = []
    monkeypatch.setattr(au, "log_event", lambda *a, **k: audited.append((a, k)))
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: timeline.append((a, k)))
    app = FastAPI()
    app.include_router(ops.router)
    state = {"user": _user()}
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    yield TestClient(app, raise_server_exceptions=False), state, audited, timeline
    MOCK_COMPLIANCE_RECORDS.clear()


def _obl(obligation_type="ESI_DEPOSIT", status="Filed", start="2026-06-01", end="2026-06-30", firm="F1", **extra):
    return compliance_records_repo.create({
        "firm_id": firm, "client_id": "C1", "compliance_type": "Payroll", "obligation_type": obligation_type,
        "period_label": f"ESI contribution {start}", "period_start": start, "period_end": end, "due_date": "2026-07-15",
        "status": status, "filed_date": "2026-07-10" if status in ("Filed", "Completed") else None,
        "acknowledgement_no": "CHALLAN-1" if status in ("Filed", "Completed") else None,
        "completed_at": "2026-07-11T10:00:00+05:30" if status == "Completed" else None, **extra})


def _reopen(client, rec, reason="Entered against the wrong month"):
    return client.post(f"/api/compliance/obligations/{rec['id']}/reopen", json={"reason": reason})


def _row(rec):
    return compliance_records_repo.find_by_id(rec["id"])


# ── the repair ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("otype", sorted(crs.REOPENABLE_OBLIGATION_TYPES))
def test_a_filed_deposit_goes_back_to_ready_to_file_and_forgets_its_filing(world, otype):
    client, _state, _audited, _timeline = world
    rec = _obl(otype)

    r = _reopen(client, rec)

    assert r.status_code == 200, r.text
    row = _row(rec)
    assert row["status"] == "Ready To File"
    assert row["filed_date"] is None and row["acknowledgement_no"] is None and row["completed_at"] is None
    assert r.json()["data"]["obligation"]["status"] == "Ready To File"


def test_a_completed_deposit_reopens_too(world):
    client, _state, _audited, _timeline = world
    rec = _obl(status="Completed")

    assert _reopen(client, rec).status_code == 200
    row = _row(rec)
    assert row["status"] == "Ready To File" and row["completed_at"] is None


def test_the_reason_is_kept_on_the_row_and_in_the_audit_log_and_the_timeline(world):
    client, _state, audited, timeline = world
    rec = _obl(notes="Chased the employer twice")

    _reopen(client, rec, reason="  Entered against the wrong month  ")

    notes = _row(rec)["notes"]
    assert notes.startswith("Chased the employer twice\n") and "Entered against the wrong month" in notes
    assert "partner@f1.test" in notes
    (args, kwargs), = audited
    assert args[1:4] == ("compliance_record", rec["id"], "reopened")
    assert kwargs["actor_id"] == "auth-partner"                      # the AUTH id, the audit log's flavour
    assert kwargs["old_data"]["status"] == "Filed" and kwargs["old_data"]["filed_date"] == "2026-07-10"
    assert kwargs["new_data"] == {"status": "Ready To File", "reason": "Entered against the wrong month"}
    assert timeline and timeline[0][0][2] == "Compliance reopened"


# ── what is refused ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
def test_a_reopen_without_a_reason_is_refused_in_words_and_changes_nothing(world, reason):
    client, _state, audited, _timeline = world
    rec = _obl()

    r = _reopen(client, rec, reason=reason)

    assert r.status_code == 422 and "Say why" in r.json()["detail"]
    assert _row(rec)["status"] == "Filed" and _row(rec)["filed_date"] == "2026-07-10" and not audited


def test_an_over_long_reason_is_refused(world):
    client, _state, _audited, _timeline = world
    rec = _obl()
    r = _reopen(client, rec, reason="x" * (crs.MAX_REOPEN_REASON_CHARS + 1))
    assert r.status_code == 422 and "too long" in r.json()["detail"]
    assert _row(rec)["status"] == "Filed"


@pytest.mark.parametrize("status", ["Not Started", "In Progress", "Ready To File", "Overdue"])
def test_an_obligation_that_is_not_filed_has_nothing_to_reopen(world, status):
    client, _state, audited, _timeline = world
    rec = _obl(status=status)

    r = _reopen(client, rec)

    assert r.status_code == 422 and "not filed" in r.json()["detail"] and status in r.json()["detail"]
    assert _row(rec)["status"] == status and not audited


def _emitted_types() -> set:
    """Every obligation type the generators emit, read off their own output for a client that has everything."""
    out = {s["obligation_type"] for s in obligations._payroll_obligations("2026-27")}
    out |= {s["obligation_type"] for s in obligations._tds_obligations("2026-27", True)}
    out |= {s["obligation_type"] for s in obligations._advance_tax_obligations("2026-27")}
    out |= {s["obligation_type"] for s in obligations._gst_obligations("2026-27", "monthly")} if _gst_takes_two() else set()
    out |= {s["obligation_type"] for s in obligations._roc_obligations("2026-27")}
    return out


def _gst_takes_two() -> bool:
    import inspect
    return len(inspect.signature(obligations._gst_obligations).parameters) >= 2


def test_the_generators_emit_the_five_deposits_and_a_good_many_other_types():
    emitted = _emitted_types()
    assert crs.REOPENABLE_OBLIGATION_TYPES <= emitted
    assert len(emitted - crs.REOPENABLE_OBLIGATION_TYPES) >= 8, emitted     # a vacuous derivation would prove nothing below


def test_every_other_obligation_type_the_generators_emit_is_refused_and_left_as_it_was(world):
    """Not a list typed here: the types are read off the generators, so a type added later is refused until it is decided on."""
    client, _state, audited, _timeline = world
    refused = sorted(_emitted_types() - crs.REOPENABLE_OBLIGATION_TYPES)
    assert refused
    for otype in refused:
        rec = _obl(otype, compliance_type="Other")
        r = _reopen(client, rec)
        assert r.status_code == 422 and "cannot be reopened from here" in r.json()["detail"], (otype, r.text)
        assert "Validation error on" not in r.json()["detail"], r.text           # the sentence as written, no field prefix
        row = _row(rec)
        assert row["status"] == "Filed" and row["filed_date"] == "2026-07-10" and row["acknowledgement_no"] == "CHALLAN-1", otype
    assert not audited


def test_a_record_with_no_obligation_type_is_not_reopenable(world):
    client, _state, _audited, _timeline = world
    rec = _obl(obligation_type=None)
    r = _reopen(client, rec)
    assert r.status_code == 422 and _row(rec)["status"] == "Filed"


def test_another_firms_record_is_a_404(world):
    client, _state, _audited, _timeline = world
    rec = _obl(firm="F2")
    assert _reopen(client, rec).status_code == 404
    assert _row(rec)["status"] == "Filed"


# ── who may ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role,allowed", [("Partner", True), ("Manager", True), ("Executive", False), ("Reviewer", False)])
def test_the_door_is_compliance_approve(world, role, allowed):
    client, state, _audited, _timeline = world
    state["user"] = _user(role)
    rec = _obl()

    r = _reopen(client, rec)

    assert (r.status_code == 200) is allowed, r.text
    assert (_row(rec)["status"] == "Ready To File") is allowed
    if not allowed:
        assert r.status_code == 403


def test_a_per_person_grant_reaches_the_door_and_a_per_person_block_closes_it(world):
    client, state, _audited, _timeline = world
    state["user"] = _user("Executive", permission_overrides={"compliance:approve": True})
    assert _reopen(client, _obl()).status_code == 200
    state["user"] = _user("Manager", permission_overrides={"compliance:approve": False})
    assert _reopen(client, _obl(start="2026-07-01", end="2026-07-31")).status_code == 403


# ── it can be filed again ────────────────────────────────────────────────────

def test_a_reopened_obligation_can_be_recorded_as_filed_again_with_a_new_date(world):
    client, _state, _audited, _timeline = world
    rec = _obl()
    _reopen(client, rec)

    r = client.post(f"/api/compliance/obligations/{rec['id']}/mark-filed",
                    json={"filed_date": "2026-07-12", "acknowledgement_no": "CHALLAN-2"})

    assert r.status_code == 200, r.text
    row = _row(rec)
    assert row["status"] == "Filed" and row["filed_date"] == "2026-07-12" and row["acknowledgement_no"] == "CHALLAN-2"


def test_reopening_twice_is_refused_the_second_time(world):
    client, _state, _audited, _timeline = world
    rec = _obl()
    assert _reopen(client, rec).status_code == 200
    assert _reopen(client, rec).status_code == 422


# ── the list the screen is given ─────────────────────────────────────────────

def test_the_server_serves_the_reopenable_types_and_the_reason_limit(world):
    client, state, _audited, _timeline = world
    state["user"] = _user("Executive")                     # reading the list is read access, not approve
    data = client.get("/api/compliance/reopenable-types").json()["data"]
    assert data["obligation_types"] == sorted(crs.REOPENABLE_OBLIGATION_TYPES)
    assert data["max_reason_chars"] == crs.MAX_REOPEN_REASON_CHARS


def test_every_reopenable_type_is_a_type_the_generator_really_emits():
    """A typo in the set would make a deposit quietly unreopenable. The types are read off the generator's own output."""
    emitted = {s["obligation_type"] for s in obligations._payroll_obligations("2026-27")}
    emitted |= {s["obligation_type"] for s in obligations._tds_obligations("2026-27", True)}
    emitted |= {s["obligation_type"] for s in obligations._advance_tax_obligations("2026-27")}
    assert crs.REOPENABLE_OBLIGATION_TYPES <= emitted, crs.REOPENABLE_OBLIGATION_TYPES - emitted


def test_no_type_with_a_filing_record_is_in_the_set():
    """The GST returns lock a period through `filings`; the returns and filings below have records of their own."""
    from services.gst_filing_record_service import FILING_TYPE_FOR_RETURN
    assert not (crs.REOPENABLE_OBLIGATION_TYPES & set(FILING_TYPE_FOR_RETURN))
    assert not (crs.REOPENABLE_OBLIGATION_TYPES & {"ITR", "TDS24Q", "TDS26Q", "TDS27Q", "TDS27EQ", "MCA_AOC4", "MCA_MGT7", "MCA_ADT1"})


# ── what the reopen says it did not touch ────────────────────────────────────

def test_every_reopenable_type_says_what_becomes_of_the_record_that_closed_it():
    assert set(crs.REOPEN_AFTERMATH) == set(crs.REOPENABLE_OBLIGATION_TYPES), "a type needs its own sentence before it is reopenable"


@pytest.mark.parametrize("otype,expected", [
    ("ESI_DEPOSIT", "retract it on the payroll hand-off"),
    ("TDS_NON_SALARY_DEPOSIT", "retract it on the Challans tab first"),
    ("ADVANCE_TAX", "closes the instalment again"),
    ("EPF_DEPOSIT", "Nothing closes it again by itself"),
])
def test_the_answer_says_what_applies_to_this_deposit(world, otype, expected):
    client, _state, _audited, _timeline = world
    message = _reopen(client, _obl(otype)).json()["data"]["message"]
    assert message.startswith("Reopened.") and expected in message and "Ready To File" in message


def test_the_escalation_bookkeeping_is_cleared_so_an_overdue_notice_is_not_held_back(world):
    client, _state, _audited, _timeline = world
    rec = _obl(last_escalated_tier="overdue", last_escalated_on="2026-07-02")
    assert _reopen(client, rec).status_code == 200
    row = _row(rec)
    assert row["last_escalated_tier"] is None and row["last_escalated_on"] is None


# ── a write acts only on a row still in the state it saw ─────────────────────

def test_a_row_somebody_changed_between_the_read_and_the_write_is_not_overwritten(world, monkeypatch):
    """Manager B read the obligation as filed; before B's write, A reopened it and an Executive recorded it as filed again with the
    corrected date. B's stale write must not blank that new filing."""
    client, _state, audited, _timeline = world
    rec = _obl()
    real = compliance_records_repo.update_clearing

    def somebody_else_first(id, firm_id, data, clear, only_if_status=None):
        row = _row(rec)
        row.update(status="Ready To File", filed_date=None, acknowledgement_no=None)          # A's reopen
        row.update(status="Filed", filed_date="2026-07-12", acknowledgement_no="CHALLAN-2")   # the corrected filing
        row["status"] = "Ready To File"                                                       # ... and a third change in flight
        return real(id, firm_id, data, clear, only_if_status=only_if_status)

    monkeypatch.setattr(compliance_records_repo, "update_clearing", somebody_else_first)

    r = _reopen(client, rec)

    assert r.status_code == 422 and "no longer recorded as filed" in r.json()["detail"], r.text
    row = _row(rec)
    assert row["status"] == "Ready To File" and row["filed_date"] == "2026-07-12" and row["acknowledgement_no"] == "CHALLAN-2"
    assert "Reopened on" not in (row.get("notes") or "")
    assert not audited


# ── the repository ───────────────────────────────────────────────────────────

def test_the_repository_writes_a_null_only_into_the_columns_a_filing_sets():
    with pytest.raises(ValueError):
        compliance_records_repo.update_clearing("x", "F1", {"status": "Ready To File"}, clear=("due_date",))


def test_against_the_database_the_update_sends_explicit_nulls_and_drops_other_nones(monkeypatch):
    sent: list = []
    seen: list = []

    class _Q:
        def update(self, payload):
            sent.append(payload)
            return self

        def eq(self, column, value):
            seen.append(("eq", column, value))
            return self

        def in_(self, column, values):
            seen.append(("in", column, list(values)))
            return self

        def execute(self):
            class _R:
                data = [{"id": "r1"}]
            return _R()

    class _DB:
        def table(self, _name):
            return _Q()

    monkeypatch.setattr(repo_module, "_USE_MOCK", False)
    monkeypatch.setattr(repo_module, "_get_db", lambda: _DB())

    compliance_records_repo.update_clearing("r1", "F1", {"status": "Ready To File", "notes": None},
                                            clear=compliance_records_repo.CLEARABLE, only_if_status=("Filed", "Completed"))

    payload, = sent
    assert payload["status"] == "Ready To File"
    assert "notes" not in payload                                # an ordinary None is still dropped
    assert all(k in payload and payload[k] is None for k in ("filed_date", "acknowledgement_no", "completed_at"))
    # The write is confined to the firm's row and to a row still in the state the caller saw.
    assert ("eq", "id", "r1") in seen and ("eq", "firm_id", "F1") in seen
    assert ("in", "status", ["Filed", "Completed"]) in seen
    assert all(k in payload and payload[k] is None for k in ("last_escalated_tier", "last_escalated_on"))


def test_against_the_mock_store_the_update_refuses_another_firm_and_a_changed_status(world):
    rec = _obl()
    assert compliance_records_repo.update_clearing(rec["id"], "F2", {"status": "Ready To File"}, clear=("filed_date",)) is None
    assert _row(rec)["status"] == "Filed" and _row(rec)["filed_date"] == "2026-07-10"
    assert compliance_records_repo.update_clearing(rec["id"], "F1", {"status": "Ready To File"}, clear=("filed_date",),
                                                   only_if_status=("In Progress",)) is None
    assert _row(rec)["status"] == "Filed"
    assert compliance_records_repo.update_clearing(rec["id"], "F1", {"status": "Ready To File"}, clear=("filed_date",),
                                                   only_if_status=("Filed",))["status"] == "Ready To File"
