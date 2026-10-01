"""The GST registrations a client holds — reads and writes (GST-20).

`domain/gst/registrations.py` is the rule; this fetches its inputs and writes.
Nothing here decides which registration a return belongs to or whether a GSTIN
is well formed.

TWO TABLES, ONE ANSWER. The PRIMARY registration is `clients.gstin` and stays
there — see the domain module's header for why a cache of it would drift — so
every read here fetches the client row AND the additional rows and hands both
to `all_registrations`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from domain.gst import registrations as reg

_logger = logging.getLogger("caflow.client_gst_registrations")

#: What the client row has to carry for `primary_of` to build the primary.
#: `gst_registration_type`/`composition_category` (migration 420, GST-25) are
#: what let the PRIMARY registration be composition — a narrow select that
#: omits them makes `registrations.primary_of()`'s read of them a silent
#: no-op, exactly the trap this file's own header warns every other domain
#: module against.
CLIENT_COLUMNS = (
    "id, firm_id, client_name, legal_name, gstin, state_code, "
    "gst_filing_frequency, gst_registration_date, gst_registration_type, "
    "composition_category"
)

#: Every column of an additional registration. Named once so a read that omits
#: one cannot hand the rule a default it did not mean.
REGISTRATION_COLUMNS = (
    "id, firm_id, client_id, gstin, state_code, registration_type, "
    "filing_frequency, trade_name, address_line1, address_line2, city, "
    "pincode, effective_from, effective_to, notes, created_at, deleted_at, "
    "composition_category"
)


def _first(rows) -> Optional[dict]:
    rows = rows or []
    return rows[0] if rows else None


def _client(db, firm_id: str, client_id: str) -> dict:
    # Inlined rather than reading CLIENT_COLUMNS by name — the schema-safety
    # scanner (tests/test_backend_columns_exist_pg.py) resolves a literal
    # .select() string and nothing reached through a variable, so a projection
    # built from the constant would be invisible to it.
    row = _first(db.table("clients").select(
        "id, firm_id, client_name, legal_name, gstin, state_code, "
        "gst_filing_frequency, gst_registration_date, gst_registration_type, "
        "composition_category")
        .eq("id", client_id).eq("firm_id", firm_id).limit(1).execute().data)
    if not row:
        raise HTTPException(status_code=404, detail="Client not found.")
    return row


def _rows(db, firm_id: str, client_id: str) -> list[dict]:
    return fetch_all(
        lambda: db.table("client_gst_registrations").select(
            "id, firm_id, client_id, gstin, state_code, registration_type, "
            "filing_frequency, trade_name, address_line1, address_line2, city, "
            "pincode, effective_from, effective_to, notes, created_at, "
            "deleted_at, composition_category")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .is_("deleted_at", "null"),
        key="id", label="client_gst_registrations")


def listing(db, firm_id: str, client_id: str) -> list[dict]:
    """Every registration this client holds, primary first."""
    client = _client(db, firm_id, client_id)
    out = []
    held_here = reg.all_registrations(client, _rows(db, firm_id, client_id))
    for r in held_here:
        out.append({
            "id": r.id,
            "gstin": r.gstin,
            "state_code": r.state_code,
            "registration_type": r.registration_type,
            "composition_category": r.composition_category,
            "filing_frequency": r.filing_frequency,
            "is_primary": r.is_primary,
            "trade_name": r.trade_name,
            "effective_from": r.effective_from,
            "effective_to": r.effective_to,
            "label": r.label,
            "files_gstr1_and_3b": r.files_gstr1_and_3b,
            # A boolean, the same shape as files_gstr1_and_3b, so the screen
            # never has to hardcode the word "composition" to decide whether
            # to offer the CMP-08 panel.
            "files_cmp08": r.files_cmp08,
            # Same shape again — whether this registration owes GSTR-8, never
            # a "tcs_collector" string comparison in the browser (GST-25).
            "files_gstr8": r.files_gstr8,
            # Same shape again — GSTR-4 Annual, filed by the same COMPOSITION
            # registrations that file CMP-08 (GST-25, migration 422).
            "files_gstr4_annual": r.files_gstr4_annual,
            # The refusal is DATA, so a screen can grey the return out and say
            # which form this registration actually owes.
            "other_return_form": reg.OTHER_RETURN_FORMS.get(r.registration_type),
            # WHAT BUILDING A RETURN FOR THIS REGISTRATION WOULD HAVE TO SAY
            # (GST-17, GST-05). A registration picker invites a CA to choose
            # which GSTIN to prepare, and no invoice, bill or note records which
            # registration it belongs to — so the choice does not filter a
            # thing. The sentence is carried HERE, where the choice is made,
            # from the in-memory list already read (no further query), and is
            # None where the client holds one registration that files the
            # ordinary pair. `registrations.documents_not_split_caveat` is the
            # one place it is worded; GST-16 retires it.
            "documents_not_split_caveat": reg.documents_not_split_caveat(
                held_here, r.gstin),
        })
    return out


def held(db, firm_id: str, client_id: str) -> list[reg.Registration]:
    """Every registration this client holds, primary first, as the domain type.

    For a caller that has to ask "is THIS GSTIN one of theirs" of something it
    read off a document rather than off a request (gst-09: the recipient GSTIN
    of an uploaded GSTR-2B). An EMPTY list is an answer — the client has none —
    and is not the same as not having asked.
    """
    client = _client(db, firm_id, client_id)
    return reg.all_registrations(client, _rows(db, firm_id, client_id))


def resolve(db, firm_id: str, client_id: str,
            gstin: Optional[str] = None) -> reg.Registration:
    """Which registration a request means — the compute paths' one entry point.

    Raises 422 rather than falling back to the primary when the GSTIN is not one
    the client holds: filing one registration's return under another's number is
    the failure this feature exists to prevent.
    """
    client = _client(db, firm_id, client_id)
    try:
        return reg.resolve(client, _rows(db, firm_id, client_id), gstin)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


def documents_not_split_caveat(db, firm_id: str, client_id: str,
                               gstin: Optional[str]) -> Optional[str]:
    """`reg.documents_not_split_caveat` over this client's registrations.

    A client row that is not there answers None rather than raising: the router
    has already resolved the registration by the time a return is being built,
    so a 404 here can only be a caller with no client to ask about, and it must
    not take a return down over a caveat. Every OTHER failure propagates — a
    failed read that silently answered "no caveat" would be the false clean
    result this function exists to prevent.
    """
    try:
        client = _client(db, firm_id, client_id)
    except HTTPException as e:
        if e.status_code == 404:
            return None
        raise
    return reg.documents_not_split_caveat(
        reg.all_registrations(client, _rows(db, firm_id, client_id)), gstin)


def create(db, firm_id: str, client_id: str, *, gstin: str,
           state_code: Optional[str] = None,
           registration_type: str = reg.REGULAR,
           filing_frequency: str = reg.MONTHLY,
           trade_name: Optional[str] = None,
           address_line1: Optional[str] = None,
           address_line2: Optional[str] = None,
           city: Optional[str] = None,
           pincode: Optional[str] = None,
           effective_from: Optional[str] = None,
           effective_to: Optional[str] = None,
           notes: Optional[str] = None,
           composition_category: Optional[str] = None,
           actor_id: Optional[str] = None) -> dict:
    """Record an additional registration."""
    client = _client(db, firm_id, client_id)
    value = (gstin or "").strip().upper()
    refusal = reg.problem_with_new(
        client, _rows(db, firm_id, client_id), gstin=value,
        state_code=state_code, registration_type=registration_type,
        filing_frequency=filing_frequency,
        composition_category=composition_category)
    if not refusal.ok:
        raise HTTPException(status_code=422, detail=" ".join(refusal.reasons))

    rows = db.table("client_gst_registrations").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "gstin": value,
        # DERIVED, never taken from the caller. The column's CHECK requires it
        # to equal the GSTIN's first two characters, and a caller-supplied
        # value that disagrees has already been refused above — so deriving it
        # here means the two can never be out of step by a path that forgot.
        "state_code": reg.state_code_of(value),
        "registration_type": registration_type,
        "filing_frequency": filing_frequency,
        "trade_name": trade_name,
        "address_line1": address_line1,
        "address_line2": address_line2,
        "city": city,
        "pincode": pincode,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "notes": notes,
        "composition_category": composition_category,
        "created_by": actor_id,
    }).execute().data or []
    return rows[0] if rows else {}


def close(db, firm_id: str, registration_id: str, *, client_id: str,
          effective_to: str) -> dict:
    """Record a s.29 cancellation or surrender.

    NOT a delete. A cancelled registration still owes the returns for every
    period it was live, and the GSTR-1 and GSTR-3B rows already filed under it
    are keyed on its GSTIN.

    `client_id` is REQUIRED and is part of the match, not decoration. The
    router writes through the service role (authenticated holds only SELECT on
    this table), so RLS no longer stands between a caller and another client's
    row; what does is that the router asserted access to THIS client and the
    update refuses to touch a row belonging to any other. Matching on id and
    firm alone let an Executive assigned to one client close a registration
    of a client they are not assigned to. A mismatch is the same 404 as an
    absent row, so the answer says nothing about what exists elsewhere.
    """
    rows = (db.table("client_gst_registrations")
            .update({"effective_to": effective_to,
                     "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", registration_id).eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Registration not found.")
    return rows[0]


def _refuse_withdraw(form: str, gstin) -> None:
    """One sentence, said the same way whichever return was found."""
    raise HTTPException(
        status_code=409,
        detail=(f"A {form} has been prepared under {gstin}, so this "
                f"registration cannot be removed. If the registration has been "
                f"cancelled or surrendered, record the date it ended instead — "
                f"the returns for the periods it was live are still owed."))


def withdraw(db, firm_id: str, registration_id: str, *, client_id: str) -> dict:
    """Remove a registration recorded in error.

    REFUSED once any return has been prepared under it — those rows are keyed
    on the GSTIN, and removing the registration would leave them pointing at a
    number the client is no longer recorded as holding. A registration that was
    real and has ended is `close`, not this.

    `client_id` is required and matched on both the read and the update, for
    `close`'s reason: the write runs under the service role, and the client the
    router asserted access to is the only thing tying the row to the caller.
    """
    row = _first(db.table("client_gst_registrations").select(
        "id, firm_id, client_id, gstin, state_code, registration_type, "
        "filing_frequency, trade_name, effective_from, effective_to, deleted_at")
        .eq("id", registration_id).eq("firm_id", firm_id)
        .eq("client_id", client_id).limit(1).execute().data)
    if not row or row.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Registration not found.")

    # BOTH TABLE NAMES ARE LITERALS rather than a loop variable. The column
    # scan (`tests/_backend_query_parser`) resolves neither a dynamic table nor
    # a computed column, so a loop here would make every filter in it invisible
    # to the check — and these two reads are what decide whether a registration
    # may be removed at all.
    # The row was matched on client_id above, so the asserted client IS the
    # row's own and the two return reads below scope by it directly.
    gstin = row.get("gstin")
    if (db.table("gstr1_returns").select("id, gstin, client_id")
            .eq("client_id", client_id).eq("gstin", gstin)
            .limit(1).execute().data):
        _refuse_withdraw("GSTR-1", gstin)
    if (db.table("gstr3b_returns").select("id, gstin, client_id")
            .eq("client_id", client_id).eq("gstin", gstin)
            .limit(1).execute().data):
        _refuse_withdraw("GSTR-3B", gstin)

    rows = (db.table("client_gst_registrations")
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", registration_id).eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .execute().data) or []
    return rows[0] if rows else row
