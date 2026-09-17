"""
Currency master + currency-policy resolution (Multi-Currency Phase 1 — read-only).

Additive and read-only: exposes the ISO 4217 currency master and the resolved
currency policy for a (firm, client). No accounting endpoint is touched, and
nothing here can change posting behaviour — with the feature off the policy is
always {active: false, functional_currency: "INR"}.
"""
import os
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access
from core.feature_flags import multi_currency_platform_enabled
from domain.currency import resolve_currency_policy
from domain.currency import currency_service

_logger = logging.getLogger("caflow.currencies")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

router = APIRouter(prefix="/api/currencies", tags=["currencies"])


@router.get("")
def get_currencies(
    active_only: bool = Query(True),
    current_user: dict = Depends(rbac("client", "read")),
):
    """List the ISO 4217 currency master (global reference data)."""
    if _USE_MOCK:
        return api_response(True, [])
    from core.supabase_client import get_supabase

    rows = currency_service.list_currencies(get_supabase(), active_only=active_only)
    return api_response(True, rows)


@router.get("/policy")
def get_currency_policy(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("client", "read")),
):
    """Resolve { active, functional_currency } for the caller's firm + this client.

    Phase 1: always {active: false, functional_currency: "INR"} unless all three
    gates (env, firm entitlement, client enablement) are on.
    """
    # Mount-guard-covered (required client_id query param); explicit so the
    # scope check is visible, and BEFORE the mock short-circuit below — which
    # otherwise returns a policy for any client_id without consulting scope.
    assert_client_access(current_user, client_id)
    firm_id = current_user.get("firm_id")
    if _USE_MOCK:
        pol = resolve_currency_policy(None, None)
        # Same SHAPE as the real branch. A mock reply missing `gates` would
        # make the screen render an undefined gate as "off" in dev and as
        # something else in production.
        return api_response(True, {
            "active": pol.active,
            "functional_currency": pol.functional_currency,
            "gates": _gates(None, None),
        })

    from core.supabase_client import get_supabase

    db = get_supabase()
    firm_res = (
        db.table("firms").select("id, multi_currency_entitled").eq("id", firm_id).limit(1).execute()
    )
    firm = (getattr(firm_res, "data", None) or [None])[0]
    # Tenant isolation: the client must belong to the caller's firm.
    client_res = (
        db.table("clients")
        .select("id, functional_currency, multi_currency_enabled")
        .eq("id", client_id)
        .eq("firm_id", firm_id)
        .limit(1)
        .execute()
    )
    client = (getattr(client_res, "data", None) or [None])[0]
    pol = resolve_currency_policy(firm, client)
    return api_response(True, {
        "active": pol.active,
        "functional_currency": pol.functional_currency,
        # WHICH GATE IS OFF (ACC-19). `active: false` alone is what made this
        # feature unusable: a Partner ticked a box, nothing happened, and the
        # screen could not say which of three switches was still down. Every
        # gate the caller can DO something about is reported separately, and
        # the one they cannot — the environment kill switch — says so.
        "gates": _gates(firm, client),
    })


def _gates(firm: dict | None, client: dict | None) -> dict:
    """The three gates `resolve_currency_policy` ANDs together, named.

    L1 is the environment kill switch and is deliberately not settable — see
    core/feature_flags, which says "No DB dependency". L2 and L3 are the two
    the endpoints below write.
    """
    functional = ((client or {}).get("functional_currency") or "INR").strip().upper()
    return {
        "platform": {
            "on": multi_currency_platform_enabled(),
            "settable": False,
            "why": ("MULTI_CURRENCY_ENABLED is an environment kill switch, not "
                    "a setting — it is read with no database dependency so it "
                    "can be turned off without one."),
        },
        "firm": {
            "on": bool((firm or {}).get("multi_currency_entitled")),
            "settable": True,
        },
        "client": {
            "on": bool((client or {}).get("multi_currency_enabled")),
            "settable": True,
        },
        # Capability B — a non-INR functional currency, meaning presentation
        # and translation — is not built, so the policy fails safe on one. A
        # client whose books are kept in USD therefore cannot be switched on,
        # and saying so is better than an inert checkbox.
        "functional_currency_supported": functional == "INR",
        "functional_currency": functional,
    }


@router.get("/entitlement")
def get_firm_entitlement(
    current_user: dict = Depends(rbac("settings", "read")),
):
    """The two FIRM-level gates, with no client in the request.

    WHY THIS EXISTS RATHER THAN READING THEM OFF A CLIENT'S POLICY. `GET
    /policy` carries the firm gate too, so the settings screen very nearly took
    it from the first client's answer — which is wrong for a firm that has no
    clients yet, exactly the firm a Partner is switching this on for. The
    checkbox would have snapped back to Off after every save, which is the
    inert control ACC-19 is about.

    One implementation either way: both answers come out of `_gates`.
    """
    firm_id = current_user.get("firm_id")
    if _USE_MOCK:
        g = _gates(None, None)
        return api_response(True, {"platform": g["platform"], "firm": g["firm"]})
    from core.supabase_client import get_supabase

    db = get_supabase()
    firm = (db.table("firms").select("id, multi_currency_entitled")
            .eq("id", firm_id).limit(1).execute().data or [None])[0]
    g = _gates(firm, None)
    return api_response(True, {"platform": g["platform"], "firm": g["firm"]})


@router.put("/entitlement")
def set_firm_entitlement(
    enabled: bool = Body(..., embed=True),
    current_user: dict = Depends(rbac("settings", "write")),
):
    """Turn multi-currency on or off for the caller's OWN firm (L2).

    WHAT WAS WRONG (ACC-19). All five multi-currency phases are built —
    foreign documents, realized and unrealized FX, five /api/fx-reports
    endpoints, foreign bank accounts — and `firms.multi_currency_entitled`
    (migration 146) was READ by policy.py and six routers and WRITTEN BY
    NOTHING. No endpoint, no Pydantic field, no screen, no seed. Only a manual
    UPDATE against the database could activate any of it.

    SELF-SERVE, and that is an owner decision of 13-09-2026. There is no
    billing, plan or entitlement machinery anywhere in this product, so a
    commercial gate has nothing to hang off and building one would be larger
    than the feature it gates. If it is ever sold the column does not move: a
    plan check goes in FRONT of this endpoint.

    Partner-only (`settings` write), because it changes what the posting kernel
    accepts for every client of the firm.
    """
    firm_id = current_user.get("firm_id")
    if _USE_MOCK:
        return api_response(True, {"firm_id": firm_id, "multi_currency_entitled": bool(enabled)})
    from core.supabase_client import get_supabase

    db = get_supabase()
    # Scoped to the caller's own firm and to nothing else: there is no firm_id
    # in the request, so a Partner can only ever change their own.
    res = (db.table("firms").update({"multi_currency_entitled": bool(enabled)})
           .eq("id", firm_id).execute())
    if not (getattr(res, "data", None) or []):
        raise HTTPException(status_code=404, detail="Firm not found.")
    _logger.info("caflow.currencies firm %s multi_currency_entitled=%s", firm_id, bool(enabled))
    return api_response(True, {"firm_id": firm_id, "multi_currency_entitled": bool(enabled)})


@router.put("/policy")
def set_client_currency_policy(
    client_id: str = Query(...),
    enabled: bool = Body(..., embed=True),
    current_user: dict = Depends(rbac("settings", "write")),
):
    """Turn multi-currency on or off for ONE client (L3).

    The other half of ACC-19: `clients.multi_currency_enabled` was read by the
    same six routers and written by nothing either.

    TURNING IT ON IS REFUSED WHERE IT WOULD BE INERT. Two ways that happens,
    and each is a sentence rather than a silent no-op — an inert checkbox is
    the defect this endpoint exists to end, and adding a second one would be
    the same mistake:

      * the FIRM is not entitled, so `active` would stay false however this is
        set. The order is firm first, then client;
      * the client's functional currency is not INR. Capability B
        (presentation and translation) is not built, so `resolve_currency_policy`
        fails safe on a non-INR functional currency by design.

    Turning it OFF is never refused. A client that should not be transacting in
    foreign currency has to be stoppable whatever the firm's state is.
    """
    assert_client_access(current_user, client_id)
    firm_id = current_user.get("firm_id")
    if _USE_MOCK:
        return api_response(True, {"client_id": client_id, "multi_currency_enabled": bool(enabled)})
    from core.supabase_client import get_supabase

    db = get_supabase()
    client = (db.table("clients")
              .select("id, functional_currency, multi_currency_enabled")
              .eq("id", client_id).eq("firm_id", firm_id).limit(1).execute().data or [None])[0]
    if not client:
        raise HTTPException(status_code=404, detail="Client not found.")

    if enabled:
        firm = (db.table("firms").select("id, multi_currency_entitled")
                .eq("id", firm_id).limit(1).execute().data or [None])[0]
        if not (firm or {}).get("multi_currency_entitled"):
            raise HTTPException(
                status_code=409,
                detail=("Multi-currency is off for the firm, so turning it on for "
                        "one client would change nothing. Turn it on for the firm "
                        "first (Settings → Multi-currency)."))
        functional = (client.get("functional_currency") or "INR").strip().upper()
        if functional != "INR":
            raise HTTPException(
                status_code=409,
                detail=(f"This client's functional currency is {functional}. The "
                        "product supports INR-functional books that transact in "
                        "foreign currency; keeping the books themselves in "
                        "another currency (presentation and translation) is not "
                        "built, so the policy would stay inactive."))

    res = (db.table("clients").update({"multi_currency_enabled": bool(enabled)})
           .eq("id", client_id).eq("firm_id", firm_id).execute())
    if not (getattr(res, "data", None) or []):
        raise HTTPException(status_code=404, detail="Client not found.")
    _logger.info("caflow.currencies client %s multi_currency_enabled=%s", client_id, bool(enabled))
    return api_response(True, {"client_id": client_id, "multi_currency_enabled": bool(enabled)})


# ─── FX rates (the table nothing could write) ─────────────────────────────────
#
# `public.fx_rates` (migration 146) is READ by `ManualRateProvider` — which is
# what every foreign document's booking rate resolves through — and was WRITTEN
# BY NOTHING. No endpoint, no Pydantic field, no screen, no seed. Only a manual
# INSERT against the database could put a rate in it, so with the ACC-19 gates
# now switchable a Partner could turn multi-currency ON and then find that the
# one thing it needs cannot be recorded. Exactly the shape ACC-19 itself was,
# and the shape `capital_wip` and `fx_revaluations` were: built, reached,
# structurally empty.
#
# THE TABLE STAYS GLOBAL, AND THE TENANCY OBJECTION IS ANSWERED ON THE WRITE
# SIDE. USD→INR on a date is a fact about the world — the RBI publishes one —
# so a firm-scoped table would have every firm re-typing the same number, and
# the rate a document was booked at would depend on who typed it. The answer is
# Partner-only plus `created_by`, and a screen that SAYS the rate is shared.
# Owner decision, recorded in docs/audits/questions-for-the-owner.md.

_RATE_TYPES = ("booking", "gst_notified", "customs", "closing")

#: What each rate_type is FOR. Served rather than spelled on the screen, for the
#: reason the Schedule III captions are: a browser copy of a vocabulary drifts.
#: The four are NOT interchangeable and a screen must never let one figure be
#: typed for all of them —
#:   booking       the rate a transaction is recorded at (AS 11 paragraph 9);
#:   gst_notified  CGST Rule 34 fixes the rate for GST at the one notified under
#:                 s.14 of the Customs Act, which is NOT the day's market rate;
#:   customs       the rate the Bill of Entry was assessed at;
#:   closing       AS 11 paragraph 11's closing rate, which the year-end
#:                 revaluation retranslates monetary items at.
_RATE_TYPE_MEANINGS = {
    "booking": "The rate a transaction is recorded at (AS 11 paragraph 9). "
               "This is the one every foreign invoice, bill, receipt and "
               "payment resolves through.",
    "gst_notified": "CGST Rule 34: the rate of exchange for GST is the one "
                    "notified under s.14 of the Customs Act, not the day's "
                    "market rate. Recording the market rate here declares a "
                    "different taxable value from the one the Act fixes.",
    "customs": "The rate a Bill of Entry was assessed at.",
    "closing": "AS 11 paragraph 11's closing rate, at which monetary items are "
               "retranslated on a balance sheet date. Used by the year-end FX "
               "revaluation and by nothing else.",
}


@router.get("/rate-types")
def get_rate_types(current_user: dict = Depends(rbac("client", "read"))):
    """The four rate types and what each one is for.

    Served rather than spelled on the screen: the CHECK on `fx_rates.rate_type`
    admits exactly these four, and a browser list of them is a second
    vocabulary one migration away from disagreeing with the database.
    """
    return api_response(True, {"rate_types": [
        {"code": c, "meaning": _RATE_TYPE_MEANINGS[c]} for c in _RATE_TYPES]})


@router.get("/rates")
def list_fx_rates(
    base: str = Query("USD", min_length=3, max_length=3),
    quote: str = Query("INR", min_length=3, max_length=3),
    rate_type: str = Query("booking"),
    limit: int = Query(60, ge=1, le=365),
    current_user: dict = Depends(rbac("client", "read")),
):
    """The most recent rates for one (base, quote, rate_type), newest first.

    Bounded by `limit` rather than by a date range, because the question the
    screen asks is "what has been recorded lately" and the answer is a screenful
    — CLAUDE.md's rule that what crosses the wire is proportional to the ANSWER.
    """
    rate_type = (rate_type or "").strip().lower()
    if rate_type not in _RATE_TYPES:
        raise HTTPException(status_code=422,
                            detail=f"rate_type must be one of {', '.join(_RATE_TYPES)}.")
    if _USE_MOCK:
        return api_response(True, {"base": base.upper(), "quote": quote.upper(),
                                   "rate_type": rate_type, "rates": []})
    from core.supabase_client import get_supabase

    rows = (get_supabase().table("fx_rates")
            .select("id, base, quote, rate_date, rate_type, rate, source, created_at")
            .eq("base", base.upper()).eq("quote", quote.upper())
            .eq("rate_type", rate_type)
            .order("rate_date", desc=True).limit(limit).execute().data) or []
    return api_response(True, {"base": base.upper(), "quote": quote.upper(),
                               "rate_type": rate_type, "rates": rows})


@router.put("/rates")
def record_fx_rate(
    base: str = Body(..., embed=True),
    quote: str = Body(..., embed=True),
    rate_date: str = Body(..., embed=True),
    rate: str = Body(..., embed=True),
    rate_type: str = Body("booking", embed=True),
    current_user: dict = Depends(rbac("settings", "write")),
):
    """Record one rate. Partner-only, and the rate is shared across the platform.

    `source` is ALWAYS 'manual' and is not settable. It is the provider
    identifier `ManualRateProvider` matches on, so a value typed here would
    write a rate that nothing reads — and the unique key is
    (base, quote, rate_date, rate_type, source), so a second source silently
    becomes a second rate for the same day rather than a correction.

    THE RATE IS PARSED AS A DECIMAL FROM ITS TEXT, never through a float. The
    column is NUMERIC(18,8) precisely so the rate is exact, and
    `RateQuote` reads it back with `Decimal(str(...))` for the same reason;
    taking a JSON number here would put a float round trip in front of all of
    that. Same discipline as `lib/money/rupeeInput.ts` on the rupee side.

    AN EXISTING RATE FOR THAT DAY IS REPLACED, not added to. A correction is
    the ordinary case — somebody typed 83.42 for 84.32 — and the unique key
    means a second INSERT would fail rather than correct. What it does NOT do
    is reach back into documents already booked at the old rate: a posted
    journal is immutable (migration 251), and re-rating one is a reversal the
    CA raises. The response SAYS which of the two happened.
    """
    from decimal import Decimal, InvalidOperation
    from datetime import date as _date

    base, quote = (base or "").strip().upper(), (quote or "").strip().upper()
    rate_type = (rate_type or "booking").strip().lower()
    if len(base) != 3 or len(quote) != 3:
        raise HTTPException(status_code=422, detail="base and quote are ISO 4217 codes.")
    if base == quote:
        raise HTTPException(
            status_code=422,
            detail="A currency's rate against itself is 1 by definition and is "
                   "resolved without a stored rate — see the identity source.")
    if rate_type not in _RATE_TYPES:
        raise HTTPException(status_code=422,
                            detail=f"rate_type must be one of {', '.join(_RATE_TYPES)}.")
    try:
        parsed = Decimal(str(rate).strip())
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=422, detail="rate must be a decimal number.")
    if parsed <= 0:
        # The column CHECKs rate > 0; saying so here costs a keystroke rather
        # than a 500 from the database.
        raise HTTPException(status_code=422, detail="rate must be greater than zero.")
    try:
        when = _date.fromisoformat(str(rate_date)[:10]).isoformat()
    except ValueError:
        raise HTTPException(status_code=422, detail="rate_date must be YYYY-MM-DD.")

    if _USE_MOCK:
        return api_response(True, {"base": base, "quote": quote, "rate_date": when,
                                   "rate_type": rate_type, "rate": str(parsed),
                                   "source": "manual", "replaced": False})
    from core.supabase_client import get_supabase

    db = get_supabase()
    existing = (db.table("fx_rates").select("id")
                .eq("base", base).eq("quote", quote).eq("rate_date", when)
                .eq("rate_type", rate_type).eq("source", "manual")
                .limit(1).execute().data) or []
    # THE KEYS ARE WRITTEN OUT AT EACH CALL, not passed as a variable.
    # `tests/test_backend_columns_exist_pg.py` reads an insert or update payload
    # as a dict LITERAL, so a `payload` built above and handed in is invisible
    # to it — a column renamed out from under this would be found in production
    # rather than in CI. The duplication is the price, and it is the same
    # decision `domain/firm/identity` and `_document_numbers` both record.
    # created_by FKs to public.users.id (the INTERNAL id), not the Supabase auth
    # id — CLAUDE.md.
    if existing:
        (db.table("fx_rates").update({
            "base": base, "quote": quote, "rate_date": when,
            "rate_type": rate_type, "rate": str(parsed), "source": "manual",
            "created_by": current_user.get("id"),
        }).eq("id", existing[0]["id"]).execute())
    else:
        db.table("fx_rates").insert({
            "base": base, "quote": quote, "rate_date": when,
            "rate_type": rate_type, "rate": str(parsed), "source": "manual",
            "created_by": current_user.get("id"),
        }).execute()
    payload = {"base": base, "quote": quote, "rate_date": when,
               "rate_type": rate_type, "rate": str(parsed), "source": "manual",
               "created_by": current_user.get("id")}
    _logger.info("caflow.currencies %s %s/%s %s %s=%s by %s",
                 "replaced" if existing else "recorded", base, quote, when,
                 rate_type, parsed, current_user.get("id"))
    return api_response(True, {**payload, "replaced": bool(existing)})
