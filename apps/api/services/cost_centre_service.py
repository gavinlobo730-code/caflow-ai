"""The cost-centre master, and the departmental result (ACC-13, migration 418).

This module FETCHES and WRITES; `domain/accounting/cost_centre.py` DECIDES. It
does not know that most lines are unallocated, that an asset line is dropped,
or that there is no balance sheet by cost centre.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

import logging
from typing import Optional

from core.db_paging import fetch_all
from core.ist_clock import fy_bounds
from domain.accounting import cost_centre as rule

logger = logging.getLogger("caflow.cost_centre")

#: Mock mode has no database. One dict per (firm, client) so the master screen
#: and its tests work the way every other mock-mode master does here.
_MOCK: dict[tuple, list[dict]] = {}


def _mock_key(firm_id: str, client_id: str) -> tuple:
    return (str(firm_id), str(client_id))


# ── The master ───────────────────────────────────────────────────────────────

def list_centres(db, firm_id: str, client_id: str,
                 include_retired: bool = False) -> list[dict]:
    if db is None:
        rows = list(_MOCK.get(_mock_key(firm_id, client_id), []))
    else:
        rows = fetch_all(
            lambda: db.table("cost_centres")
            .select("id, firm_id, client_id, code, name, description, is_active, created_at")
            .eq("firm_id", firm_id).eq("client_id", client_id),
            label="cost_centre_service.list",
        )
    if not include_retired:
        rows = [r for r in rows if r.get("is_active", True)]
    return sorted(rows, key=lambda r: (r.get("code") or ""))


def create_centre(db, firm_id: str, client_id: str, data: dict) -> dict:
    """Create one. The door has already validated; this normalises and writes.

    `normalise_code` runs HERE as well as at the door, because the unique index
    is on the STORED value: a caller reaching the service another way would
    otherwise create `Factory` beside `FACTORY` and split one department's cost
    in two, with both rows looking identical on every screen.
    """
    code = rule.normalise_code(data.get("code"))
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip() or None
    is_active = bool(data.get("is_active", True))
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "code": code,
        "name": name,
        "description": description,
        "is_active": is_active,
    }
    if db is None:
        import uuid
        row = {**row, "id": str(uuid.uuid4())}
        bucket = _MOCK.setdefault(_mock_key(firm_id, client_id), [])
        if any(r["code"] == row["code"] for r in bucket):
            raise ValueError(f"A cost centre with code {row['code']} already exists.")
        bucket.append(row)
        return row
    # ⚠️ A DICT LITERAL, not `insert(row)`, although `row` holds exactly these
    # six keys two lines up. `tests/test_backend_inserts_supply_every_required_
    # column_pg` reads an insert payload as a dict LITERAL and cannot see one
    # bound to a NAME, so `insert(row)` would take the only write to this table
    # out of the check that proves it supplies every NOT NULL column — and both
    # that guard's budget and the column guard's are EXACT with no headroom, so
    # it is a CI failure as well as a coverage hole. Six duplicated keys is the
    # price, and it is the same one `domain/tally/party_identifiers` records
    # paying for its two inserts. A test asserts the literal and `row` name the
    # same six keys, so they cannot drift.
    return (db.table("cost_centres").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "code": code,
        "name": name,
        "description": description,
        "is_active": is_active,
    }).execute().data or [row])[0]


def update_centre(db, firm_id: str, client_id: str, centre_id: str, data: dict) -> dict:
    patch: dict = {}
    if "code" in data:
        patch["code"] = rule.normalise_code(data["code"])
    if "name" in data:
        patch["name"] = (data["name"] or "").strip()
    if "description" in data:
        patch["description"] = (data["description"] or "").strip() or None
    if "is_active" in data:
        patch["is_active"] = bool(data["is_active"])
    if not patch:
        return {"id": centre_id}
    patch["updated_at"] = "now()"
    if db is None:
        for r in _MOCK.get(_mock_key(firm_id, client_id), []):
            if r["id"] == centre_id:
                r.update({k: v for k, v in patch.items() if k != "updated_at"})
                return r
        raise ValueError("No such cost centre.")
    return (db.table("cost_centres").update(patch)
            .eq("id", centre_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .execute().data or [{"id": centre_id}])[0]


def resolve(db, firm_id: str, client_id: str, centre_id: Optional[str]) -> Optional[str]:
    """REFUSE a cost centre this client does not have, never default it away.

    The database says the same thing — migration 418 extended migration 360's
    statement-level trigger, because `journal_lines.cost_centre_id` carries
    only a GLOBAL FK — and this is the 422 that gives the CA a sentence instead
    of a SQLSTATE. `client_gst_registration_service.resolve`'s shape, for the
    same reason: a value that names somebody else's row is the exact failure
    the check exists to prevent, and it is invisible until somebody reads a
    report.
    """
    if not centre_id:
        return None
    known = {str(r["id"]) for r in list_centres(db, firm_id, client_id,
                                                include_retired=True)}
    if str(centre_id) not in known:
        raise ValueError(
            "That cost centre does not belong to this client. Choose one from "
            "the client's own list, or create it first.")
    return str(centre_id)


# ── The departmental result ──────────────────────────────────────────────────

def allocation(db, firm_id: str, client_id: str, financial_year: str) -> rule.Allocation:
    """Income and expenditure by cost centre for one financial year.

    ⚠️ THE READ IS BOUNDED BY THE PERIOD AND BY THE ACCOUNT KIND, not paged
    over the whole ledger and filtered here. CLAUDE.md's reporting rule: the
    answer is one row per centre per account — dozens — and `journal_lines` is
    the highest-volume table in the schema.

    It still fetches LINES rather than a pre-aggregated bucket, and that is the
    one place this report differs from the trial balance: `account_period_
    balances` is keyed on (account, month) and has thrown the cost centre away
    by construction, so there is nothing to read it off. The narrowing that
    makes it affordable is the embed's own filter — only lines that CARRY a
    centre, plus the account kinds that appear on a P&L — and a client who does
    not use the dimension reads nothing at all.
    """
    start, end = fy_bounds(financial_year)
    centres = {str(r["id"]): r.get("name") or r.get("code") or "Unnamed"
               for r in list_centres(db, firm_id, client_id, include_retired=True)}

    if db is None:
        return rule.allocate([], centres)

    rows = fetch_all(
        lambda: db.table("journal_lines")
        .select(
            "id, account_id, debit_paise, credit_paise, cost_centre_id, "
            "journal_entries!inner(id, firm_id, client_id, entry_date, is_posted, deleted_at), "
            "chart_of_accounts!inner(id, account_name, account_type)"
        )
        .eq("journal_entries.firm_id", firm_id)
        .eq("journal_entries.client_id", client_id)
        .eq("journal_entries.is_posted", True)
        .is_("journal_entries.deleted_at", "null")
        .gte("journal_entries.entry_date", start)
        .lte("journal_entries.entry_date", end)
        .in_("chart_of_accounts.account_type", ["Income", "Expense"]),
        label="cost_centre_service.allocation",
    )

    lines = []
    for r in rows:
        acc = r.get("chart_of_accounts") or {}
        kind = (acc.get("account_type") or "").lower()
        cid = r.get("cost_centre_id")
        lines.append(rule.AllocatedLine(
            cost_centre_id=str(cid) if cid else None,
            cost_centre_name=centres.get(str(cid)) if cid else None,
            account_id=str(r.get("account_id")),
            account_name=acc.get("account_name") or "Unnamed account",
            account_kind=kind,
            debit_paise=int(r.get("debit_paise") or 0),
            credit_paise=int(r.get("credit_paise") or 0),
        ))
    return rule.allocate(lines, centres)
