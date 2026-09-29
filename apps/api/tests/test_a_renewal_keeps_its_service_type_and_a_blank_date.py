"""Two bugs in `POST /api/lifecycle/renewals`, found by live browser testing.

BUG 1 — service_type was accepted on the request, shown back in the create
response, and never written to the database. `routers/lifecycle.py::
create_renewal` built ONE `row` dict carrying `service_type` and then, on the
real-Postgres path only, built a SECOND dict (`db_row`) that dropped it before
the INSERT — because `public.renewals` had no such column at all (migration
059). Mock mode inserts `row` unchanged, so this bug is invisible unless the
DB-path payload — what actually reaches Postgres — is inspected directly,
which is what these tests do with a fake `db.table("renewals").insert(...)`
rather than relying on the mock branch.

BUG 2 — a blank Renewal Date was fabricated to `ist_today() + 365 days` and
stored as though the CA had typed it, because `renewals.renewal_date` was
NOT NULL. Migration 438 makes the column nullable; this pins that the ROUTER
no longer fabricates a value — it must pass a caller-omitted date through as
NULL, on both the mock and the real-Postgres path.

Migration 438 is the schema half (adds `service_type`, drops `renewal_date`
NOT NULL) and is pinned separately by the real-Postgres suite
(test_migrations_apply.py exercises every migration; there is no dedicated
schema test here because a plain ALTER TABLE ADD COLUMN / DROP NOT NULL has
no interesting failure mode beyond "did it apply").
"""
from unittest.mock import patch

import pytest

from routers.lifecycle import create_renewal, RenewalIn


PARTNER = {"id": "u1", "firm_id": "f1", "role": "Partner", "email": "p@x.com"}


class _FakeQuery:
    def __init__(self, log):
        self._log = log

    def insert(self, payload):
        self._log["insert"] = payload
        return self

    def execute(self):
        return type("R", (), {"data": [self._log.get("insert")]})()


class _FakeDb:
    def __init__(self):
        self.log: dict = {}

    def table(self, name):
        assert name == "renewals", name
        return _FakeQuery(self.log)


def _create(**overrides):
    db = _FakeDb()
    body = {
        "client_id": "c1",
        "financial_year": "2026-27",
        "service_type": "GST Filing",
        "value_paise": 1_500_000,
    }
    body.update(overrides)
    with patch("routers.lifecycle._db", return_value=db):
        out = create_renewal(data=RenewalIn(**body), current_user=PARTNER)
    return out, db.log.get("insert")


# ── Bug 1: service_type reaches the database ──────────────────────────────────

def test_service_type_is_written_to_the_database():
    _out, inserted = _create(service_type="GST Filing")
    assert inserted is not None, "create_renewal never reached the DB insert"
    assert inserted.get("service_type") == "GST Filing", (
        "service_type was accepted and dropped before the INSERT — the exact "
        "bug: correct in the create response, blank on every reload"
    )


def test_the_create_response_and_the_stored_row_agree():
    """The response the CA sees immediately must be the same value that
    survives a reload, not two different pictures of one renewal."""
    out, inserted = _create(service_type="Tax Audit")
    assert out["data"]["service_type"] == "Tax Audit"
    assert inserted["service_type"] == "Tax Audit"


# ── Bug 2: a blank renewal date is stored as NULL, never fabricated ──────────

def test_a_blank_renewal_date_is_stored_as_null_not_fabricated():
    _out, inserted = _create(renewal_date=None)
    assert inserted.get("renewal_date") is None, (
        f"a blank Renewal Date was fabricated to {inserted.get('renewal_date')!r} "
        "instead of being left null"
    )


def test_a_blank_renewal_date_is_null_in_the_response_too():
    out, _inserted = _create(renewal_date=None)
    assert out["data"]["renewal_date"] is None


def test_a_supplied_renewal_date_is_passed_through_unchanged():
    out, inserted = _create(renewal_date="2027-03-31")
    assert inserted.get("renewal_date") == "2027-03-31"
    assert out["data"]["renewal_date"] == "2027-03-31"


# ── The same two facts hold in mock mode (no DB configured) ─────────────────

def test_mock_mode_also_keeps_service_type_and_a_null_date():
    with patch("routers.lifecycle._db", return_value=None):
        out = create_renewal(
            data=RenewalIn(client_id="c1", financial_year="2026-27",
                           service_type="ROC Compliance", value_paise=0),
            current_user=PARTNER,
        )
    assert out["data"]["service_type"] == "ROC Compliance"
    assert out["data"]["renewal_date"] is None
