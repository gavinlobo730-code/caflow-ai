"""
Filing a GST return leaves a record — on the return, and in `filings`.

THE GAP THIS CLOSES
    journal_period_lock_reason (migration 266) refuses to edit a journal inside
    a period whose return has been filed. It reads `filings`. Nothing in the
    codebase had ever written a row to that table, so that half of the lock
    could never fire — a correct guard, permanently unreachable.

    The real-Postgres tests for 266 did not catch it because they seed `filings`
    themselves. They proved the SQL was right. Nothing proved anything fills the
    table. That is the same shape as testing a helper without testing its call
    site, and it is why the last test in this file asserts the written row
    against the function's actual WHERE clause rather than against a shape
    somebody typed twice.

    Separately, marking a return submitted wrote only `status`, leaving
    submitted_at, arn, ca_approved_by and ca_approved_at NULL on every return
    ever filed.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.gst_workspace as gw
from services.gst_filing_record_service import (
    FILING_TYPE_GSTR1, build_filings_row, period_bounds, record_filing,
    return_status_patch,
)
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
CLIENT = "client-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1",
        "email": "ca@f.test", "role": "Partner"}
GSTIN = "27AAAAA0000A1Z5"
PERIOD = "062026"          # June 2026


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    monkeypatch.setattr(gw, "_USE_MOCK", False)
    wire_e2e(monkeypatch, d, [gw])
    return d


def _save(db):
    return gw.save_gstr1(gw.SaveGSTR1Request(
        client_id=CLIENT, period=PERIOD, gstin=GSTIN,
        payload_json={"b2b": [{"inum": "INV-1"}]},
        summary_json={"invoices": 1},
        total_taxable_paise=10_000_00, total_igst_paise=1_800_00,
    ), current_user=USER)


def _submit(db, return_id, **kw):
    return gw.update_gstr1_status(
        return_id,
        gw.UpdateStatusRequest(status="submitted", ca_approved=True, **kw),
        current_user=USER,
    )


# ── period bounds: what the lock actually matches on ─────────────────────────

def test_period_bounds_cover_the_whole_month():
    assert period_bounds("062026") == ("2026-06-01", "2026-06-30")
    assert period_bounds("022024") == ("2024-02-01", "2024-02-29"), "leap year"
    assert period_bounds("022026") == ("2026-02-01", "2026-02-28")
    assert period_bounds("122026") == ("2026-12-01", "2026-12-31")


def test_a_malformed_period_is_refused_rather_than_guessed():
    for bad in ["62026", "132026", "002026", "abcdef", ""]:
        with pytest.raises(ValueError):
            period_bounds(bad)


# ── the return row itself ────────────────────────────────────────────────────

def test_submitting_records_when_who_and_the_acknowledgement(db):
    saved = _save(db)["data"]

    resp = _submit(db, saved["id"], arn="AA270626123456A")

    assert resp["success"] is True
    row = db.rows("gstr1_returns")[0]
    assert row["status"] == "submitted"
    assert row["submitted_at"], "nothing recorded WHEN it was filed"
    assert row["ca_approved_by"] == "u1", "nothing recorded WHO approved it"
    assert row["ca_approved_at"]
    assert row["arn"] == "AA270626123456A"


def test_validating_stamps_its_own_timestamp_and_no_approver():
    patch = return_status_patch("validated", actor_id="u1", now_iso="2026-07-11T00:00:00")

    assert patch["validated_at"] == "2026-07-11T00:00:00"
    assert "ca_approved_by" not in patch, "validation is not approval"
    assert "submitted_at" not in patch


def test_submitting_straight_from_validated_still_records_the_approver():
    """A return can skip the intermediate ca_approved step. The CA who confirms
    the submit IS the approver, and losing that because a step was skipped would
    leave the approval unattributed."""
    patch = return_status_patch("submitted", actor_id="u1", now_iso="2026-07-11T00:00:00")

    assert patch["ca_approved_by"] == "u1"
    assert patch["ca_approved_at"] == "2026-07-11T00:00:00"
    assert patch["submitted_at"] == "2026-07-11T00:00:00"


# ── the filings row ──────────────────────────────────────────────────────────

def test_submitting_writes_the_filings_row_that_did_not_exist_before(db):
    saved = _save(db)["data"]

    _submit(db, saved["id"], arn="AA270626123456A", filed_date="2026-07-11")

    filings = db.rows("filings")
    assert len(filings) == 1, "no filings row — the period lock has nothing to read"
    f = filings[0]
    assert f["client_id"] == CLIENT
    assert f["filing_type"] == FILING_TYPE_GSTR1
    assert f["period_start"] == "2026-06-01" and f["period_end"] == "2026-06-30"
    assert f["filed_date"] == "2026-07-11"
    assert f["status"] == "filed"
    assert f["acknowledgement_number"] == "AA270626123456A"


def test_a_draft_or_approved_return_files_nothing(db):
    """Only submission is filing. Approving a return in this app does not put
    anything at the portal, so it must not freeze the CA's books."""
    saved = _save(db)["data"]

    gw.update_gstr1_status(saved["id"], gw.UpdateStatusRequest(
        status="ca_approved", ca_approved=True), current_user=USER)

    assert db.rows("filings") == []


def test_recording_the_same_filing_twice_leaves_one_row(db):
    """`filings` has no unique constraint over (client, type, period), so a
    repeated submit would otherwise leave two rows claiming the same filing."""
    for _ in range(2):
        record_filing(db, firm_id=FIRM, client_id=CLIENT,
                      filing_type=FILING_TYPE_GSTR1, period=PERIOD,
                      filed_date="2026-07-11", arn="AA270626123456A")

    assert len(db.rows("filings")) == 1


def test_a_failed_filings_write_does_not_block_recording_reality(db, monkeypatch):
    """The return IS filed — the CA said so. Refusing the request because our
    bookkeeping row failed would leave them unable to record what happened."""
    saved = _save(db)["data"]
    monkeypatch.setattr(gw, "record_filing",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    resp = _submit(db, saved["id"])

    assert resp["success"] is True
    assert db.rows("gstr1_returns")[0]["status"] == "submitted"


# ── immutability ─────────────────────────────────────────────────────────────

def test_a_draft_can_be_revised_in_place(db):
    """One return per client per period — the table says so and so does the
    law. A second save is a revision, and it used to hit the UNIQUE constraint
    and surface as "Unable to complete GST operation. Please try again."."""
    first = _save(db)["data"]

    second = gw.save_gstr1(gw.SaveGSTR1Request(
        client_id=CLIENT, period=PERIOD, gstin=GSTIN,
        payload_json={"b2b": [{"inum": "INV-1"}, {"inum": "INV-2"}]},
        summary_json={"invoices": 2}, total_taxable_paise=20_000_00,
    ), current_user=USER)["data"]

    assert second["id"] == first["id"], "a revision created a second return"
    rows = db.rows("gstr1_returns")
    assert len(rows) == 1
    assert rows[0]["total_taxable_paise"] == 20_000_00


def test_a_filed_return_cannot_be_changed(db):
    """CGST §37: a return cannot be revised. And a payload that could still move
    after filing would make the exception report meaningless."""
    saved = _save(db)["data"]
    _submit(db, saved["id"])

    with pytest.raises(HTTPException) as e:
        gw.save_gstr1(gw.SaveGSTR1Request(
            client_id=CLIENT, period=PERIOD, gstin=GSTIN,
            payload_json={"b2b": []}, total_taxable_paise=0,
        ), current_user=USER)

    assert e.value.status_code == 422
    assert "amendment" in e.value.detail.lower(), "say what the CA should do instead"
    assert db.rows("gstr1_returns")[0]["total_taxable_paise"] == 10_000_00, "the filed payload moved"


# ── the wiring, against the lock's real predicate ────────────────────────────

def test_the_written_row_satisfies_what_the_period_lock_looks_for():
    """The test the 266 suite could not be: it seeds `filings` itself, so it
    verifies the SQL and never that anything fills the table.

    journal_period_lock_reason matches on

        client_id = p_client
        AND deleted_at IS NULL
        AND filed_date IS NOT NULL
        AND p_date BETWEEN period_start AND period_end

    so a row missing filed_date, or with the bounds wrong, is one the lock
    silently skips and the CA edits a filed period believing it is open.
    """
    row = build_filings_row(
        firm_id=FIRM, client_id=CLIENT, filing_type=FILING_TYPE_GSTR1,
        period=PERIOD, filed_date="2026-07-11", arn="AA270626123456A",
    )

    assert row["client_id"] == CLIENT
    assert row.get("deleted_at") is None
    assert row["filed_date"] is not None, "the lock skips rows with no filed_date"
    # Every date in June is inside the filed period; the days either side are not.
    assert row["period_start"] <= "2026-06-01" <= row["period_end"]
    assert row["period_start"] <= "2026-06-30" <= row["period_end"]
    assert not (row["period_start"] <= "2026-05-31" <= row["period_end"])
    assert not (row["period_start"] <= "2026-07-01" <= row["period_end"])


def test_filed_by_is_left_unset_because_it_references_a_different_table():
    """filings.filed_by references team_members(id) (migration 001) and the
    actor we hold is a users.id. Writing it would either violate the FK or
    record the wrong person."""
    row = build_filings_row(
        firm_id=FIRM, client_id=CLIENT, filing_type=FILING_TYPE_GSTR1,
        period=PERIOD, filed_date="2026-07-11",
    )

    assert "filed_by" not in row
