"""
A BROUGHT-FORWARD LOSS COULD BE DISPLAYED, SET OFF — AND NEVER RECORDED.

`brought_forward_losses` has existed since migration 156. `POST
/api/itr/bf-losses` records one. `domain/income_tax/loss_set_off.py` applies
§72, §73, §74 and §71B to it correctly, head by head, and IT-10 wired it into
the engine. The computation screen has a "Brought Forward Losses" panel that
lists them.

Nothing wrote the table. The endpoint had no caller — the reachability ratchet
carried it — and the panel is read-only, so every client saw "No carried-forward
losses recorded" for ever. §72 lets a business loss be carried eight assessment
years; a CA with a client holding one had nowhere to type it, and relief not
claimed in time is not recoverable.

AND THE ONE STATUTORY FACT IN THE ROW WAS TYPED
    `expiry_assessment_year` was a REQUIRED caller-supplied field, so how long
    a loss lives — the thing the Act decides — was whatever arrived in the
    request. `domain/income_tax/loss_carry_forward.py` is the authority now and
    the endpoint derives it; a caller-supplied value still wins, the shape
    `domain/tds/deductor.resolve` uses.

THE PERIOD THAT IS NOT EIGHT
    §73(4) carries a SPECULATION loss FOUR assessment years, against §72(3)'s
    and §74(2)'s and §71B's eight. The screen's own label used to read
    "§72 (Business, 8 yrs) · §74 (Capital, 8 yrs)" — true of three heads,
    silent about the fourth — and `loss_set_off`'s expiry refusal quoted
    "§72(3)/§74's eight assessment years" for every head including speculation.

⚠️ Every period is `[S]`-graded and pinned below, because egress is refused at
this environment's proxy. The error direction is NOT safe either way — too
short expires relief the client is entitled to, too long claims relief they are
not — which is why nothing falls back and the derived value can be overridden.
"""
from __future__ import annotations

import pytest

from domain.income_tax import loss_carry_forward as lcf
from domain.income_tax.loss_set_off import KNOWN_LOSS_TYPES


# ── The statutory table, pinned ──────────────────────────────────────────────

@pytest.mark.parametrize("loss_type,section,years", [
    ("business",           "§72(3)", 8),
    ("speculation",        "§73(4)", 4),
    ("capital_short_term", "§74(2)", 8),
    ("capital_long_term",  "§74(2)", 8),
    ("house_property",     "§71B",   8),
])
def test_each_head_carries_its_own_section_and_period(loss_type, section, years):
    rule = lcf.rule_for(loss_type)
    assert rule is not None
    assert rule.section == section
    assert rule.years == years


def test_speculation_is_four_and_nothing_else_is():
    """The whole point of the module. If this ever equals the others, the
    distinction §73(4) draws has been flattened."""
    four = [r.loss_type for r in lcf.known_types() if r.years == 4]
    assert four == ["speculation"]
    assert {r.years for r in lcf.known_types() if r.years is not None} == {4, 8}


def test_the_periods_are_not_claimed_as_verified():
    """`[S]`: written from knowledge, egress refused. Flipping this to True
    without reading the sections is the drift the flag exists to prevent."""
    assert lcf.VERIFIED is False


def test_every_stored_loss_type_has_a_rule():
    """The vocabulary is migration 319's CHECK, mirrored in KNOWN_LOSS_TYPES. A
    type added there without a rule here would fall through to 'not a loss type
    this product stores' at the one moment a CA is recording it."""
    assert {r.loss_type for r in lcf.known_types()} == set(KNOWN_LOSS_TYPES)


# ── The derivation ───────────────────────────────────────────────────────────

def test_the_expiry_is_the_last_year_it_may_still_be_used():
    """Matches what loss_set_off._is_available compares against: it refuses
    when the computation year is GREATER than the expiry, so a loss whose
    expiry equals this year is still available. Off by one here would silently
    give or take a whole year of relief."""
    last, why = lcf.expiry_for("business", "2020-21")
    assert last == "2028-29"
    assert "§72(3)" in why and "8" in why

    from domain.income_tax.loss_set_off import BroughtForwardLoss, _is_available
    loss = BroughtForwardLoss(loss_type="business", amount_paise=100,
                              assessment_year="2020-21", expiry_assessment_year=last)
    assert _is_available(loss, "2028-29")[0] is True, "its own expiry year must still work"
    assert _is_available(loss, "2029-30")[0] is False, "the year after must not"


def test_speculation_expires_four_years_earlier_than_business():
    b, _ = lcf.expiry_for("business", "2020-21")
    s, _ = lcf.expiry_for("speculation", "2020-21")
    assert b == "2028-29" and s == "2024-25"


def test_other_is_refused_rather_than_defaulted_to_eight():
    """`other` means the head is not identified, so no section fixes a period.
    Defaulting to eight would end a loss the Act may not end."""
    last, why = lcf.expiry_for("other", "2020-21")
    assert last is None
    assert "not identified" in why


def test_an_unknown_type_and_an_unparseable_year_are_each_refused_with_a_reason():
    for args in (("nonsense", "2020-21"), ("business", "not-a-year")):
        last, why = lcf.expiry_for(*args)
        assert last is None
        assert len(why) > 40, "a refusal with no reason is a silent nil"


def test_the_century_rolls_over_correctly():
    last, _ = lcf.expiry_for("business", "2099-00")
    assert last == "2107-08"


# ── The refusal message names the right section ──────────────────────────────

def test_an_expired_loss_names_its_own_section_and_period():
    from domain.income_tax.loss_set_off import BroughtForwardLoss, _is_available
    for loss_type, section, years in (("business", "§72(3)", "8"),
                                      ("speculation", "§73(4)", "4")):
        loss = BroughtForwardLoss(loss_type=loss_type, amount_paise=100,
                                  assessment_year="2015-16", is_expired=True)
        ok, why = _is_available(loss, "2026-27")
        assert ok is False
        assert section in why and years in why, why


def test_the_expired_message_no_longer_quotes_two_sections_at_every_head():
    """It used to read '§72(3)/§74's eight assessment years' for every head,
    speculation included. Two sections quoted at a third is how four becomes
    eight on a screen a CA reads."""
    from domain.income_tax.loss_set_off import BroughtForwardLoss, _is_available
    loss = BroughtForwardLoss(loss_type="speculation", amount_paise=100,
                              assessment_year="2015-16", is_expired=True)
    why = _is_available(loss, "2026-27")[1]
    assert "§72(3)/§74" not in why
    assert "eight" not in why.lower()


# ── What is deliberately absent ──────────────────────────────────────────────

def test_the_indefinitely_carried_losses_are_named_not_squeezed_into_other():
    """§32(2) unabsorbed depreciation and §73A both carry forward with NO
    expiry, and neither is in the stored vocabulary. Recording one as `other`
    with any expiry would end a loss the Act does not end, so they are named
    instead — and the endpoint serves the note so a screen can say why."""
    assert len(lcf.NOT_MODELLED) == 2
    joined = " ".join(lcf.NOT_MODELLED) + " " + " ".join(lcf.NOT_MODELLED.values())
    assert "32(2)" in joined and "73A" in joined
    for why in lcf.NOT_MODELLED.values():
        assert "indefinitel" in why, "the reason must say WHY there is no row"
    for name in lcf.NOT_MODELLED:
        assert name.split()[0].lstrip("§").rstrip("(2)") not in KNOWN_LOSS_TYPES


# ── The door ─────────────────────────────────────────────────────────────────
#
# Through the real HTTP path rather than by calling the handler: a direct call
# leaves every Query(...) default as a truthy Query object and skips FastAPI's
# own validation of the request model, which is where the loss-type refusal and
# the now-optional expiry actually live.

from fastapi import FastAPI                     # noqa: E402
from fastapi.testclient import TestClient       # noqa: E402

import routers.itr_workspace as itrw            # noqa: E402
from core.auth import get_current_user          # noqa: E402

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner",
           "email": "p@f1.test", "auth_user_id": "auth-partner"}


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(itrw.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def test_the_vocabulary_is_served_so_a_form_holds_none_of_it():
    r = _client().get("/api/itr/loss-types")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    by_type = {t["loss_type"]: t for t in data["types"]}
    assert set(by_type) == set(KNOWN_LOSS_TYPES)
    assert by_type["speculation"]["years"] == 4
    assert by_type["business"]["years"] == 8
    assert by_type["other"]["years"] is None
    assert data["verified"] is False
    assert len(data["not_modelled"]) == 2


def test_an_unknown_loss_type_is_a_422_and_not_a_500():
    """It used to reach migration 319's CHECK, raise inside create_bf_loss's
    `except Exception`, and come back as a 500 with a constraint name in it.

    The assertion names the VALIDATOR'S OWN message, not merely a 422 — a
    negative control found that removing the validator still gave 422, because
    an unknown type then reaches the expiry derivation and is refused THERE for
    a different reason. Two refusals with the same status code are not
    interchangeable: this one lists what is valid, and that is what a CA needs.
    """
    r = _client().post("/api/itr/bf-losses", json={
        "client_id": "C1", "assessment_year": "2020-21", "loss_type": "made_up",
        "original_amount_paise": 100000,
    })
    assert r.status_code == 422, r.text
    assert "Unknown loss type 'made_up'" in r.text
    assert "One of:" in r.text and "capital_long_term" in r.text


def test_a_loss_with_no_expiry_is_stored_with_the_derived_one():
    """End to end: the row that comes back carries §72(3)'s answer, and the
    working travels with it so the screen can say which section fixed the date
    rather than showing a year with no provenance."""
    r = _client().post("/api/itr/bf-losses", json={
        "client_id": "C1", "assessment_year": "2020-21", "loss_type": "business",
        "original_amount_paise": 100000,
    })
    assert r.status_code == 200, r.text
    row = r.json()["data"]
    assert row["expiry_assessment_year"] == "2028-29"
    assert "§72(3)" in row["expiry_derivation"]


def test_speculation_is_stored_four_years_out_not_eight():
    r = _client().post("/api/itr/bf-losses", json={
        "client_id": "C1", "assessment_year": "2020-21", "loss_type": "speculation",
        "original_amount_paise": 100000,
    })
    assert r.status_code == 200, r.text
    assert r.json()["data"]["expiry_assessment_year"] == "2024-25"


def test_other_is_accepted_once_the_ca_supplies_the_expiry():
    """The refusal is about the DERIVATION, not about the head. A CA who knows
    the answer records it; the endpoint must not then overrule them with a
    derivation it has already said it cannot make."""
    r = _client().post("/api/itr/bf-losses", json={
        "client_id": "C1", "assessment_year": "2020-21", "loss_type": "other",
        "original_amount_paise": 100000, "expiry_assessment_year": "2026-27",
    })
    assert r.status_code == 200, r.text
    row = r.json()["data"]
    assert row["expiry_assessment_year"] == "2026-27"
    assert "expiry_derivation" not in row, (
        "a derivation was reported for a value the caller supplied")


def test_a_caller_supplied_expiry_is_not_overwritten_by_the_derivation():
    """business + an expiry of the CA's own: the §72(3) answer would be
    2028-29, and theirs must survive."""
    r = _client().post("/api/itr/bf-losses", json={
        "client_id": "C1", "assessment_year": "2020-21", "loss_type": "business",
        "original_amount_paise": 100000, "expiry_assessment_year": "2025-26",
    })
    assert r.status_code == 200, r.text
    assert r.json()["data"]["expiry_assessment_year"] == "2025-26"


def test_other_with_no_expiry_is_refused_with_the_reason():
    """No section fixes a period for an unidentified head, so the request is
    refused rather than given eight years by default."""
    r = _client().post("/api/itr/bf-losses", json={
        "client_id": "C1", "assessment_year": "2020-21", "loss_type": "other",
        "original_amount_paise": 100000,
    })
    assert r.status_code == 422, r.text
    assert "not identified" in r.text


def test_the_expiry_is_no_longer_a_required_field():
    """The regression that matters: making it required again would put the one
    statutory fact in the row back in the caller's hands."""
    fields = itrw.BFLossRequest.model_fields
    assert fields["expiry_assessment_year"].is_required() is False
    assert fields["assessment_year"].is_required() is True


def test_a_caller_supplied_expiry_still_wins():
    """domain/tds/deductor.resolve's shape. The derivation spares the CA
    eight-year arithmetic; it does not overrule them."""
    req = itrw.BFLossRequest(client_id="C1", assessment_year="2020-21",
                             loss_type="business", original_amount_paise=1,
                             expiry_assessment_year="2026-27")
    assert req.expiry_assessment_year == "2026-27"


def test_the_loss_type_is_normalised_on_the_way_in():
    req = itrw.BFLossRequest(client_id="C1", assessment_year="2020-21",
                             loss_type="  BUSINESS  ", original_amount_paise=1)
    assert req.loss_type == "business"
