"""
Fetch what `domain/gst/irn_worklist` needs, and answer it (GST-20).

The RULES — who owes an IRN, what the IRP's window is, what each state means —
are `irn_scope` and `irn_worklist`. This module is the reads, and it has one
job beyond them: keeping what crosses the wire proportional to the ANSWER and
not to the ledger (CLAUDE.md, "Reporting performance"). Four things do that.

  1. CLIENTS ARE PRE-SORTED ON THEIR RECORDED TURNOVER, before any invoice is
     read. `client_gst_turnover` is one row per client per year — small — and a
     client whose recorded turnover never exceeded the LOWEST Rule 48(4)
     threshold is outside the rule on every invoice date, so its invoices are
     never fetched. A client with NO recorded turnover is not assessed either in
     the firm-wide list: strict reading of an unknown would put every B2B
     invoice of every unrecorded client on the list, burying the clients that
     really are over the line. They are NAMED instead, with what to do, which is
     the truthful form of "cannot tell" — and the per-client view, where the CA
     is looking at that one client, DOES list them, flagged.
  2. THE LOOK-BACK IS BOUNDED (`irn_worklist.DEFAULT_LOOKBACK_DAYS`) and the
     answer says what it covered. `since` widens it.
  3. THE E-INVOICE RECORDS ARE READ BY DATE for the same clients, and only the
     invoices that then LOOK like they have none are confirmed by id — a small
     second read, rather than one that grows with every invoice a large client
     ever raised.
  4. NOTHING IS PAGED BY HAND: `fetch_all_in` is the one chunked, keyset helper.

THE FIRM FILTER IS ON EVERY READ and a caller's scope is `effective_client_ids`:
None means the whole firm and an EMPTY set means nothing, never "no filter".

# CA REVIEW REQUIRED — this lists invoices. It generates no IRN and reaches no
# portal.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from core.db_paging import fetch_all, fetch_all_in
from core.ist_clock import ist_today
from domain.accounting import opening_documents as _opening
from domain.gst import irn_scope, irn_worklist as wl
from services import gst_return_service

#: A cap on what is RETURNED, not on what is considered: the counts are over
#: every invoice found, and `truncated` says the list was cut.
MAX_ROWS = 500

# NOT its own list: the invoices that count as issued are the ones the returns
# are built from, and a status added there must reach here with no edit.
_ISSUED = gst_return_service._SALES_POSTED

CLIENT_TURNOVER_NOT_RECORDED = (
    "No aggregate turnover is recorded for this client, so whether CGST Rule "
    "48(4) reaches any of its invoices cannot be told — and a guess either way "
    "is expensive. Record it on the client's GST settings (Registrations tab)."
)


def _since(as_at: date, since: Optional[str]) -> str:
    asked = None
    if since:
        try:
            asked = date.fromisoformat(str(since)[:10])
        except ValueError:
            raise ValueError("`since` must be a date as YYYY-MM-DD.")
    return (asked or as_at - timedelta(days=wl.DEFAULT_LOOKBACK_DAYS)).isoformat()


def _clients(db, firm_id: str, only_client: Optional[str],
             scope: Optional[set]) -> dict[str, str]:
    """id -> display name, for the clients this call may see."""
    def make():
        q = db.table("clients").select("id, client_name, legal_name").eq("firm_id", firm_id)
        return q.eq("id", only_client) if only_client else q

    if scope is not None and not only_client:
        rows = fetch_all_in(make, "id", scope, key="id", label="irn_worklist.clients")
    else:
        rows = fetch_all(make, key="id", label="irn_worklist.clients")
    return {str(r["id"]): (r.get("legal_name") or r.get("client_name") or "") for r in rows}


def _turnover_by_client(db, firm_id: str, client_ids) -> dict[str, dict[str, int]]:
    """client id -> {financial year -> recorded aggregate turnover, paise}."""
    rows = fetch_all_in(
        lambda: db.table("client_gst_turnover")
        .select("id, client_id, financial_year, aggregate_turnover_paise")
        .eq("firm_id", firm_id),
        "client_id", client_ids, key="id", label="irn_worklist.turnover")
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        out.setdefault(str(r["client_id"]), {})[str(r["financial_year"])] = int(
            r.get("aggregate_turnover_paise") or 0)
    return out


def _highest_within_rule_48_4(by_year: dict[str, int], invoice_date: str) -> Optional[int]:
    """`client_gst_turnover_service.highest_turnover_within_rule_48_4`'s rule on
    rows already in hand: the MAXIMUM across `irn_scope`'s qualifying years, None
    where none is recorded. Same answer, no further read per invoice."""
    figures = [by_year[fy] for fy in irn_scope.qualifying_financial_years(invoice_date)
               if fy in by_year]
    return max(figures) if figures else None


def worklist(db, firm_id: str, *, client_id: Optional[str] = None,
             scope: Optional[set] = None, since: Optional[str] = None,
             as_at: Optional[date] = None) -> dict:
    """In-scope invoices with no live IRN, oldest first, with the clock."""
    as_at = as_at or ist_today()
    floor = _since(as_at, since)
    names = _clients(db, firm_id, client_id, scope)
    turnover = _turnover_by_client(db, firm_id, list(names))

    lowest_threshold = min(t[1] for t in irn_scope.THRESHOLDS)
    candidates: list[str] = []
    not_assessed: list[dict] = []
    below = 0
    client_status = None
    for cid in sorted(names):
        years = turnover.get(cid) or {}
        if not years:
            if client_id:
                candidates.append(cid)          # the CA is looking at this one
                client_status = "turnover_not_recorded"
            else:
                not_assessed.append({
                    "client_id": cid, "client_name": names[cid],
                    "reason": CLIENT_TURNOVER_NOT_RECORDED})
            continue
        if max(years.values()) <= lowest_threshold:
            below += 1                          # outside Rule 48(4) on every date
            if client_id:
                client_status = "below_threshold"
            continue
        candidates.append(cid)
        if client_id:
            client_status = "assessed"

    base = {
        "as_of": as_at.isoformat(),
        "scope": "client" if client_id else "firm",
        "listed_since": floor,
        "clients_not_assessed": not_assessed,
        "clients_below_threshold": below,
        "client_status": client_status,
        "verified": wl.VERIFIED,
        "ca_review_required": True,   # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    }
    caveats = [wl.WINDOW_SOURCE, wl.WINDOW_TURNOVER_BASIS, wl.NOT_COVERED]
    if not candidates:
        return {**base, "invoices": [], "counts": wl.counts([]),
                "truncated": False, "caveats": caveats}

    # ── The invoices, for the clients that can be in scope ──────────────────
    invoices = _opening.without_carried_over(fetch_all_in(
        lambda: db.table("client_sales_invoices")
        .select("id, client_id, customer_id, invoice_no, invoice_date, status, "
                "total_paise, igst_paise, supply_type, invoice_type, is_opening")
        .eq("firm_id", firm_id).in_("status", list(_ISSUED))
        .gte("invoice_date", floor).is_("deleted_at", "null"),
        "client_id", candidates, key="id", label="irn_worklist.invoices"))

    customer_ids = {str(i["customer_id"]) for i in invoices if i.get("customer_id")}
    customers = {str(c["id"]): c for c in fetch_all_in(
        lambda: db.table("customers").select("id, name, gstin").eq("firm_id", firm_id),
        "id", customer_ids, key="id", label="irn_worklist.customers")}
    for inv in invoices:
        inv["customers"] = customers.get(str(inv.get("customer_id")))

    # ── The e-invoice records for the same clients, by date ─────────────────
    records = fetch_all_in(
        lambda: db.table("einvoice_records")
        .select("id, client_id, sales_invoice_id, invoice_number, status, irn")
        .eq("firm_id", firm_id).gte("invoice_date", floor),
        "client_id", candidates, key="id", label="irn_worklist.records")
    by_id: dict[str, list] = {}
    by_number: dict[tuple, list] = {}
    for r in records:
        if r.get("sales_invoice_id"):
            by_id.setdefault(str(r["sales_invoice_id"]), []).append(r)
        by_number.setdefault((str(r["client_id"]), str(r.get("invoice_number") or "").strip().upper()),
                             []).append(r)

    def matched(inv: dict) -> list:
        # By the invoice it names first, then by the NUMBER — a record may be
        # prepared for an invoice without being linked to it, and invoice
        # numbers are unique per client (migration 151).
        return (by_id.get(str(inv["id"]))
                or by_number.get((str(inv["client_id"]),
                                  str(inv.get("invoice_no") or "").strip().upper()), []))

    # Which invoices LOOK as though they have no live IRN — and only those are
    # confirmed against the table by id, so a record outside the date window
    # (a late-keyed one) cannot make a clean invoice read as missing.
    def aato(inv):
        return _highest_within_rule_48_4(turnover.get(str(inv["client_id"])) or {},
                                         str(inv.get("invoice_date") or ""))

    looks_missing = [i for i in invoices
                     if wl.irn_state(matched(i)) is not None]
    if looks_missing:
        for r in fetch_all_in(
                lambda: db.table("einvoice_records")
                .select("id, client_id, sales_invoice_id, invoice_number, status, irn")
                .eq("firm_id", firm_id),
                "sales_invoice_id", [i["id"] for i in looks_missing],
                key="id", label="irn_worklist.confirm"):
            by_id.setdefault(str(r["sales_invoice_id"]), []).append(r)

    rows = []
    for inv in invoices:
        row = wl.assess_invoice(inv, matched(inv), aato(inv), as_at)
        if row is not None:
            row["client_name"] = names.get(str(inv["client_id"]), "")
            rows.append(row)
    rows = wl.sort_oldest_first(rows)

    # Said ONCE, not per row — every row would otherwise repeat the same
    # sentences. They are `irn_scope`'s own (the first proviso's exempted
    # classes, the unrecorded-turnover reading, a malformed GSTIN), collected
    # off the rows rather than restated here.
    for r in rows:
        for g in r.pop("scope_gaps", []):
            if g not in caveats:
                caveats.append(g)
    if any(r["window"].get("assumed") for r in rows):
        caveats.append(wl.UNKNOWN_TURNOVER_WINDOW)
    if any(r["window"]["status"] == wl.PAST_WINDOW for r in rows):
        caveats.append(wl.PAST_WINDOW_IS_NOT_OURS_TO_DECIDE)

    return {**base, "invoices": rows[:MAX_ROWS], "counts": wl.counts(rows),
            "truncated": len(rows) > MAX_ROWS, "caveats": caveats}
