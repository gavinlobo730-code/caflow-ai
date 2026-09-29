"""GST-20 — a saved or approved GSTR-3B must be under a GSTIN this CLIENT
holds, not merely a well-formed one (apex-tax-compliance-01).

`save_gstr3b` already rejected a GSTIN failing its OWN checksum
(`validate_gstin`), but never asked whether the client holds it at all — the
question the GSTR-9/GSTR-9C/IFF compute paths in this same file already ask
through `client_gst_registration_service.resolve`. A CA could therefore save a
GSTR-3B under a well-formed GSTIN the client does not hold, in violation of
GST-20's registration-ownership rule.

`update_gstr3b_status` carried the same gap on the transition into
`ca_approved`/`submitted`: a return recorded under a registration the client no
longer (or never) held could still be approved and marked filed unchecked.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.gst_workspace as gw
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
CLIENT = "client-1"
PRIMARY = "27AAPFU0939F1ZV"   # clients.gstin — checksum-valid (tests/fixtures/gstin.json)
SECOND = "29AAGCB7383J1Z4"    # an additional registration this client also holds
UNHELD = "24AAACC1206D1ZM"    # checksum-valid, held by nobody in this fixture
PERIOD = "062026"

USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1",
        "email": "ca@f.test", "role": "Partner"}


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    monkeypatch.setattr(gw, "_USE_MOCK", False)
    wire_e2e(monkeypatch, d, [gw])
    d.seed("clients", {
        "id": CLIENT, "firm_id": FIRM, "client_name": "Acme Industries",
        "legal_name": "Acme Industries Private Limited",
        "gstin": PRIMARY, "state_code": "27",
        "gst_filing_frequency": "monthly", "gst_registration_date": None,
        "gst_registration_type": None, "composition_category": None,
    })
    d.seed("client_gst_registrations", {
        "firm_id": FIRM, "client_id": CLIENT, "gstin": SECOND,
        "state_code": "29", "registration_type": "regular",
        "filing_frequency": "monthly", "trade_name": "Bengaluru depot",
        "effective_from": None, "effective_to": None, "notes": None,
        "created_at": None, "deleted_at": None, "composition_category": None,
    })
    return d


def _save(db, gstin, **over):
    body = {
        "client_id": CLIENT, "period": PERIOD, "gstin": gstin,
        "payload_json": {}, "summary_json": {},
        "tax_liability_paise": 10_000_00, "itc_claimed_paise": 2_000_00,
        "net_tax_paise": 8_000_00,
    }
    body.update(over)
    return gw.save_gstr3b(gw.SaveGSTR3BRequest(**body), current_user=USER)


def _approve(db, return_id, status="ca_approved", acknowledge_stale=True):
    # acknowledge_stale=True: this fixture's FakeDB carries no journal entries
    # behind the saved figures, so the pre-existing "books have moved since
    # this was computed" check would otherwise refuse every approval here —
    # a different, unrelated guard this file is not about.
    return gw.update_gstr3b_status(
        return_id, gw.UpdateStatusRequest(
            status=status, ca_approved=True, acknowledge_stale=acknowledge_stale),
        current_user=USER)


# ── save_gstr3b: the new registration-ownership check ────────────────────────

def test_a_gstin_the_client_does_not_hold_is_refused_at_save(db):
    with pytest.raises(HTTPException) as ei:
        _save(db, UNHELD)
    assert ei.value.status_code == 422
    assert PRIMARY in str(ei.value.detail), \
        "the refusal should name what IS on file, the way the compute paths' do"
    assert not db.rows("gstr3b_returns"), "nothing was saved"


def test_the_primary_gstin_still_saves(db):
    result = _save(db, PRIMARY)
    assert result["success"] is True
    assert db.rows("gstr3b_returns")[0]["gstin"] == PRIMARY


def test_an_additional_registrations_gstin_also_saves(db):
    """GST-20: a client may hold several GSTINs, and each files its own
    return — the fix must not narrow saving back down to the primary alone."""
    result = _save(db, SECOND)
    assert result["success"] is True
    assert db.rows("gstr3b_returns")[0]["gstin"] == SECOND


def test_a_checksum_valid_but_unheld_gstin_is_never_written_even_as_a_revision(db):
    """Saving twice under the primary, then trying to redirect the SAME draft
    to a GSTIN the client does not hold, must not quietly repoint it."""
    saved = _save(db, PRIMARY)["data"]
    with pytest.raises(HTTPException):
        _save(db, UNHELD)
    row = db.rows("gstr3b_returns")[0]
    assert row["id"] == saved["id"] and row["gstin"] == PRIMARY


# ── update_gstr3b_status: the same check on approve/submit ───────────────────

def test_approving_a_return_whose_registration_has_since_gone_is_refused(db):
    saved = _save(db, SECOND)["data"]
    # The registration is withdrawn (or corrected away) after the return was
    # saved — simulated here by soft-deleting the row its GSTIN depends on.
    db.rows("client_gst_registrations")[0]["deleted_at"] = "2026-06-15T00:00:00+00:00"

    result = _approve(db, saved["id"])

    assert result["success"] is False
    assert PRIMARY in result["error"]
    row = [r for r in db.rows("gstr3b_returns") if r["id"] == saved["id"]][0]
    assert row["status"] == "draft", "the row must not have moved to ca_approved"


def test_approving_a_return_under_a_held_registration_still_works(db):
    saved = _save(db, PRIMARY)["data"]
    result = _approve(db, saved["id"])
    assert result["success"] is True
    row = [r for r in db.rows("gstr3b_returns") if r["id"] == saved["id"]][0]
    assert row["status"] == "ca_approved"


def test_submitting_is_checked_too_not_only_ca_approved(db):
    saved = _save(db, SECOND)["data"]
    db.rows("client_gst_registrations")[0]["deleted_at"] = "2026-06-15T00:00:00+00:00"

    result = _approve(db, saved["id"], status="submitted")

    assert result["success"] is False
    row = [r for r in db.rows("gstr3b_returns") if r["id"] == saved["id"]][0]
    assert row["status"] == "draft"


def test_a_draft_or_validated_transition_is_not_gated_on_the_check(db):
    """The registration check exists to stop an APPROVAL/FILING under a stale
    registration — moving a return between draft and validated is not that,
    and must not start failing for clients with no registration change at
    all."""
    saved = _save(db, SECOND)["data"]
    db.rows("client_gst_registrations")[0]["deleted_at"] = "2026-06-15T00:00:00+00:00"

    result = gw.update_gstr3b_status(
        saved["id"], gw.UpdateStatusRequest(status="validated"),
        current_user=USER)

    assert result["success"] is True
