"""
Shared dual-currency helper for the customer (AR) and vendor (AP) statements
(Multi-Currency Phase 5). READ-ONLY / display only — the base (INR) amounts on
each statement stay authoritative; this only splits the CLOSING outstanding by
transaction currency so a foreign customer/vendor sees both the foreign and the
base amount owed.

Reconciliation guarantee: Σ(outstanding_base_paise over currencies) equals the
statement's closing_balance_paise exactly, because we accumulate the seed opening
(INR) plus every movement dated on/before the period end — the same set that
defines the closing balance. Integer paise / integer minor units throughout.

It is a no-op (adds nothing) when the party has only INR activity, so an INR-only
statement is byte-for-byte identical to today's.
"""
from __future__ import annotations


def attach_currency_outstanding(result: dict, party: dict, events: list[dict],
                                end: str, *, credit_positive: bool = False) -> None:
    """Attach `base_currency` + `outstanding_by_currency` to `result` when any event
    is non-INR. `credit_positive` selects the payable (vendor) sign convention; the
    default is the receivable (customer) convention.

    Each event must carry: date, debit_paise, credit_paise, txn_currency, txn_amount.
    """
    if not any((e.get("txn_currency") or "INR").upper() != "INR" for e in events):
        return

    seed = int(party.get("opening_balance_paise") or 0)
    by: dict[str, dict] = {}

    def slot(cur: str) -> dict:
        return by.setdefault(cur, {"outstanding_foreign_minor": 0, "outstanding_base_paise": 0})

    inr = slot("INR")
    inr["outstanding_foreign_minor"] += seed
    inr["outstanding_base_paise"] += seed
    for e in events:
        if e["date"] > end:
            continue
        cur = (e.get("txn_currency") or "INR").upper()
        dr, cr = int(e["debit_paise"]), int(e["credit_paise"])
        base_delta = (cr - dr) if credit_positive else (dr - cr)
        # The foreign leg moves in the same direction as the base leg; INR rows carry
        # txn_amount == base so this stays exact for them too.
        txn = int(e["txn_amount"])
        fx_signed = txn if base_delta >= 0 else -txn
        s = slot(cur)
        s["outstanding_base_paise"] += base_delta
        s["outstanding_foreign_minor"] += fx_signed

    lines = []
    for cur, s in sorted(by.items()):
        row = {"currency": cur, "base_currency": "INR",
               "outstanding_base_paise": s["outstanding_base_paise"]}
        if cur != "INR":
            row["outstanding_foreign_minor"] = s["outstanding_foreign_minor"]
        lines.append(row)
    result["base_currency"] = "INR"
    result["outstanding_by_currency"] = lines


def summarize_by_currency(entries: list[tuple]) -> tuple:
    """Aggregate an AR/AP aging into a per-currency outstanding breakdown.

    `entries` is a list of (currency, base_paise, foreign_minor). Returns
    ("INR", [ {currency, base_currency, outstanding_base_paise[, outstanding_foreign_minor]} ])
    when any entry is foreign, else (None, None) so an INR-only aging is unchanged.
    """
    if not any((c or "INR").upper() != "INR" for c, _b, _f in entries):
        return None, None
    by: dict[str, dict] = {}
    for c, b, f in entries:
        cur = (c or "INR").upper()
        s = by.setdefault(cur, {"base": 0, "foreign": 0})
        s["base"] += int(b)
        s["foreign"] += int(f or 0)
    lines = []
    for cur, s in sorted(by.items()):
        row = {"currency": cur, "base_currency": "INR", "outstanding_base_paise": s["base"]}
        if cur != "INR":
            row["outstanding_foreign_minor"] = s["foreign"]
        lines.append(row)
    return "INR", lines
