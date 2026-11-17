"""Find a payroll ledger account for a client: the one door every payroll writer and reader goes through (POST-A-083).

The vocabulary and the choice are `domain/payroll/ledger_accounts.py`; this module reads the two candidate sets from the
chart and hands them to it. Two reads rather than one OR: the first is the key, which survives a rename; the second is the
pattern the posting has always used, which serves a chart nobody has keyed. Both are the firm's rows, narrowed to the
client's own and the firm-level ones, active only.
"""
from __future__ import annotations

from typing import Optional

from domain.payroll import ledger_accounts as L
from domain.payroll.ledger_accounts import PayrollLedger, Resolved


def _scope(db, firm_id: str, client_id: Optional[str]):
    q = db.table("chart_of_accounts").select("id, client_id, account_name, system_account_key, is_active").eq("firm_id", firm_id).eq("is_active", True)
    if client_id:
        return q.or_(f"client_id.eq.{client_id},client_id.is.null")
    return q.is_("client_id", "null")


def resolve(db, *, firm_id: str, client_id: Optional[str], ledger: PayrollLedger,
            required: bool = True) -> Optional[Resolved]:
    """The account for `ledger` in this client's view of the firm's chart. Raises PayrollLedgerMissing when there is none and
    `required` (a posting cannot go ahead without it), returns None when there is none and not `required` (a reader with
    nothing to reconcile), and raises PayrollLedgerAmbiguous either way when two could be it."""
    key_rows = _scope(db, firm_id, client_id).eq("system_account_key", ledger.key).execute().data or []
    found = L.choose(ledger, key_rows=key_rows, name_rows=[], client_id=client_id)
    if found is None:
        name_rows = _scope(db, firm_id, client_id).ilike("account_name", ledger.pattern).execute().data or []
        found = L.choose(ledger, key_rows=[], name_rows=name_rows, client_id=client_id)
    if found is None and required:
        raise L.PayrollLedgerMissing(ledger, L.missing_sentence(ledger))
    return found


def resolve_id(db, *, firm_id: str, client_id: Optional[str], ledger: PayrollLedger,
               required: bool = True) -> Optional[str]:
    found = resolve(db, firm_id=firm_id, client_id=client_id, ledger=ledger, required=required)
    return found.id if found else None
