"""Which ledger accounts a client has used most recently on a journal or a bill line (POST-A-155).

THE ACCOUNT PICKER PUTS THE ACCOUNTS THIS CLIENT USED LAST AT THE TOP, AND THE ORDER IS READ FROM THE CLIENT'S OWN
DOCUMENTS, the rule the customer and supplier pickers follow (`domain/party_recent.py`). A journal line's picker offers
the accounts on the client's newest MANUAL journals (an entry posted by a document always names the same control
accounts, and offering Trade Receivables first to a person typing a journal would be noise); a bill line's picker offers
the expense accounts on the client's newest live bills that were not carried over. The answer is derived, never stored,
and read in a bounded window: the newest WINDOW documents, then all of their lines (paged, so a long bill is not cut), each account once, in the order of the
newest document and, within it, the line's own order. Nothing is pre-selected: the list is reordered and the person
still chooses.
"""
from __future__ import annotations

from typing import Iterable

from core.db_paging import fetch_all_in

#: How many of the client's newest documents are read to find the recent accounts.
WINDOW = 50
#: How many accounts are offered at the top.
DEFAULT_LIMIT = 8
#: Which documents each picker reads. A journal line takes the manual journals, a bill line the purchase bills.
USED_ON = ("journal", "bill")

#: `journal_entries.source_type` of an entry a person typed (services/manual_journal_service.MANUAL_SOURCE).
_MANUAL_SOURCE = "manual"


def recent_account_ids(doc_ids: Iterable[str], lines: Iterable[dict], doc_key: str, account_key: str, order_key: str,
                       limit: int = DEFAULT_LIMIT) -> list[str]:
    """Distinct accounts in the order of the documents (newest first) and, within one document, its lines' order."""
    rank = {str(d): i for i, d in enumerate(doc_ids)}
    ordered = sorted(
        (ln for ln in lines or [] if str(ln.get(doc_key)) in rank and ln.get(account_key)),
        key=lambda ln: (rank[str(ln.get(doc_key))], ln.get(order_key) if ln.get(order_key) is not None else 0,
                        str(ln.get("id") or "")),
    )
    out: list[str] = []
    seen: set[str] = set()
    for ln in ordered:
        aid = str(ln[account_key])
        if aid in seen:
            continue
        seen.add(aid)
        out.append(aid)
        if len(out) >= limit:
            break
    return out


def read_recent_accounts(db, used_on: str, firm_id: str, client_id: str, limit: int = DEFAULT_LIMIT) -> dict:
    """The recent account ids for one client's journal lines or bill lines.

    The documents are read firm and client scoped, newest first, within WINDOW; their lines are then read by the ids
    that scoped read returned (the line tables carry no firm of their own), so no line of another client is reached.
    """
    if used_on == "journal":
        docs = (
            db.table("journal_entries").select("id,created_at")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("source_type", _MANUAL_SOURCE)
            .is_("deleted_at", "null")
            .order("created_at", desc=True).order("id", desc=True)
            .limit(WINDOW)
            .execute()
        ).data or []
        ids = [str(d["id"]) for d in docs]
        lines = fetch_all_in(lambda: db.table("journal_lines").select("id,journal_entry_id,account_id,line_order"),
                             "journal_entry_id", ids, label="recent_accounts.journal_lines")
        out = recent_account_ids(ids, lines, "journal_entry_id", "account_id", "line_order", limit)
    elif used_on == "bill":
        docs = (
            db.table("purchase_bills").select("id,created_at")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("is_opening", False)
            .is_("deleted_at", "null")
            .order("created_at", desc=True).order("id", desc=True)
            .limit(WINDOW)
            .execute()
        ).data or []
        ids = [str(d["id"]) for d in docs]
        lines = fetch_all_in(lambda: db.table("purchase_bill_lines").select("id,bill_id,expense_account_id,sort_order"),
                             "bill_id", ids, label="recent_accounts.bill_lines")
        out = recent_account_ids(ids, lines, "bill_id", "expense_account_id", "sort_order", limit)
    else:
        raise ValueError(f"no recent accounts for {used_on!r}")
    return {"ids": out, "documents_read": len(ids), "window": WINDOW}
