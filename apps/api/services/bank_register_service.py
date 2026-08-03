"""
Bank register service (Tier 1.1) — the ledger view of one bank account.

Assembles what domain/banking/register.py needs (the account's opening balance,
its transactions, and the status of every reconciliation that claimed one), then
applies the caller's filters, sort and paging.

READ-ONLY BY DESIGN. Nothing here writes. Posted journals are immutable in this
system, so an editable register would be offering something the ledger refuses —
corrections are reversals, made where reversals are made.

ONE THING WORTH UNDERSTANDING ABOUT FILTERING
    The running balance is computed over the WHOLE account, always, before any
    filter is applied. Filtering to April and recomputing from zero would show a
    balance column that starts at the April opening — which is not the account's
    balance and would not tie to the statement. So the arithmetic runs over
    everything and the filter only decides which of those rows are returned;
    each row keeps its true balance. `view_opening_balance_paise` reports the
    balance immediately before the first returned row, which is what makes the
    filtered view still add up.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from domain.banking.register import (
    build_register, first_divergence, summarise, RegisterLine,
    CLEARED_NONE, CLEARED_PENDING, CLEARED_RECONCILED,
)

# What the caller may sort by. A closed list — an arbitrary column name here
# would be a PostgREST injection point, and most columns make no sense to sort a
# register by anyway.
SORTABLE = ("date", "amount", "description", "balance", "cleared")
_DEFAULT_SORT = "date"

# Status filters, named for what a bookkeeper is actually looking for.
STATUS_FILTERS = ("all", "uncleared", "pending", "reconciled", "unposted", "needs_review")


class BankRegisterService:

    # ── data assembly ────────────────────────────────────────────────────────
    def _account(self, db, firm_id: str, client_id: Optional[str], bank_account_id: str) -> dict:
        rows = (db.table("bank_accounts").select("*")
                .eq("id", bank_account_id).eq("firm_id", firm_id).limit(1).execute().data) or []
        ba = rows[0] if rows else None
        if not ba:
            raise HTTPException(status_code=404, detail="Bank account not found for this firm.")
        # Same tenant check the reconciliation service makes: a bank_account_id
        # from another client must not resolve just because the firm matches.
        if client_id and ba.get("client_id") and ba["client_id"] != client_id:
            raise HTTPException(status_code=422, detail="Bank account does not belong to this client.")
        return ba

    def _txns(self, db, firm_id: str, bank_account_id: str) -> list[dict]:
        """Every transaction on this account's statements.

        ALL of them — not just posted ones. A register is the BANK's view: a
        line the bank debited is on the statement whether or not anyone has
        coded it yet, and hiding the uncoded ones would make the balance
        disagree with the statement, which is the one thing a register must
        never do. (The reconciliation service filters to posted for a different
        and correct reason — it ties out the BOOKS.)
        """
        stmts = (db.table("bank_statements").select("id")
                 .eq("firm_id", firm_id).eq("bank_account_id", bank_account_id)
                 .execute().data) or []
        stmt_ids = [s["id"] for s in stmts]
        if not stmt_ids:
            return []
        return (db.table("bank_transactions").select("*")
                .eq("firm_id", firm_id).in_("statement_id", stmt_ids)
                .execute().data) or []

    def _reconciliation_statuses(self, db, firm_id: str, txns: list[dict]) -> dict:
        """reconciliation_id -> status, for the cleared column.

        Only the ids actually referenced, so this stays one small query however
        many reconciliations the client has accumulated.
        """
        ids = {t.get("reconciliation_id") for t in txns if t.get("reconciliation_id")}
        if not ids:
            return {}
        rows = (db.table("bank_reconciliations").select("id, status")
                .eq("firm_id", firm_id).in_("id", list(ids)).execute().data) or []
        return {r["id"]: r.get("status") for r in rows}

    # ── filtering / sorting ──────────────────────────────────────────────────
    @staticmethod
    def _matches(line: RegisterLine, raw: dict, *, date_from, date_to, status, q) -> bool:
        if date_from and (not line.transaction_date or str(line.transaction_date) < date_from):
            return False
        if date_to and (not line.transaction_date or str(line.transaction_date) > date_to):
            return False
        if status == "uncleared" and line.cleared != CLEARED_NONE:
            return False
        if status == "pending" and line.cleared != CLEARED_PENDING:
            return False
        if status == "reconciled" and line.cleared != CLEARED_RECONCILED:
            return False
        if status == "unposted" and line.posted_journal_id:
            return False
        if status == "needs_review" and not raw.get("needs_review"):
            return False
        if q:
            needle = q.strip().lower()
            hay = " ".join(str(x or "") for x in
                           (line.description, line.reference_no, line.category))
            if needle not in hay.lower():
                return False
        return True

    @staticmethod
    def _sort(lines: list[RegisterLine], sort: str, desc: bool) -> list[RegisterLine]:
        """Re-order for display. Each line keeps the balance it had in DATE
        order — see the module docstring. Sorting by amount does not renumber
        the balance column, because a running balance in amount order is not a
        running balance."""
        if sort == "amount":
            key = lambda l: (l.amount_paise, str(l.transaction_date or ""), l.transaction_id)
        elif sort == "description":
            key = lambda l: (l.description.lower(), str(l.transaction_date or ""), l.transaction_id)
        elif sort == "balance":
            key = lambda l: (l.balance_paise, str(l.transaction_date or ""), l.transaction_id)
        elif sort == "cleared":
            # blank -> C -> R, so the work still to do sorts to the top.
            rank = {CLEARED_NONE: 0, CLEARED_PENDING: 1, CLEARED_RECONCILED: 2}
            key = lambda l: (rank.get(l.cleared, 0), str(l.transaction_date or ""), l.transaction_id)
        else:
            key = lambda l: (str(l.transaction_date or ""), l.transaction_id)
        return sorted(lines, key=key, reverse=desc)

    @staticmethod
    def _line_out(line: RegisterLine) -> dict:
        return {
            "transaction_id": line.transaction_id,
            "transaction_date": line.transaction_date.isoformat() if line.transaction_date else None,
            "description": line.description,
            "reference_no": line.reference_no,
            "debit_paise": line.debit_paise,
            "credit_paise": line.credit_paise,
            "amount_paise": line.amount_paise,
            "balance_paise": line.balance_paise,
            "cleared": line.cleared,
            "category": line.category,
            "match_status": line.match_status,
            "posted_journal_id": line.posted_journal_id,
            "reconciliation_id": line.reconciliation_id,
            "statement_balance_paise": line.statement_balance_paise,
            "balance_delta_paise": line.balance_delta_paise,
            "precedes_opening": line.precedes_opening,
        }

    # ── the register ─────────────────────────────────────────────────────────
    def register(self, db, firm_id: str, bank_account_id: str, *,
                 client_id: Optional[str] = None,
                 date_from: Optional[str] = None, date_to: Optional[str] = None,
                 status: str = "all", q: Optional[str] = None,
                 sort: str = _DEFAULT_SORT, desc: bool = False,
                 limit: int = 200, offset: int = 0) -> dict:
        if sort not in SORTABLE:
            raise HTTPException(status_code=422,
                                detail=f"Cannot sort by '{sort}'. Allowed: {', '.join(SORTABLE)}")
        if status not in STATUS_FILTERS:
            raise HTTPException(status_code=422,
                                detail=f"Unknown filter '{status}'. Allowed: {', '.join(STATUS_FILTERS)}")
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status_code=422, detail="The start date must not follow the end date.")
        # `int(limit or 200)` would be wrong: 0 is falsy, so an explicit 0 would
        # silently become 200 rather than clamping to 1. The router blocks 0
        # (ge=1) but the service is directly callable, and a paging bound that
        # quietly means its opposite is the kind of thing nobody debugs twice.
        limit = 200 if limit is None else max(1, min(int(limit), 1000))
        offset = 0 if offset is None else max(0, int(offset))

        account = self._account(db, firm_id, client_id, bank_account_id)
        txns = self._txns(db, firm_id, bank_account_id)
        statuses = self._reconciliation_statuses(db, firm_id, txns)
        opening = int(account.get("opening_balance_paise") or 0)

        # Over the WHOLE account, before any filter — see the module docstring.
        all_lines = build_register(
            txns, opening_balance_paise=opening,
            opening_balance_date=account.get("opening_balance_date"),
            reconciliation_statuses=statuses,
        )
        by_id = {str(t.get("id")): t for t in txns}

        filtered = [l for l in all_lines
                    if self._matches(l, by_id.get(l.transaction_id, {}),
                                     date_from=date_from, date_to=date_to, status=status, q=q)]
        ordered = self._sort(filtered, sort, desc)
        page = ordered[offset:offset + limit]

        # What the balance was immediately before the first row of this view.
        # Without it a filtered register does not add up on screen: the first
        # visible balance would look like it came from nowhere.
        view_opening = opening
        if filtered:
            earliest = min(filtered, key=lambda l: all_lines.index(l))
            idx = all_lines.index(earliest)
            view_opening = all_lines[idx - 1].balance_paise if idx > 0 else opening

        return {
            "account": {
                "id": account["id"],
                "bank_name": account.get("bank_name"),
                "account_no": account.get("account_no"),
                "account_type": account.get("account_type"),
                "currency": account.get("currency") or "INR",
                "coa_account_id": account.get("coa_account_id"),
                "opening_balance_paise": opening,
                "opening_balance_date": (str(account["opening_balance_date"])[:10]
                                         if account.get("opening_balance_date") else None),
            },
            "lines": [self._line_out(l) for l in page],
            "summary": summarise(all_lines, opening_balance_paise=opening),
            # The self-check against the bank's own balance column. None when
            # every line agrees, or when the statements carried no balances.
            "divergence": first_divergence(all_lines),
            "view_opening_balance_paise": view_opening,
            "filtered_count": len(filtered),
            "total_count": len(all_lines),
            "limit": limit,
            "offset": offset,
            "sort": sort,
            "desc": bool(desc),
        }


bank_register_service = BankRegisterService()
