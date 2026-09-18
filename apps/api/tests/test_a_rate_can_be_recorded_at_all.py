"""`public.fx_rates` was read by the booking path and written by nothing.

Migration 146 created it, `ManualRateProvider` reads it — it is what every
foreign invoice, bill, receipt and payment resolves its booking rate through —
and no endpoint, Pydantic field, screen or seed ever put a row in it. ACC-19
made the multi-currency gates switchable on 13-09-2026, which turned that from
dormant into live: a Partner can now turn the feature on and find the one thing
it needs cannot be recorded. Same shape as `capital_wip` and `fx_revaluations`.

What is asserted here is the DECISIONS, not the CRUD: who may write, what the
rate is parsed as, what a second rate for the same day does, and that the four
rate types stay four and stay distinct.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from routers import currencies as R

PARTNER = {"id": "u1", "firm_id": "f1", "role": "Partner", "email": "p@x.com"}


def _put(**kw):
    body = {"base": "USD", "quote": "INR", "rate_date": "2026-06-30",
            "rate": "83.4200", "rate_type": "booking"}
    body.update(kw)
    return R.record_fx_rate(current_user=PARTNER, **body)


# ── the rate itself ──────────────────────────────────────────────────────────

def test_a_rate_is_recorded_and_comes_back_exactly_as_typed():
    """NUMERIC(18,8) exists so the rate is exact. A JSON number would put a
    float round trip in front of a column chosen to avoid one — the same
    discipline lib/money/rupeeInput.ts applies to rupees."""
    out = _put(rate="83.42675000")
    assert out["success"]
    assert out["data"]["rate"] == "83.42675000"
    assert Decimal(out["data"]["rate"]) == Decimal("83.42675000")


def test_the_source_is_manual_and_is_not_settable():
    """`source` is the provider identifier ManualRateProvider matches on, and
    it is half the unique key — so a settable one writes a rate nothing reads,
    and makes a correction into a second rate for the same day."""
    import inspect
    assert "source" not in inspect.signature(R.record_fx_rate).parameters
    assert _put()["data"]["source"] == "manual"


@pytest.mark.parametrize("bad,why", [
    ({"rate": "0"}, "zero"),
    ({"rate": "-1"}, "negative"),
    ({"rate": "eighty"}, "not a number"),
    ({"rate_date": "30-06-2026"}, "not ISO"),
    ({"rate_type": "spot"}, "not one of the four"),
    ({"base": "US"}, "not ISO 4217"),
    ({"base": "INR", "quote": "INR"}, "a currency against itself"),
])
def test_what_is_refused_and_why(bad, why):
    with pytest.raises(HTTPException) as e:
        _put(**bad)
    assert e.value.status_code == 422, why
    assert str(e.value.detail).strip(), "a refusal must say something"


def test_a_currency_against_itself_is_refused_rather_than_stored_as_one():
    """1.0 is right and storing it is not: the identity source already answers
    it, and a stored row would be a second answer that can drift from it."""
    with pytest.raises(HTTPException) as e:
        _put(base="INR", quote="INR")
    assert "1 by definition" in str(e.value.detail)


# ── who may write ────────────────────────────────────────────────────────────

def test_the_write_is_partner_only_and_the_read_is_not():
    """A rate is shared across the platform, so the tenancy answer is on the
    WRITE side — the owner's decision. Asserted on the dependency, because that
    is what actually decides it."""
    def _pair(fn):
        """The (resource, action) the endpoint's rbac() actually closes over.

        Asserting only that SOME rbac is present is too weak: `rbac("client",
        "write")` passes that and opens the write to an Executive. The closure
        is what decides, so the closure is what is read — a negative control
        that downgraded the dependency slipped past the weaker form."""
        import inspect
        d = inspect.signature(fn).parameters["current_user"].default
        dep = getattr(d, "dependency", None)
        assert dep is not None, f"{fn.__name__} has no dependency at all"
        return dict(zip(dep.__code__.co_freevars,
                        (c.cell_contents for c in dep.__closure__ or ())))

    assert _pair(R.record_fx_rate) == {"resource": "settings", "action": "write"}, (
        "a rate is shared across the platform, so the write is Partner-only")
    assert _pair(R.list_fx_rates) == {"resource": "client", "action": "read"}
    assert _pair(R.get_rate_types) == {"resource": "client", "action": "read"}
    # The resource/action pair is what rbac() closes over; compare against the
    # endpoint next to it that is already Partner-only for the same reason.
    from core.permissions import Role, can
    assert can(Role.PARTNER.value, "settings", "write")
    assert not can(Role.EXECUTIVE.value, "settings", "write")
    assert can(Role.EXECUTIVE.value, "client", "read"), (
        "the READ must stay open — every screen showing a foreign amount needs it")


# ── the four types are four, and are not interchangeable ─────────────────────

def test_the_rate_types_match_the_database_check():
    """The CHECK on fx_rates.rate_type admits exactly these four. A browser list
    of them would be a second vocabulary; this endpoint is why there is none."""
    import pathlib
    sql = (pathlib.Path(__file__).resolve().parent.parent /
           "migrations" / "146_multi_currency_phase1_foundation.sql").read_text()
    block = sql[sql.index("CHECK (rate_type IN ("):]
    block = block[:block.index(")")]
    for code in R._RATE_TYPES:
        assert f"'{code}'" in block, f"{code} is not in the CHECK"
    assert block.count("'") // 2 == len(R._RATE_TYPES), (
        "the CHECK and _RATE_TYPES have diverged")


def test_each_rate_type_means_something_different():
    """Not interchangeable, and the one that matters most is gst_notified:
    CGST Rule 34 fixes the GST rate at the one notified under s.14 of the
    Customs Act, so recording the market rate there declares a different
    taxable value from the one the Act fixes."""
    meanings = [R._RATE_TYPE_MEANINGS[c] for c in R._RATE_TYPES]
    assert len(set(meanings)) == len(meanings), "two types share a sentence"
    assert "Rule 34" in R._RATE_TYPE_MEANINGS["gst_notified"]
    assert "AS 11 paragraph 11" in R._RATE_TYPE_MEANINGS["closing"]
    out = R.get_rate_types(current_user=PARTNER)
    assert [r["code"] for r in out["data"]["rate_types"]] == list(R._RATE_TYPES)
    assert all(r["meaning"] for r in out["data"]["rate_types"])


def test_the_list_endpoint_refuses_a_rate_type_it_cannot_store():
    with pytest.raises(HTTPException) as e:
        R.list_fx_rates(rate_type="spot", current_user=PARTNER)
    assert e.value.status_code == 422


def test_the_list_is_bounded_by_the_answer_not_the_history():
    """CLAUDE.md: what crosses the wire is proportional to the ANSWER."""
    import inspect
    q = inspect.signature(R.list_fx_rates).parameters["limit"].default
    assert q.default == 60
    # The bound is Annotated metadata, not an attribute on the Query — assert
    # the CONSTRAINT rather than a spelling of where FastAPI happens to keep it.
    bounds = {type(m).__name__: getattr(m, "le", getattr(m, "ge", None))
              for m in q.metadata}
    assert bounds.get("Le") == 365, (
        "an unbounded rate history is a report reading a ledger")
    assert bounds.get("Ge") == 1
