"""
Where the fixed-asset register disagrees with the ledger, or with Schedule II.

WHY IT REPORTS AND REPAIRS NOTHING

    Every remedy here is a judgement. Repost the acquisition, delete the
    duplicate, re-link the bill, record the life, correct the rate or disclose
    it — which one is right depends on facts the ledger does not hold. So this
    states the finding and the endpoint that serves it offers no fix button.

WHY IT IS PURE

    Rows in, findings out. `routers/fixed_assets.py` calls it on demand from the
    Reports tab; `services/reconciliation_service.py` calls it in the nightly
    sweep and on "Verify Books" (FA-20). Those two were about to hold one copy
    each, over the same register, for the same client — and the second copy is
    always the one that stops being updated. Fetching stays at the callers,
    where the query and the paging rule are.

WHAT EACH CHECK MEANS, because none of them is self-evident from its name:

  * `no_acquisition_journal` — the register says the client owns a machine and
    no entry ever put it on the balance sheet. It arises when journal posting
    failed after the row was inserted: the router updates `journal_entry_id` in
    a SECOND statement, so a failure between the two leaves exactly this.
  * `bill_capitalised_more_than_once` — migration 343's unique index stops it
    now, but rows created before it are unprotected, and the same bill's cost
    then sits in Fixed Assets twice while its payable is recorded once.
  * `capitalised_from_a_bill_that_is_gone` — `acquisition_mode = 'from_bill'`
    means the entry only RECLASSIFIED cost out of purchases; with the bill
    deleted, nothing supports the asset.
  * `depreciation_basis_departs_from_schedule_ii` (FA-02) — rows written before
    the rate was derived from Part C carry Income-tax Act block rates, which
    under-depreciate. NOT an error report: Part A expressly permits a different
    life or residual, provided it is disclosed.
  * `wdv_asset_has_no_stopping_point` (FA-13) — a reducing balance approaches
    its floor and never reaches it, so a row with no useful life and no salvage
    is still being charged years after the asset is worn out.

A DISPOSED ASSET IS NOT CHECKED FOR THE LAST TWO. Its basis is settled — the
gain or loss was computed from it — so a finding there is noise the CA cannot
act on.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Optional

from domain.fixed_assets import schedule_ii


#: The columns `register_findings` reads. Named here, beside the rule that
#: needs them, because BOTH callers fetch their own rows — the endpoint and the
#: reconciliation sweep — and a column added to one query and not the other
#: makes one of them quietly answer "clean" on a finding it could not see. A
#: check cannot judge what was never selected.
COLUMNS = (
    "id, asset_code, asset_name, purchase_cost_paise, accumulated_depreciation_paise, "
    "salvage_value_paise, journal_entry_id, acquisition_mode, purchase_bill_id, "
    "is_disposed, asset_category, depreciation_method, wdv_rate_percent, "
    "useful_life_years"
)


def schedule_ii_departure(asset: dict) -> Optional[dict]:
    """Whether this asset depreciates on a basis Schedule II does not prescribe.

    WHY THIS REPORTS AND DOES NOT CORRECT (FA-02)

    The stored `wdv_rate_percent` is what every charge the asset will ever
    produce is computed from, and rows written before the rate was derived from
    Schedule II Part C carry Income-tax Act block rates instead — Furniture at
    10%, Intangibles at 25% — every one of them under-depreciating.

    The obvious fix is a backfill migration. It is the wrong fix, and the
    statute is why: **Schedule II Part A expressly allows a company to use a
    different useful life or residual value**, provided the difference is
    DISCLOSED in the accounts and justified. So a rate that departs from the
    table is not necessarily an error — it may be a judgement somebody made and
    has to disclose. Nothing in this schema distinguishes the two, and a
    migration that rewrote them would silently overwrite the judgement, change
    the depreciation charge, and move the profit.

    So the departure is NAMED and the CA decides: correct it through
    PATCH /{asset_id} (wdv_rate_percent is a Tier C field), or keep it and
    disclose it.

    CONFORMING MEANS MATCHING ANY CLASS THE CATEGORY OFFERS, not the default.
    Schedule II gives several lives per category — a CA choosing "Plant and
    Machinery used in manufacture" over the category's first entry has picked
    from the table, not departed from it.
    """
    category = asset.get("asset_category")
    if category in schedule_ii.NOT_DEPRECIABLE:
        return None
    classes = schedule_ii.CATEGORIES.get(category or "")
    # A category Schedule II prescribes nothing for cannot be departed FROM.
    # Creation already refuses those without a figure (_no_statutory_basis).
    if not classes or all(c["useful_life_years"] is None for c in classes):
        return None

    method = (asset.get("depreciation_method") or "WDV")
    method = getattr(method, "value", method)
    if method == "SL":
        stored = asset.get("useful_life_years")
        if stored is None:
            return None
        if any(c["useful_life_years"] == int(stored) for c in classes):
            return None
        field, prescribed = "useful_life_years", sorted(
            {c["useful_life_years"] for c in classes if c["useful_life_years"]})
    else:
        stored = asset.get("wdv_rate_percent")
        if stored is None:
            return None
        stored_d = Decimal(str(stored)).quantize(Decimal("0.01"))
        if any(c["wdv_rate_percent"] is not None
               and c["wdv_rate_percent"] == stored_d for c in classes):
            return None
        field, prescribed = "wdv_rate_percent", sorted(
            {float(c["wdv_rate_percent"]) for c in classes
             if c["wdv_rate_percent"] is not None})

    return {
        "kind": "depreciation_basis_departs_from_schedule_ii",
        "asset_code": asset.get("asset_code"),
        "asset_name": asset.get("asset_name"),
        "asset_category": category,
        "field": field,
        "stored": float(stored),
        "schedule_ii_prescribes": prescribed,
        "what_it_means": (
            f"This asset depreciates on a {field.replace('_', ' ')} of {stored}, "
            f"which is not one Schedule II Part C prescribes for '{category}'. "
            "That is ALLOWED — Part A permits a different useful life or residual "
            "value — but it must be disclosed in the accounts and justified. "
            "Correct it on the asset, or keep it and disclose it."),
    }


def wdv_with_no_stopping_point(asset: dict) -> Optional[dict]:
    """A reducing-balance asset with nothing to stop it (FA-13).

    `_wdv_residual_at_end_of_life` needs the row's own useful life to work out
    where the charge ends. Where there is no life recorded, the only terminal
    left is `salvage_value_paise` — and a reducing balance never reaches a
    salvage of zero, which is the column's default and what the form
    pre-fills. Such a row is charged for ever, in ever-smaller amounts, long
    after the asset is worn out.

    Reported rather than repaired, for the same reason FA-02's departure is:
    the life is a Schedule II Part C judgement about THIS asset, and writing
    one in from the category default would change the charge on a row a CA may
    have deliberately left open. Naming it costs a CA one edit; guessing it
    moves the profit.

    Not raised for Land (never depreciated), for a category Schedule II
    prescribes nothing for (there is no life to have recorded), or where the
    rate is 0.00 or the asset is already fully depreciated — none of those
    keeps charging.
    """
    category = asset.get("asset_category")
    if category in schedule_ii.NOT_DEPRECIABLE:
        return None
    method = asset.get("depreciation_method") or "WDV"
    method = getattr(method, "value", method)
    if method != "WDV":
        return None                    # SL divides by the life; it terminates
    if asset.get("useful_life_years"):
        return None
    classes = schedule_ii.CATEGORIES.get(category or "")
    if not classes or all(c["useful_life_years"] is None for c in classes):
        return None
    if int(asset.get("salvage_value_paise") or 0) > 0:
        return None                    # the salvage is the terminal
    rate = asset.get("wdv_rate_percent")
    if rate is None or Decimal(str(rate)) <= 0:
        return None                    # nothing is being charged
    cost = int(asset.get("purchase_cost_paise") or 0)
    accum = int(asset.get("accumulated_depreciation_paise") or 0)
    if cost <= 0 or cost - accum <= 0:
        return None
    prescribed = sorted({c["useful_life_years"] for c in classes
                         if c["useful_life_years"]})
    return {
        "kind": "wdv_asset_has_no_stopping_point",
        "asset_code": asset.get("asset_code"),
        "asset_name": asset.get("asset_name"),
        "wdv_rate_percent": float(rate),
        "prescribed_useful_life_years": prescribed,
        "amount_paise": cost - accum,
        "what_it_means": (
            "This asset depreciates on the reducing balance with no useful life "
            "recorded and no salvage value, so nothing ever stops the charge — "
            "it keeps writing the asset down after it is fully depreciated. "
            "Record the useful life (Schedule II Part C gives "
            f"{', '.join(str(y) for y in prescribed)} year"
            f"{'s' if prescribed != [1] else ''} for this category) or a salvage "
            "value, and the charge will stop where Schedule II says it should."),
    }


def register_findings(assets: Iterable[dict], live_bill_ids: set) -> list[dict]:
    """Every finding over one client's register.

    `assets` are `fixed_assets` rows with the soft-deleted ones already
    excluded by the caller's query. `live_bill_ids` is the set of
    `purchase_bills.id` that still exist, which the caller resolves because
    only it has the database — passing an EMPTY set therefore reports every
    bill-backed asset as orphaned, so a caller that cannot resolve them must
    not call this rather than passing nothing.
    """
    findings: list[dict] = []
    by_bill: dict[str, list[dict]] = {}

    for a in assets:
        if not a.get("journal_entry_id"):
            findings.append({
                "kind": "no_acquisition_journal",
                "asset_code": a.get("asset_code"),
                "asset_name": a.get("asset_name"),
                "amount_paise": int(a.get("purchase_cost_paise") or 0),
                "what_it_means": (
                    "This asset is in the register and no journal entry ever put "
                    "it on the balance sheet."),
            })
        # A disposed asset's basis is settled — see the module docstring.
        if not a.get("is_disposed"):
            departure = schedule_ii_departure(a)
            if departure:
                findings.append(departure)
            no_terminal = wdv_with_no_stopping_point(a)
            if no_terminal:
                findings.append(no_terminal)
        if a.get("purchase_bill_id"):
            by_bill.setdefault(a["purchase_bill_id"], []).append(a)

    for bill_id, group in by_bill.items():
        if len(group) > 1:
            findings.append({
                "kind": "bill_capitalised_more_than_once",
                "purchase_bill_id": bill_id,
                "asset_codes": [x.get("asset_code") for x in group],
                "amount_paise": sum(int(x.get("purchase_cost_paise") or 0) for x in group),
                "what_it_means": (
                    "One purchase bill is capitalised as several assets, so its "
                    "cost is in Fixed Assets more than once."),
            })

    for bill_id, group in by_bill.items():
        if bill_id not in live_bill_ids:
            findings.append({
                "kind": "capitalised_from_a_bill_that_is_gone",
                "purchase_bill_id": bill_id,
                "asset_codes": [x.get("asset_code") for x in group],
                "what_it_means": (
                    "The entry only moved cost out of purchases; with the bill "
                    "deleted, nothing supports the asset."),
            })

    return findings
