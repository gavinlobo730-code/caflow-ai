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
                                end: str, *, credit_positive: bool = False,
                                opening_position: dict | None = None) -> None:
    """Attach `base_currency` + `outstanding_by_currency` to `result` when any event
    is non-INR. `credit_positive` selects the payable (vendor) sign convention; the
    default is the receivable (customer) convention.

    Each event must carry: date, debit_paise, credit_paise, txn_currency, txn_amount.

    `opening_position` is the party's per-currency position BEFORE the statement
    window — {"by_currency": [{currency, base_paise, foreign_minor}, ...]}, seed
    included — as returned by public.party_opening_position (migration 282). Pass
    it when `events` holds only the window's documents; the accumulation then
    starts from that position instead of from the seed, and the reconciliation
    guarantee above is preserved.

    This is why the statement asks the database for a POSITION and not just an
    opening balance. The guarantee holds because every movement on or before the
    period end is accumulated, and a scalar balance has already summed the
    currency dimension away — feed one in and a party with foreign activity before
    the window gets a split that does not reconcile to its own closing balance.

    Omit it and behaviour is exactly as before: `events` is taken to be the full
    history and the seed opens the INR slot. That is what mock mode, local dev and
    every pure-builder caller still do.
    """
    opening_ccy = list((opening_position or {}).get("by_currency") or [])
    # A party whose ONLY foreign activity predates the window would look INR-only
    # from the windowed events alone, and would silently lose the block it gets
    # today. The position names every currency it ever saw, zero-valued or not,
    # which is exactly the set the full replay would have found.
    if not (any((e.get("txn_currency") or "INR").upper() != "INR" for e in events)
            or any((r.get("currency") or "INR").upper() != "INR" for r in opening_ccy)):
        return

    by: dict[str, dict] = {}

    def slot(cur: str) -> dict:
        return by.setdefault(cur, {"outstanding_foreign_minor": 0, "outstanding_base_paise": 0})

    if opening_position is not None:
        for row in opening_ccy:
            s = slot((row.get("currency") or "INR").upper())
            s["outstanding_base_paise"] += int(row.get("base_paise") or 0)
            s["outstanding_foreign_minor"] += int(row.get("foreign_minor") or 0)
        slot("INR")          # the INR row exists even for a purely foreign party
    else:
        seed = int(party.get("opening_balance_paise") or 0)
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
