"""The four lists the TDS screen shows for one client, as windows the server cuts and counts (POST-A-276).

WHAT THIS REPLACES
    The screen read `tds_deductions`, `tds_challans`, `tds_returns` and `tds_certificates` straight from the database in the
    browser (the frontend's second data path), where `rbac()` and the assignment scope never run, and then worked out its footer,
    its "Returns Due" and "Certificates Pending" cards and the Overdue split of the Returns tab over whatever it had paged in.
    The four endpoints in `routers/tds_workspace` existed beside it and nothing called them: they returned a bare array, in no
    stated order, with no word on whether more rows existed.

WHAT EACH ANSWER IS
    A WINDOW: the rows in a stated total order (the day, latest first, and the id, so two requests never repeat or skip a row), the
    server's `has_more` (one row more than the window is read, `core.list_window`), `limit` and `max_limit`. Beside the rows, the
    figures the screen shows over them, taken over ALL of the client's rows by `domain/tds/screen_counts` and not over the window,
    so a list that stops at a number never makes a total or a count shorter than the truth.

    The figures are read with the narrow columns they need (`core.db_paging.fetch_all`, keyset), so a client with a long history
    costs a few small pages and not the whole table.

`financial_year` narrows the deductions to one year (POST-A-294): the register is listed whole and sorted and searched in the browser, so a
client with a long history passes the ceiling below, and the older rows were then unreachable from the screen. The totals narrow with
the rows, as they do for a quarter, so a footer never describes rows the table does not hold. Every writer of a deduction sets the
column (migration 263 backfilled the rest), and the (firm, client, financial year) index serves the filter.

`TDS_LIST_MAX` is the ceiling one read may ask for. The screen lists a client's register whole and searches and sorts it in the
browser, so it asks for the ceiling, as the entity register does; it is the one browser-side copy of this number
(`TDS_REGISTER_WINDOW_MAX` in `lib/lists/window.ts`), and a test holds the two equal.
"""
from __future__ import annotations

from typing import Callable, Optional

from core.db_paging import fetch_all, fetch_window
from core.ist_clock import ist_today
from core.list_window import probe, split
from domain.tds import screen_counts

TDS_LIST_MAX = 2000


def _window(rows: list, limit: int, has_more: bool, rows_field: str, **extra) -> dict:
    return {rows_field: rows, "has_more": has_more, "limit": limit, "max_limit": TDS_LIST_MAX, **extra}


def _sorted_latest_first(rows: list, field: str) -> list:
    """`field` descending and then the id ascending: the order the database is asked for, for the in-memory store."""
    ordered = sorted(rows, key=lambda r: str(r.get("id") or ""))
    return sorted(ordered, key=lambda r: str(r.get(field) or ""), reverse=True)


def _cut(rows: list, limit: int, offset: int) -> tuple[list, bool]:
    return split(rows[offset:offset + probe(limit)], limit)


def _read_window(base: Callable, order_field: str, limit: int, offset: int) -> tuple[list, bool]:
    """One window of the query `base()` builds (a fresh builder each call, with its firm and client filters on it), in the stated
    total order: `order_field` descending and then the id. `core.db_paging.fetch_window` reads it in requests the server will honour
    (PostgREST answers at most `PAGE` rows to one request and says nothing when it cuts one short), and `split` takes the probe row
    off and reports whether more existed."""
    return split(fetch_window(base, order_field, count=probe(limit), start=offset), limit)


# ── deductions ───────────────────────────────────────────────────────────────

def deductions(db, firm_id: str, client_id: str, *, quarter: Optional[str], limit: int, offset: int,
               financial_year: Optional[str] = None) -> dict:
    def narrow(q):
        if financial_year:
            q = q.eq("financial_year", financial_year)
        return q.eq("quarter", quarter) if quarter else q
    rows, has_more = _read_window(
        lambda: narrow(db.table("tds_deductions").select("*").eq("firm_id", firm_id).eq("client_id", client_id)),
        "transaction_date", limit, offset)
    every = fetch_all(lambda: narrow(db.table("tds_deductions").select("id, payment_amount_paise, tds_paise")
                                     .eq("firm_id", firm_id).eq("client_id", client_id)),
                      label="tds.lists.deductions")
    return _window(rows, limit, has_more, "deductions", totals=screen_counts.deduction_totals(every))


def deductions_in_memory(all_rows: list, *, quarter: Optional[str], limit: int, offset: int,
                         financial_year: Optional[str] = None) -> dict:
    rows = [d for d in all_rows
            if (not quarter or d.get("quarter") == quarter) and (not financial_year or d.get("financial_year") == financial_year)]
    window, has_more = _cut(_sorted_latest_first(rows, "transaction_date"), limit, offset)
    return _window(window, limit, has_more, "deductions", totals=screen_counts.deduction_totals(rows))


# ── challans ─────────────────────────────────────────────────────────────────

def challans(db, firm_id: str, client_id: str, *, from_date: Optional[str], to_date: Optional[str], limit: int, offset: int) -> dict:
    def narrow(q):
        if from_date:
            q = q.gte("payment_date", from_date)
        if to_date:
            q = q.lte("payment_date", to_date)
        return q
    rows, has_more = _read_window(
        lambda: narrow(db.table("tds_challans").select("*").eq("firm_id", firm_id).eq("client_id", client_id)),
        "payment_date", limit, offset)
    # A challan tied to a ledger entry says whether that entry still records the payment (POST-A-272): a posted entry is reversed or
    # soft-deleted, never hard-deleted, so the link outlives it.
    from services import tds_challan_ledger_service as ledger_link
    ledger_link.annotate_links(db, firm_id=firm_id, client_id=client_id, rows=rows)
    return _window(rows, limit, has_more, "challans")


def challans_in_memory(all_rows: list, *, from_date: Optional[str], to_date: Optional[str], limit: int, offset: int) -> dict:
    rows = [c for c in all_rows
            if (not from_date or str(c.get("payment_date") or "") >= from_date)
            and (not to_date or str(c.get("payment_date") or "") <= to_date)]
    window, has_more = _cut(_sorted_latest_first(rows, "payment_date"), limit, offset)
    return _window(window, limit, has_more, "challans")


# ── returns ──────────────────────────────────────────────────────────────────

def returns(db, firm_id: str, client_id: str, *, limit: int, offset: int) -> dict:
    rows, has_more = _read_window(
        lambda: db.table("tds_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id), "due_date", limit, offset)
    every = fetch_all(lambda: db.table("tds_returns").select("id, status, due_date").eq("firm_id", firm_id).eq("client_id", client_id),
                      label="tds.lists.returns")
    return _window(rows, limit, has_more, "returns", counts=screen_counts.return_counts(every, today=ist_today()))


def returns_in_memory(all_rows: list, *, limit: int, offset: int) -> dict:
    window, has_more = _cut(_sorted_latest_first(all_rows, "due_date"), limit, offset)
    return _window(window, limit, has_more, "returns", counts=screen_counts.return_counts(all_rows, today=ist_today()))


# ── certificates ─────────────────────────────────────────────────────────────

def certificates(db, firm_id: str, client_id: str, *, limit: int, offset: int) -> dict:
    rows, has_more = _read_window(
        lambda: db.table("tds_certificates").select("*").eq("firm_id", firm_id).eq("client_id", client_id), "created_at", limit, offset)
    every = fetch_all(lambda: db.table("tds_certificates").select("id, status").eq("firm_id", firm_id).eq("client_id", client_id),
                      label="tds.lists.certificates")
    return _window(rows, limit, has_more, "certificates", counts=screen_counts.certificate_counts(every))


def certificates_in_memory(all_rows: list, *, limit: int, offset: int) -> dict:
    window, has_more = _cut(_sorted_latest_first(all_rows, "created_at"), limit, offset)
    return _window(window, limit, has_more, "certificates", counts=screen_counts.certificate_counts(all_rows))


# ── §197 lower-deduction certificates (POST-A-293) ───────────────────────────

#: What the §197 tab shows of a certificate. Narrow on purpose: the row is the certificate's own facts and nothing the screen does not draw.
LOWER_DEDUCTION_COLUMNS = "id, vendor_id, section, certificate_no, rate_bps, valid_from, valid_to, ceiling_paise, notes"


def lower_deduction_certificates(db, firm_id: str, client_id: str, *, limit: int, offset: int) -> dict:
    """A client's §197 certificates, the latest validity first and then the id, as a window under `lower_deduction_certificates`,
    with `vendors`: the client's active suppliers (`id`, `name`) the certificate form offers, read in full in keyset pages and not
    cut at the window."""
    rows, has_more = _read_window(
        lambda: db.table("tds_lower_deduction_certificates").select(LOWER_DEDUCTION_COLUMNS)
        .eq("firm_id", firm_id).eq("client_id", client_id), "valid_from", limit, offset)
    vendors = fetch_all(lambda: db.table("vendors").select("id, name").eq("firm_id", firm_id).eq("client_id", client_id)
                        .eq("is_active", True), label="tds.lists.lower_deduction_vendors")
    return _window(rows, limit, has_more, "lower_deduction_certificates",
                   vendors=sorted(({"id": v["id"], "name": v.get("name")} for v in vendors), key=lambda v: (str(v["name"] or ""), v["id"])))


def lower_deduction_certificates_in_memory(all_rows: list, *, limit: int, offset: int, vendors: list | None = None) -> dict:
    window, has_more = _cut(_sorted_latest_first(all_rows, "valid_from"), limit, offset)
    return _window(window, limit, has_more, "lower_deduction_certificates",
                   vendors=sorted(({"id": v["id"], "name": v.get("name")} for v in (vendors or [])),
                                  key=lambda v: (str(v["name"] or ""), v["id"])))
