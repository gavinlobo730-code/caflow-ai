"""The TDS deposit position of some clients, from the database: the one reader the hub's tile and the TDS screen share.

`public.tds_deposit_position` (migration 523) computes both figures where the rows are (CLAUDE.md's reporting rule: what crosses the wire
is proportional to the answer, not to the ledger): the tax deducted and not yet deposited in quarters for which a challan is recorded,
and, apart, the tax deducted in quarters for which none is (NOT RECORDED: this product holds no challan to say whether it was
deposited). The function's name is written out at the call on purpose: `core/schema_guard` and the rpc-existence tests read the literal
first argument of an rpc call and cannot see a name held in a variable.
"""
from __future__ import annotations

from typing import Optional


def read(db, firm_id: str, client_ids: Optional[list[str]]) -> tuple[int, int]:
    """(deducted and not yet deposited, deducted in quarters with no challan recorded), in paise.

    `client_ids` None is every client of the firm, a list is those clients, an empty list is none. A partial or absent answer raises:
    the callers turn it into no figure, and an unknown is never shown as a value."""
    data = db.rpc("tds_deposit_position", {"p_firm_id": firm_id, "p_client_ids": client_ids}).execute().data
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict) or data.get("undeposited_paise") is None or data.get("not_recorded_paise") is None:
        # The function sums with a coalesce, so a genuine nothing is 0. An ANSWER that is absent is a read that did not happen.
        raise RuntimeError("tds_deposit_position answered nothing")
    return int(data["undeposited_paise"]), int(data["not_recorded_paise"])
