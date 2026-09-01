"""
The Schedule III ageing schedules, served.

Two paths, one rule. public.schedule_iii_ageing (migration 303) is what
production runs — the answer is twenty-four numbers and the input is every open
document the client has, so CLAUDE.md's reporting rule puts the aggregation in
the database. domain/reporting/ageing.py is the same rule in Python for
everything with no SQL functions to call: mock mode, local dev, the in-memory
suite. tests/test_schedule_iii_ageing_parity_pg.py holds the two identical.

The fallback fetch is bounded by what is OWED rather than by billing history —
`outstanding_paise > 0` and the status filter are both in the query, exactly as
customer_statement_service.ar_aging does since migration 278. On the live client
that is the difference between reading 5,655 invoices and reading the ones still
open.

CLASSIFICATION IS A WRITE, AND IT IS GUARDED HERE
    Marking a receivable disputed or doubtful, classifying a vendor under the
    MSMED Act, and marking a GL account as holding unbilled dues are the facts
    the note needs and the schema could not supply. They are recorded through
    classify() rather than by a direct PostgREST write from the report screen,
    because s.43B(h) of the IT Act makes the micro/small classification a
    taxable-income question and the account marking puts a balance into a
    statutory disclosure — they are judgements, and judgements go through rbac()
    and land in one place that validates them.

    review_unbilled() is the fourth write and a different kind. The markings say
    which accounts hold unbilled dues; only the review says there are no others,
    which is the assertion the note makes and what lets a nil be printed at all.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException

from core.ist_clock import ist_today
from domain.reporting import ageing

_logger = logging.getLogger("caflow.ageing")

# Transcribed from customer_statement_service / vendor_statement_service so the
# ageing schedule and the operational ageing agree on what an open document is.
_DEAD_INVOICE = {"draft", "cancelled"}
_DEAD_BILL = {"draft", "cancelled"}


def _d(v) -> Optional[str]:
    return str(v)[:10] if v else None


def _as_date(v) -> Optional[date]:
    try:
        return date.fromisoformat(_d(v)) if v else None
    except (ValueError, TypeError):
        return None


def _paginate_all(make_query, key: str = "id", page: int = 1000) -> list:
    """Keyset paging, same shape as the statement services'. An un-paged
    .execute() is silently capped at PostgREST's ~1000 rows, which here would
    understate a statutory disclosure with no error at all."""
    first = make_query()
    if not (hasattr(first, "gt") and hasattr(first, "order") and hasattr(first, "limit")):
        return first.execute().data or []
    out: list = []
    cursor = None
    while True:
        q = make_query()
        if cursor is not None:
            q = q.gt(key, cursor)
        rows = q.order(key).limit(page).execute().data or []
        out.extend(rows)
        if len(rows) < page:
            return out
        cursor = rows[-1].get(key)
        if cursor is None:
            return out


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _parse_as_of(as_of: Optional[str]) -> date:
    if not as_of:
        return _today()
    try:
        return date.fromisoformat(str(as_of)[:10])
    except (ValueError, TypeError):
        raise HTTPException(status_code=422,
                            detail=f"as_of must be YYYY-MM-DD, got {as_of!r}")


# ── The Python half's data fetch ─────────────────────────────────────────────

def _fetch_receivables(db, firm_id: str, client_id: str, as_of: date) -> list:
    rows = _paginate_all(lambda: db.table("client_sales_invoices")
            .select("id, invoice_date, due_date, outstanding_paise, status, "
                    "is_disputed, considered_doubtful")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .is_("deleted_at", "null")
            .not_.in_("status", list(_DEAD_INVOICE))
            .gt("outstanding_paise", 0))
    out = []
    for r in rows:
        # Belt and braces for a test double that ignores the query filters.
        if (r.get("status") or "") in _DEAD_INVOICE:
            continue
        invoiced = _as_date(r.get("invoice_date"))
        if invoiced and invoiced > as_of:
            continue                      # raised after the reporting date
        out.append(ageing.Receivable(
            outstanding_paise=int(r.get("outstanding_paise") or 0),
            ref_date=_as_date(r.get("due_date")) or invoiced,
            disputed=bool(r.get("is_disputed")),
            doubtful=bool(r.get("considered_doubtful")),
        ))
    return out


def _fetch_payables(db, firm_id: str, client_id: str, as_of: date) -> list:
    rows = _paginate_all(lambda: db.table("purchase_bills")
            .select("id, vendor_id, bill_date, due_date, outstanding_paise, status, is_disputed")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .is_("deleted_at", "null")
            .not_.in_("status", list(_DEAD_BILL))
            .gt("outstanding_paise", 0))
    vendors = {v["id"]: v for v in _paginate_all(
        lambda: db.table("vendors").select("id, name, msme_status")
        .eq("firm_id", firm_id).eq("client_id", client_id))}
    out = []
    for b in rows:
        if (b.get("status") or "") in _DEAD_BILL:
            continue
        billed = _as_date(b.get("bill_date"))
        if billed and billed > as_of:
            continue
        v = vendors.get(b.get("vendor_id")) or {}
        out.append(ageing.Payable(
            outstanding_paise=int(b.get("outstanding_paise") or 0),
            ref_date=_as_date(b.get("due_date")) or billed,
            disputed=bool(b.get("is_disputed")),
            # NOT defaulted. An unclassified vendor is a gap, never an "Other" —
            # see domain/reporting/ageing.MSME_ROW_STATUSES.
            msme_status=v.get("msme_status"),
            vendor_id=b.get("vendor_id"),
            vendor_name=v.get("name"),
        ))
    return out


def _fetch_unbilled(db, firm_id: str, client_id: str, as_of: date):
    """The marked accounts, their posting lines, and whether anybody has
    reviewed the chart of accounts.

    THE LINE FETCH IS BOUNDED BY THE MARKED ACCOUNTS, not by the ledger — the
    `!inner` embed makes PostgREST return only entries that HAVE a line on one
    of them, with only those lines attached, exactly as
    SupabaseLedgerSource._entries does for the per-account drill-down. An
    accrual account with four entries a year reads four entries however long
    the client has been trading. Production does not come through here at all:
    public.schedule_iii_ageing aggregates in the database, and this is the
    fallback for local dev and a failed RPC.
    """
    accounts = _paginate_all(lambda: db.table("chart_of_accounts")
            .select("id, account_code, account_name, unbilled_dues_side")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .not_.is_("unbilled_dues_side", "null"))
    marked = [ageing.UnbilledAccount(
                  account_id=a["id"],
                  account_code=str(a.get("account_code") or ""),
                  account_name=str(a.get("account_name") or ""),
                  side=a["unbilled_dues_side"])
              for a in accounts
              if a.get("unbilled_dues_side") in ageing.UNBILLED_SIDES]

    lines: list = []
    if marked:
        ids = [a.account_id for a in marked]
        rows = _paginate_all(lambda: db.table("journal_entries")
                .select("id, entry_date, journal_lines!inner(account_id, debit_paise, credit_paise)")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("is_posted", True).is_("deleted_at", "null")
                .lte("entry_date", as_of.isoformat())
                .in_("journal_lines.account_id", ids))
        for e in rows:
            when = _as_date(e.get("entry_date"))
            for ln in (e.get("journal_lines") or []):
                lines.append(ageing.PostingLine(
                    account_id=ln.get("account_id"),
                    entry_date=when,
                    debit_paise=int(ln.get("debit_paise") or 0),
                    credit_paise=int(ln.get("credit_paise") or 0)))

    review = (db.table("schedule_iii_unbilled_reviews").select("reviewed_on")
              .eq("firm_id", firm_id).eq("client_id", client_id)
              .limit(1).execute().data or [])
    return marked, lines, (_as_date(review[0].get("reviewed_on")) if review else None)


# ── The report ───────────────────────────────────────────────────────────────

def schedule(db, firm_id: str, client_id: str, as_of: Optional[str] = None) -> dict:
    """Both ageing schedules for one client. Tries the SQL aggregate first and
    falls back to the Python rule, which is what mock mode and local dev run."""
    at = _parse_as_of(as_of)
    if not client_id:
        raise HTTPException(status_code=422,
                            detail="client_id is required — the ageing schedule is a "
                                   "note to one client's balance sheet")

    if db is None:
        # No database at all — mock mode and local dev. An empty schedule in the
        # right shape, not a fabricated one: there are no documents to age.
        return ageing.build([], [], at, _today())

    if hasattr(db, "rpc"):
        try:
            res = db.rpc("schedule_iii_ageing", {
                "p_firm": firm_id, "p_client": client_id, "p_as_of": at.isoformat(),
            }).execute()
            out = getattr(res, "data", None)
            if isinstance(out, dict) and "receivables" in out and "payables" in out:
                return out
            raise ValueError(
                f"schedule_iii_ageing returned {type(out).__name__}, not a schedule")
        except Exception as e:                              # noqa: BLE001
            _logger.error("schedule_iii_ageing failed (%s %s %s) — falling back to "
                          "the Python rule: %s", firm_id, client_id, at, e)

    marked, lines, reviewed_on = _fetch_unbilled(db, firm_id, client_id, at)
    return ageing.build(_fetch_receivables(db, firm_id, client_id, at),
                        _fetch_payables(db, firm_id, client_id, at),
                        at, _today(), marked, lines, reviewed_on)


# ── Classification ───────────────────────────────────────────────────────────

# What each target may set — the allow-list, and deliberately NOT a table name
# to interpolate into a query. See _write() for why every write below is spelled
# out with literal table names and literal payload keys.
_ALLOWED_FIELDS = {
    "invoice": {"is_disputed", "considered_doubtful"},
    "bill":    {"is_disputed"},
    "vendor":  {"msme_status", "msme_registration_no"},
    # Which GL accounts hold unbilled dues. The database CHECK also refuses a
    # side that does not match the account's own type, so a revenue account
    # cannot be marked at all — see migration 305.
    "account": {"unbilled_dues_side"},
}


def _write(db, target: str, target_id: str, firm_id: str, client_id: str, update: dict):
    """One literal query per target, with the payload written INLINE.

    Verbose on purpose. tests/test_backend_columns_exist_pg.py checks every
    column a query names against the real schema, and it can only read a query
    whose table name and payload keys are both string constants — a table name
    held in a variable, or a payload dict built above the call, is invisible to
    it, which is how a column the schema does not have reaches production.
    (The example is not written out here: the checker parses THIS file too, and
    a plausible-looking table name in a docstring is reported as real schema
    drift. It was, the first time.) The same file's budget comment
    records the last person to hit this and choose the same way: they inlined
    two inserts rather than raise the budget, and the twelve columns those write
    are checked because of it.

    So the branches enumerate which fields were actually sent, and every column
    name below is a literal this check can see. Firm AND client scoped on every
    branch — the service-role key bypasses RLS, so this filter is the isolation.
    """
    if target == "invoice":
        if "is_disputed" in update and "considered_doubtful" in update:
            return (db.table("client_sales_invoices")
                    .update({"is_disputed": update["is_disputed"],
                             "considered_doubtful": update["considered_doubtful"]})
                    .eq("id", target_id).eq("firm_id", firm_id).eq("client_id", client_id)
                    .execute())
        if "is_disputed" in update:
            return (db.table("client_sales_invoices")
                    .update({"is_disputed": update["is_disputed"]})
                    .eq("id", target_id).eq("firm_id", firm_id).eq("client_id", client_id)
                    .execute())
        return (db.table("client_sales_invoices")
                .update({"considered_doubtful": update["considered_doubtful"]})
                .eq("id", target_id).eq("firm_id", firm_id).eq("client_id", client_id)
                .execute())

    if target == "account":
        return (db.table("chart_of_accounts")
                .update({"unbilled_dues_side": update["unbilled_dues_side"]})
                .eq("id", target_id).eq("firm_id", firm_id).eq("client_id", client_id)
                .execute())

    if target == "bill":
        return (db.table("purchase_bills")
                .update({"is_disputed": update["is_disputed"]})
                .eq("id", target_id).eq("firm_id", firm_id).eq("client_id", client_id)
                .execute())

    # A registration number is EVIDENCE for a classification, so it never
    # travels without one — classify() refuses that combination before we get
    # here, which is also what keeps this branch's payload literal.
    if "msme_registration_no" in update:
        return (db.table("vendors")
                .update({"msme_status": update["msme_status"],
                         "msme_registration_no": update["msme_registration_no"]})
                .eq("id", target_id).eq("firm_id", firm_id).eq("client_id", client_id)
                .execute())
    return (db.table("vendors")
            .update({"msme_status": update["msme_status"]})
            .eq("id", target_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .execute())


def classify(db, firm_id: str, client_id: str, target: str, target_id: str,
             fields: dict) -> dict:
    """Record one classification. Firm AND client scoped on every write — the
    service-role key bypasses RLS, so this filter is the isolation.

    Only the fields the note needs, and only on the row named. A caller cannot
    reach an amount, a date or a status through here."""
    allowed = _ALLOWED_FIELDS.get(target)
    if allowed is None:
        raise HTTPException(
            status_code=422,
            detail=f"target must be one of {sorted(_ALLOWED_FIELDS)}, got {target!r}")
    if not target_id:
        raise HTTPException(status_code=422, detail="target_id is required")

    unknown = set(fields) - allowed
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"{target} accepts only {sorted(allowed)}; got {sorted(unknown)}")
    if not fields:
        raise HTTPException(status_code=422, detail="nothing to set")
    if "msme_registration_no" in fields and "msme_status" not in fields:
        raise HTTPException(
            status_code=422,
            detail="msme_registration_no is the evidence for a classification and "
                   "cannot be recorded without msme_status")

    update: dict = {}
    for k, v in fields.items():
        if k == "msme_status":
            # None is a legitimate value here: a CA who classified a vendor by
            # mistake must be able to put them back into the gap rather than
            # leave a guess standing, because s.43B(h) turns the guess into a
            # disallowance.
            if v is not None and v not in ageing.MSME_STATUSES:
                raise HTTPException(
                    status_code=422,
                    detail=f"msme_status must be null or one of "
                           f"{list(ageing.MSME_STATUSES)}; got {v!r}. Micro and "
                           f"small are row (i) of the Schedule III payables "
                           f"ageing schedule; medium is Others (MSMED s.22, s.2(n)).")
            update[k] = v
        elif k == "unbilled_dues_side":
            # None is the un-marking, and it has to stay available: an account
            # marked by mistake would otherwise be stuck in a statutory
            # disclosure with no way out.
            if v is not None and v not in ageing.UNBILLED_SIDES:
                raise HTTPException(
                    status_code=422,
                    detail=f"unbilled_dues_side must be null or one of "
                           f"{list(ageing.UNBILLED_SIDES)}; got {v!r}. "
                           f"'receivable' is an ASSET balance (accrued income, "
                           f"unbilled revenue); 'payable' is a LIABILITY balance "
                           f"(accrued expenses, goods received not invoiced).")
            update[k] = v
        elif k == "msme_registration_no":
            update[k] = (str(v).strip() or None) if v is not None else None
        else:
            update[k] = bool(v)

    if db is None:
        raise HTTPException(status_code=503,
                            detail="No database configured — a classification cannot be recorded")

    res = _write(db, target, target_id, firm_id, client_id, update)
    if not getattr(res, "data", None):
        raise HTTPException(status_code=404,
                            detail=f"{target} {target_id} not found for this client")
    return {"target": target, "target_id": target_id, "set": update}


# ── The unbilled-dues review ─────────────────────────────────────────────────

def review_unbilled(db, firm_id: str, client_id: str, reviewed: bool,
                    note: Optional[str] = None,
                    actor_id: Optional[str] = None) -> dict:
    """Record — or withdraw — the statement that somebody has been through this
    client's chart of accounts and marked every account holding unbilled dues.

    This is what turns the disclosure from absent into a figure, and it is a
    separate act from the marking on purpose. Marking accounts says "these hold
    unbilled dues". Only this says "and there are no others" — which is the
    assertion the note actually makes, and the one that lets a nil be printed.
    A client with genuinely none records the review and marks nothing.

    `reviewed=False` deletes the row and puts the disclosure back into its gap,
    which is what a CA who no longer stands behind the review needs.
    """
    if db is None:
        raise HTTPException(status_code=503,
                            detail="No database configured — a review cannot be recorded")
    if not client_id:
        raise HTTPException(status_code=422, detail="client_id is required")

    if not reviewed:
        (db.table("schedule_iii_unbilled_reviews").delete()
         .eq("firm_id", firm_id).eq("client_id", client_id).execute())
        return {"reviewed": False, "reviewed_on": None, "note": None}

    # IST, per CLAUDE.md: the date goes onto a note a CA signs, and the column
    # is a date rather than a timestamp so there is no question which day a
    # late-evening review belongs to.
    on = ist_today().isoformat()
    text = (note or "").strip() or None
    # Payload written INLINE with literal keys — see _write() for why.
    db.table("schedule_iii_unbilled_reviews").upsert(
        {"firm_id": firm_id, "client_id": client_id, "reviewed_on": on,
         "reviewed_by": actor_id, "note": text,
         "updated_at": datetime.now(timezone.utc).isoformat()},
        on_conflict="firm_id,client_id").execute()
    return {"reviewed": True, "reviewed_on": on, "note": text}
