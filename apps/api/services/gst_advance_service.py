"""Advances received against no invoice — GSTR-1 Tables 11A and 11B.

WHAT A ROW NEEDS, AND WHERE IT COMES FROM
    Table 11A declares an advance on which tax is payable but no invoice has
    been issued. A row needs the place of supply, whether the supply is inter-
    or intra-state, the RATE, and the tax split — all properties of a supply
    that HAS NOT HAPPENED YET. So they are recorded ON THE RECEIPT when it is
    taken (`receipts.gst_rate_bps`, `place_of_supply`, `is_interstate`;
    `receipt_service._advance_treatment` derives the third from IGST §§7-8
    rather than trusting the browser), and `table_11_sections` reads them.

    A receipt missing ANY of the three is not declared and is NAMED as a gap,
    never guessed: a guessed rate is a guessed liability on a filed return.
    The gap travels with the return — `gst_return_service` extends the GSTR-1
    payload's `gaps` with this list.

WHY A BLANKET RULE WOULD BE WRONG EVEN WITH A RATE
    Notification 66/2017-Central Tax (15 November 2017) exempts a registered
    person from paying tax on an advance received for a supply of GOODS — the
    liability arises at the invoice instead (CGST Act §12(2) proviso). For
    SERVICES it does not: §13(2) puts the time of supply at the earlier of
    invoice or payment, so an advance for services is taxable when received.

    A receipt in this system is not marked goods or services. Two clients with
    identical books can therefore owe different tax on the same advance, and
    which one is which is a fact about their business, not about their ledger.
    So the whole of Table 11 is gated on the client's own
    `gst_advance_tax_applicable`, which is off by default.

THE TWO RETURNS READ THE SAME BUCKETS (GST-15)
    `_table_11_rows` builds the GSTR-1 sections and `_bucket_totals_paise`
    totals the SAME buckets in paise for GSTR-3B Table 3.1(a), through one
    `split_inclusive_charge` per bucket. Deliberately one pass: GSTR-3B had no
    advances input at all until GST-15, so a client with the flag on filed a
    GSTR-1 declaring a liability and a GSTR-3B that discharged none of it, and
    two independent computations of one figure is how that stays possible.

WHAT IS STILL NOT HERE
    The LIABILITY is declared; it is not POSTED. A receipt journal is Bank Dr
    / Trade Receivable Cr and carries no output-tax leg, so the §13(2) tax
    sits on the return and not in the general ledger. `gst_return_service`
    therefore holds it out of the GSTR-3B books-to-ledger comparison and names
    the amount rather than letting every advance-bearing client read as
    permanently unreconciled.
"""
from __future__ import annotations

import logging
from typing import Optional

from domain.banking.charge_gst import split_inclusive_charge

_logger = logging.getLogger("caflow.gst_advances")

PAGE = 1000


def _paginate_all(make_query, key: str = "id") -> list:
    out: list = []
    cursor = None
    while True:
        q = make_query()
        if cursor is not None:
            q = q.gt(key, cursor)
        page = q.order(key).limit(PAGE).execute().data or []
        out.extend(page)
        if len(page) < PAGE:
            break
        cursor = page[-1].get(key)
        if cursor is None:
            break
    return out


def _period_bounds(period: str) -> tuple[str, str]:
    """MMYYYY -> (first day, last day) as YYYY-MM-DD."""
    import calendar
    mm, yyyy = int(period[:2]), int(period[2:])
    last = calendar.monthrange(yyyy, mm)[1]
    return f"{yyyy:04d}-{mm:02d}-01", f"{yyyy:04d}-{mm:02d}-{last:02d}"


def _allocations_by_receipt(db, receipt_ids: list[str]) -> dict:
    """receipt_id -> [(allocated_paise, created_at)].

    Table 11 asks what was outstanding AT THE PERIOD END, not what is
    outstanding today. receipts.unallocated_paise is the state now, so reading
    it would answer a July question with August's facts and quietly change a
    filed period every time an old advance is settled.
    """
    out: dict = {}
    if not receipt_ids:
        return out
    rows = (db.table("receipt_allocations")
            .select("receipt_id, allocated_paise, created_at")
            .in_("receipt_id", receipt_ids).execute().data) or []
    for r in rows:
        out.setdefault(r.get("receipt_id"), []).append(
            (int(r.get("allocated_paise") or 0), str(r.get("created_at") or "")))
    return out


def _table_11_rows(buckets: dict) -> list[dict]:
    """GSTN Table 11 rows: one per place of supply, items grouped by rate.

    Shape read from the Returns Offline Tool V3.2.4 (returnStructure.js, cases
    'at' and 'atadj'): {pos, sply_ty, itms: [{rt, ad_amt, iamt | camt+samt,
    csamt}]}. An intra-state row splits the rate in half across CGST and SGST;
    an inter-state row carries the whole of it as IGST.
    """
    by_pos: dict = {}
    for (pos, interstate, rate_bps), gross in sorted(buckets.items()):
        if gross <= 0:
            continue
        # An advance is money the customer actually paid, so it is INCLUSIVE of
        # the tax on it. ad_amt is the taxable value backed out of it — the
        # utility multiplies ad_amt BY the rate to get the tax, so handing it
        # the gross would overstate both.
        sp = split_inclusive_charge(gross, rate_bps, is_interstate=interstate)
        key = (pos, interstate)
        item = {"rt": rate_bps / 100.0,
                "ad_amt": round(sp.taxable_paise / 100, 2)}
        if interstate:
            item["iamt"] = round(sp.igst_paise / 100, 2)
        else:
            item["camt"] = round(sp.cgst_paise / 100, 2)
            item["samt"] = round(sp.sgst_paise / 100, 2)
        item["csamt"] = 0
        row = by_pos.setdefault(key, {
            "pos": pos,
            "sply_ty": "INTER" if interstate else "INTRA",
            "itms": [],
        })
        row["itms"].append(item)
    return list(by_pos.values())


def _bucket_totals_paise(buckets: dict) -> dict:
    """A Table 11 bucket set totalled in integer paise.

    Same input and same split as `_table_11_rows`, which produces the GSTR-1
    payload rows — deliberately, because GSTR-3B's 3.1(a) has to agree with
    what GSTR-1 declared on the same advance, and two independent computations
    of one figure is how they came to disagree in the first place. The rupee
    rounding stays where it belongs: in the payload builder, at the statutory
    boundary (CLAUDE.md), not here.
    """
    total = {"taxable_paise": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0}
    for (_pos, interstate, rate_bps), gross in buckets.items():
        if gross <= 0:
            continue
        sp = split_inclusive_charge(gross, rate_bps, is_interstate=interstate)
        total["taxable_paise"] += sp.taxable_paise
        total["igst_paise"] += sp.igst_paise
        total["cgst_paise"] += sp.cgst_paise
        total["sgst_paise"] += sp.sgst_paise
    return total


def _missing_phrase(rate, pos, treatment) -> str:
    """"it has no GST rate and no place of supply recorded" — the list of what
    is absent, in one sentence, whichever combination it is. Written out rather
    than assembled inline because there are now three of them and eight
    combinations, and the inline version had already lost the Oxford comma."""
    missing = []
    if rate is None:
        missing.append("no GST rate")
    if not pos:
        missing.append("no place of supply")
    if treatment is None:
        missing.append("no inter-state or intra-state treatment")
    if not missing:                                    # pragma: no cover
        return "it is not declarable"
    if len(missing) == 1:
        return f"it has {missing[0]} recorded"
    return f"it has {', '.join(missing[:-1])} and {missing[-1]} recorded"


def advance_tax_applicable(db, firm_id: str, client_id: str) -> bool:
    """Does this client bear tax on advances at all? (CGST Act §13(2).)

    One reader for the one flag, because two answers to "is Table 11 computed
    for this client" is how a screen came to say it was not while the GSTR-1
    builder was declaring rows. Firm-scoped: the service-role key bypasses RLS,
    so the app-layer firm filter is the isolation control (CLAUDE.md) and a
    read keyed on a bare uuid is not one.
    """
    rows = (db.table("clients").select("id, gst_advance_tax_applicable")
            .eq("id", client_id).eq("firm_id", firm_id)
            .limit(1).execute().data) or []
    return bool(rows and rows[0].get("gst_advance_tax_applicable"))


def table_11_sections(db, firm_id: str, client_id: str, period: str) -> dict:
    """GSTR-1 Tables 11A (`at`) and 11B (`txpd`), or empty when not applicable.

    Empty for a client whose gst_advance_tax_applicable is false, which is the
    default: Notification 66/2017-Central Tax removed the charge on advances
    for GOODS, so most registered persons have no Table 11 at all. A supplier
    of SERVICES turns it on (CGST Act §13(2)).

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
    """
    if not advance_tax_applicable(db, firm_id, client_id):
        return {"at": [], "txpd": [], "applicable": False, "gaps": []}

    start, end = _period_bounds(period)
    receipts = _paginate_all(lambda: db.table("receipts")
        .select("id, receipt_date, amount_paise, gst_rate_bps, "
                "place_of_supply, is_interstate")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .lte("receipt_date", end))
    allocs = _allocations_by_receipt(db, [r["id"] for r in receipts])

    at_buckets: dict = {}
    txpd_buckets: dict = {}
    undeclarable: list[dict] = []
    for r in receipts:
        rate = r.get("gst_rate_bps")
        pos = r.get("place_of_supply")
        # No rate or no place of supply means the advance cannot be declared.
        # It still appears in advances_report(), so it is visible rather than
        # dropped — but a guessed rate is a guessed liability.
        # `is_interstate` is a THIRD thing that can be missing, and it used to
        # read as False — intra-state — for a row that had never been decided.
        # Nothing in IGST §§7-8 makes "unknown" mean "same state", and the
        # default put CGST and SGST in Table 11A on an inter-state advance as
        # readily as the browser's old rule put IGST on a local one. Undecided
        # belongs in this list, beside a missing rate, for the same reason: the
        # split is the row, not a presentation of it.
        treatment = r.get("is_interstate")
        if rate is None or not pos or treatment is None:
            # Declared nowhere, and SAID SO. This used to `continue` in silence
            # under a comment explaining that a guessed rate is a guessed
            # liability — which is right — but the advance then vanished from
            # the return with nothing on screen to say a Table 11A row was
            # missing. It is still not guessed at; it is named.
            undeclarable.append({
                "kind": "TABLE_11A",
                "reference_no": str(r.get("id") or ""),
                "reason": (
                    "This advance is not declared in Table 11A: "
                    + _missing_phrase(rate, pos, treatment)
                    + ". CGST s.13(2) charges tax on an advance for "
                    "services when it is received, and the rate, the place of "
                    "supply and whether the supply is inter-state are what the "
                    "row is declared at — none can be guessed without guessing "
                    "the liability."),
            })
            continue
        key = (str(pos), bool(treatment), int(rate))
        mine = allocs.get(r["id"], [])
        amount = int(r.get("amount_paise") or 0)
        adjusted_by_end = sum(a for a, ts in mine if ts[:10] <= end)
        adjusted_in_period = sum(a for a, ts in mine if start <= ts[:10] <= end)
        received_this_period = start <= str(r.get("receipt_date") or "")[:10] <= end

        if received_this_period:
            # 11A: received now, still not invoiced by the period end.
            left = amount - adjusted_by_end
            if left > 0:
                at_buckets[key] = at_buckets.get(key, 0) + left
        elif adjusted_in_period > 0:
            # 11B: received in an EARLIER period — so its tax was declared in
            # that period's 11A — and adjusted against an invoice now. An
            # advance received and adjusted inside one period never reaches
            # either table: it was invoiced before any 11A could declare it.
            txpd_buckets[key] = txpd_buckets.get(key, 0) + adjusted_in_period

    return {
        "at": _table_11_rows(at_buckets),
        "txpd": _table_11_rows(txpd_buckets),
        # The SAME buckets, in paise, for GSTR-3B Table 3.1(a) (GST-15). One
        # pass, one `split_inclusive_charge` per bucket, so the two returns
        # cannot declare different tax on the same advance — which is exactly
        # what they did while 3B had no advances input at all.
        "paise": {
            "at": _bucket_totals_paise(at_buckets),
            "txpd": _bucket_totals_paise(txpd_buckets),
        },
        "applicable": True,
        "gaps": undeclarable,
    }


def advances_report(db, firm_id: str, client_id: str, period: str) -> dict:
    """Every advance still unadjusted in `period`, and whether Table 11 is on.

    A LIST, not the return. `table_11_sections` is what builds the declared
    rows; this answers the different question a CA asks while preparing — which
    receipts are sitting unadjusted and how much money that is — so it reads
    `unallocated_paise`, the position NOW, and reads no rate at all.

    `table_11_computed` says whether Table 11 is computed for THIS client,
    because an empty Table 11 has two meanings and only the client's own
    `gst_advance_tax_applicable` separates them. It reported a flat False for
    as long as it existed, which stopped being true when `table_11_sections`
    began declaring real 11A rows: the screen carried an amber banner telling
    the CA the platform does not compute Table 11 while their filed GSTR-1
    carried it.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. This reports; it writes nothing
    # and files nothing.
    """
    start, end = _period_bounds(period)
    computed = advance_tax_applicable(db, firm_id, client_id)

    receipts = _paginate_all(lambda: db.table("receipts")
        .select("id, receipt_no, receipt_date, customer_id, amount_paise, "
                "allocated_paise, unallocated_paise")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .gte("receipt_date", start).lte("receipt_date", end))

    cust_ids = {r.get("customer_id") for r in receipts if r.get("customer_id")}
    names: dict = {}
    if cust_ids:
        rows = (db.table("customers").select("id, name, gstin, state_code")
                .eq("firm_id", firm_id).in_("id", list(cust_ids)).execute().data) or []
        names = {c["id"]: c for c in rows}

    unadjusted = []
    total = 0
    for r in receipts:
        left = int(r.get("unallocated_paise") or 0)
        if left <= 0:
            continue
        cust = names.get(r.get("customer_id")) or {}
        total += left
        unadjusted.append({
            "receipt_id": r.get("id"),
            "receipt_no": r.get("receipt_no"),
            "receipt_date": r.get("receipt_date"),
            "customer_name": cust.get("name") or "",
            "customer_gstin": cust.get("gstin"),
            "amount_paise": int(r.get("amount_paise") or 0),
            "unadjusted_paise": left,
        })

    # Longest outstanding first — the one most likely to have been forgotten.
    unadjusted.sort(key=lambda a: (str(a["receipt_date"] or ""), str(a["receipt_no"] or "")))

    return {
        "period": period,
        "unadjusted_advances": unadjusted,
        "count": len(unadjusted),
        "total_unadjusted_paise": total,
        # Stated in the payload, not only in a docstring: a CA reading an empty
        # Table 11 needs to know whether it is empty because there were no
        # advances or because nothing computes it for this client.
        "table_11_computed": computed,
        "why": (
            "Table 11 is computed for this client: an advance received for a "
            "supply of SERVICES bears tax when it is received (CGST Act "
            "§13(2)). Each one is declared at the GST rate, place of supply "
            "and inter/intra-state treatment recorded on the receipt, and "
            "GSTR-3B Table 3.1(a) pays the same figure — 11A received less "
            "11B adjusted. An advance missing any of the three is named on "
            "the return as undeclared rather than guessed; a guessed rate is "
            "a guessed liability. The tax is declared but not posted: a "
            "receipt journal carries no output-tax leg, so it is held out of "
            "the books-to-ledger comparison and named there."
            if computed else
            "Table 11 is not computed for this client, because advances here "
            "are not marked as bearing tax. CGST Act §13(2) makes an "
            "advance for SERVICES taxable when it is received; Notification "
            "66/2017-Central Tax removed the charge for GOODS, where the "
            "liability arises at the invoice instead (§12(2) proviso). "
            "Which applies is a fact about the client's business, not about "
            "the receipt, so it is the client setting "
            "'Advances received bear GST' that turns Table 11 on."
        ),
        "rule": "CGST Act §12(2), §13(2); Notification 66/2017-Central Tax",
        "ca_review_required": True,
    }
