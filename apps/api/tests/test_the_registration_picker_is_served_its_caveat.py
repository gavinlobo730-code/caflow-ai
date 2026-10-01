"""
GST-17 — the registration picker's server half.

The picker itself is a screen and is held by `apps/web/scripts/
the-gst-screens-let-the-ca-choose-the-registration.test.ts` and the pure rules
in `lib/gst/registrationChoice.test.ts`. What the SERVER owes it, and what this
asserts, is three things:

  * the list it chooses from carries, per registration, the caveat a return for
    that registration would have to say — because choosing a registration does
    not split the documents (GST-16 is open), and a picker that did not say so
    would let a CA build wrong returns faster;
  * the compute calls accept the chosen GSTIN and BUILD THAT REGISTRATION'S
    RETURN — the response names it, so the screen saves it under that GSTIN;
  * a GSTIN the client does not hold is REFUSED and never defaulted to the
    primary.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.gst as gst_router
import routers.gst_workspace as gw
import services.client_gst_registration_service as regsvc
import services.gst_return_service as grs
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-P"
CLIENT = "CLI"
PRIMARY = "27AAAAA0000A1Z2"      # Maharashtra
SECOND = "29AAAAA0000A1ZY"       # Karnataka
PERIOD = "062025"
CALLER = {"firm_id": FIRM, "id": "u-p", "auth_user_id": "auth-p",
          "email": "ca@p.test", "role": "Partner"}


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [gw, grs, gst_router])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "gstin": PRIMARY,
                       "financial_year_start": "2025-04-01", "state_code": "27"})
    seed_standard_coa(d, FIRM, CLIENT)
    return d


def _second(db, **over):
    row = {"firm_id": FIRM, "client_id": CLIENT, "gstin": SECOND,
           "state_code": "29", "registration_type": "regular",
           "filing_frequency": "monthly", "deleted_at": None}
    row.update(over)
    return db.seed("client_gst_registrations", row)


# ── the list carries the caveat, per registration ────────────────────────────

def test_a_client_with_one_registration_carries_no_caveat(db):
    rows = regsvc.listing(db, FIRM, CLIENT)
    assert [r["gstin"] for r in rows] == [PRIMARY]
    assert rows[0]["documents_not_split_caveat"] is None, (
        "null is the TRUTH for one registration — rendering nothing is not an omission")


def test_two_registrations_each_carry_a_caveat_naming_the_other(db):
    _second(db)
    rows = {r["gstin"]: r for r in regsvc.listing(db, FIRM, CLIENT)}
    assert list(rows) == [PRIMARY, SECOND], "the primary comes first"
    primary = rows[PRIMARY]["documents_not_split_caveat"]
    second = rows[SECOND]["documents_not_split_caveat"]
    assert primary and SECOND in primary and "the primary registration" in primary
    assert second and PRIMARY in second and "a second registration" in second
    assert "split by registration" in second


def test_the_caveat_is_the_domains_own_sentence_not_a_second_wording(db):
    """One place words it. If the list built its own sentence the screen would
    say something different from the return it produces."""
    from domain.gst import registrations as reg
    _second(db)
    held = regsvc.held(db, FIRM, CLIENT)
    served = {r["gstin"]: r["documents_not_split_caveat"]
              for r in regsvc.listing(db, FIRM, CLIENT)}
    for r in held:
        assert served[r.gstin] == reg.documents_not_split_caveat(held, r.gstin)


def test_a_registration_that_files_another_return_is_not_offered_a_caveat(db):
    """A composition dealer's own returns are built from its own tables and owe
    nothing here — and it is not a registration a GSTR-1 can be prepared for."""
    _second(db, registration_type="composition", composition_category="trader")
    rows = {r["gstin"]: r for r in regsvc.listing(db, FIRM, CLIENT)}
    assert rows[SECOND]["files_gstr1_and_3b"] is False
    assert rows[SECOND]["other_return_form"]
    assert rows[SECOND]["documents_not_split_caveat"] is None
    # ... and the one registration left that does file is not asked to carry a
    # caveat about a split between registrations that file the ordinary pair.
    assert rows[PRIMARY]["documents_not_split_caveat"] is None


# ── the compute call builds the chosen registration's return ─────────────────

def _compute3b(db, gstin=None):
    req = gst_router.FromBooksRequest(client_id=CLIENT, period=PERIOD,
                                      **({"gstin": gstin} if gstin else {}))
    return gst_router.gstr3b_from_books_endpoint(req, CALLER)


def test_the_chosen_registration_is_the_one_the_return_is_built_for(db):
    _second(db)
    primary = _compute3b(db)["data"]
    second = _compute3b(db, SECOND)["data"]
    assert primary["gstin"] == PRIMARY, "omitted means the primary"
    assert second["gstin"] == SECOND
    # The caveat travels with the return as well, so a screen that only reads
    # the compute response says the same thing the picker did.
    assert second["registration_caveat"] and PRIMARY in second["registration_caveat"]


def test_a_gstin_the_client_does_not_hold_is_refused_not_defaulted(db):
    _second(db)
    with pytest.raises(HTTPException) as e:
        _compute3b(db, "07AAAAA0000A1Z5")
    assert e.value.status_code == 422, (
        "a GSTIN the client does not hold must be REFUSED — never answered with "
        "the primary's return")


def test_gstr1_compute_takes_the_chosen_gstin_too(db):
    _second(db)
    req = gst_router.GSTR1FromBooksRequest(client_id=CLIENT, period=PERIOD,
                                           gstin=SECOND)
    out = gst_router.gstr1_from_books_endpoint(req, CALLER)["data"]
    assert out["gstin"] == SECOND
    assert out["payload"]["gstin"] == SECOND
