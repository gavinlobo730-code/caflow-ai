"""
Assembling one client's IT Act §32 blocks for one previous year.

WHERE EACH FACT COMES FROM, AND WHY THE SPLIT IS WHERE IT IS

    DERIVED from the fixed-asset register, because the register genuinely holds
    it:
      * ADDITIONS  — an asset whose purchase date falls in the previous year,
                     at its actual cost;
      * DELETIONS  — an asset disposed of in the previous year, at the MONEYS
                     PAYABLE (§43(6)(c)(i)(B)), which is the disposal value, not
                     the asset's cost and not its book value.

    STORED, because nobody can derive it (migration 357):
      * WHICH BLOCK an asset falls in. §2(11) groups by nature AND rate, and the
        Schedule II categories on the register do not map onto it — "Plant &
        Machinery" is one Schedule II category and several §32 blocks.
      * THE RATE, which is half a block's identity under §2(11) and comes out of
        Appendix I, a statutory table this repository does not write from memory.
      * THE OPENING WRITTEN-DOWN VALUE, which comes off last year's return.
      * WHETHER ANY ASSET OF THE BLOCK REMAINS, which §50 turns on and which the
        money cannot answer.
      * WHEN AN ASSET WAS PUT TO USE, which is what the second proviso to
        §32(1) turns on — never the purchase date.

WHAT IS REFUSED RATHER THAN GUESSED

An asset with no `it_block_key` is NOT placed in a block. There is no default
that is safe: putting it in the wrong block charges the wrong rate on the wrong
base for the rest of the asset's life, and putting it in no block silently drops
its cost out of the allowance. It is named, per asset, in `unclassified`.

A block referenced by an asset but with no opening row is likewise named. A
missing opening written-down value is not a zero — a zero allows no depreciation
at all on a block that may have been running for a decade.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from core.db_paging import fetch_all
from domain.income_tax import additional_depreciation as addl
from domain.income_tax import itr_depreciation_rows as itr_rows
from domain.income_tax.section_32 import (
    Addition, Block, Deletion, Section32Result, compute,
)


def _d(value) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def fy_window(financial_year: str) -> tuple[date, date]:
    """(1 April, 31 March) for a 'YYYY-YY' label. April to March (CLAUDE.md)."""
    start_year = int(str(financial_year)[:4])
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def block_to_dict(b, itr_schedule_row: Optional[str] = None) -> dict:
    """One block's result as the service serves it. A function of its own so the Part A schedules' tests build their input with the
    SAME dict the screen is served, and cannot drift from it."""
    return {
        "block_key": b.key, "rate_percent": b.rate_percent,
        "opening_wdv_paise": b.opening_wdv_paise,
        "additions_full_rate_paise": b.additions_full_rate_paise,
        "additions_half_rate_paise": b.additions_half_rate_paise,
        "additions_not_put_to_use_paise": b.additions_not_put_to_use_paise,
        "deletions_paise": b.deletions_paise,
        "wdv_before_depreciation_paise": b.wdv_before_depreciation_paise,
        "depreciation_paise": b.depreciation_paise,
        "additional_depreciation_paise": b.additional_depreciation_paise,
        "closing_wdv_paise": b.closing_wdv_paise,
        "short_term_capital_gain_paise": b.short_term_capital_gain_paise,
        # The working behind the allowance, which the return's Schedule DPM and DOA print column by column
        # (domain/income_tax/books_schedules), and the row of the return the CA recorded for the block (migration 552; None until
        # somebody records it, and read with `.get` so a database that has not applied the migration yet reads as "none recorded"
        # and not as a fault).
        "realization_against_full_paise": b.realization_against_full_paise,
        "realization_against_half_paise": b.realization_against_half_paise,
        "depreciation_base_full_paise": b.depreciation_base_full_paise,
        "depreciation_base_half_paise": b.depreciation_base_half_paise,
        "depreciation_at_full_rate_paise": b.depreciation_at_full_rate_paise,
        "depreciation_at_half_rate_paise": b.depreciation_at_half_rate_paise,
        "additional_on_full_rate_additions_paise": b.additional_on_full_rate_additions_paise,
        "additional_on_half_rate_additions_paise": b.additional_on_half_rate_additions_paise,
        "itr_schedule_row": itr_schedule_row,
        # The words for the key, so the screen shows a caption and holds no list of rows of its own. A key the form no longer has reads
        # as the key itself, which is what a CA needs to see to record another.
        "itr_schedule_row_caption": (None if not itr_schedule_row else
                                     (lambda r: r.caption if r else itr_schedule_row)(itr_rows.row_by_key("ITR-3", itr_schedule_row))),
        "gaps": list(b.gaps),
    }


class Section32Service:
    def assemble(self, db, firm_id: str, client_id: str,
                 financial_year: str) -> dict:
        """The blocks, the computation, and everything that could not be placed.

        Returns the engine's answer plus the two lists a CA has to act on before
        it means anything: assets with no block, and blocks with no opening
        written-down value on record.
        """
        fy_start, fy_end = fy_window(financial_year)

        blocks_rows = (db.table("income_tax_asset_blocks").select("*")
                       .eq("firm_id", firm_id).eq("client_id", client_id)
                       .eq("financial_year", financial_year).execute().data or [])
        by_key = {r["block_key"]: r for r in blocks_rows}

        # EVERY page: an unpaged read stops at PostgREST's row cap (about 1,000) and a client with more assets than
        # that had its block allowance understated, silently. `fetch_all` calls the builder once per page.
        def _assets_query():
            return (db.table("fixed_assets").select("*")
                    .eq("firm_id", firm_id).eq("client_id", client_id)
                    .is_("deleted_at", "null"))

        assets = fetch_all(_assets_query, label="section_32.fixed_assets")

        # §32(1)(iia) (IT-09, migration 406). TWO facts, and this one is about
        # the CLIENT: the section reaches only an assessee engaged in
        # manufacture, production, or the generation, transmission or
        # distribution of power. `domain/income_tax/additional_depreciation`
        # decides; nothing here infers it from `industry` (free text) or
        # `business_type` (the legal form).
        #
        # A row that cannot be read leaves the fact UNRECORDED rather than
        # False — the distinction the hardcoded False destroyed.
        client_rows = (db.table("clients").select("id, section_32_1_iia_business")
                       .eq("firm_id", firm_id).eq("id", client_id)
                       .execute().data or [])
        within = addl.assessee_is_within_the_section(
            (client_rows[0] if client_rows else {}).get("section_32_1_iia_business"))
        addl_additions: list = []

        unclassified: list[dict] = []
        additions: dict[str, list[Addition]] = {}
        deletions: dict[str, list[Deletion]] = {}
        blocks_seen: set[str] = set()

        for a in assets:
            key = a.get("it_block_key")
            bought = _d(a.get("purchase_date"))
            sold = _d(a.get("disposal_date")) if a.get("is_disposed") else None
            in_year = ((bought and fy_start <= bought <= fy_end)
                       or (sold and fy_start <= sold <= fy_end))
            if not key:
                # Only worth naming if it would have MATTERED this year. An
                # unclassified asset bought four years ago and still held is a
                # gap in the opening written-down value somebody has already
                # entered, not a gap in this year's movement.
                if in_year:
                    unclassified.append({
                        "asset_id": a["id"], "asset_code": a.get("asset_code"),
                        "asset_name": a.get("asset_name"),
                        "asset_category": a.get("asset_category"),
                        "purchase_cost_paise": int(a.get("purchase_cost_paise") or 0),
                    })
                continue
            blocks_seen.add(key)
            if bought and fy_start <= bought <= fy_end:
                additions.setdefault(key, []).append(Addition(
                    label=a.get("asset_code") or a.get("asset_name") or a["id"][:8],
                    cost_paise=int(a.get("purchase_cost_paise") or 0),
                    # NOT the purchase date. Migration 357's own comment says
                    # why, and the engine reports a gap where it is absent
                    # rather than substituting one for the other.
                    put_to_use_date=_d(a.get("put_to_use_date")),
                    # §32(1)(iia) (IT-09). BOTH facts, ANDed in the domain
                    # module: the assessee has to be within the section and the
                    # asset has to be marked. An asset ticked at a client the
                    # section does not reach claims nothing, which is not a
                    # contradiction to resolve — a CA may mark their machines
                    # before recording the business.
                    additional_depreciation_eligible=addl.addition_is_eligible(
                        assessee_within_section=within.reaches_the_assessee,
                        asset_flag=a.get("additional_depreciation_eligible")),
                ))
                addl_additions.append((
                    a.get("asset_code") or a.get("asset_name") or a["id"][:8],
                    a.get("additional_depreciation_eligible")))
            if sold and fy_start <= sold <= fy_end:
                deletions.setdefault(key, []).append(Deletion(
                    label=a.get("asset_code") or a.get("asset_name") or a["id"][:8],
                    moneys_payable_paise=int(a.get("disposal_value_paise") or 0),
                ))

        blocks: list[Block] = []
        without_opening: list[str] = []
        for key in sorted(set(by_key) | blocks_seen):
            row = by_key.get(key)
            if row is None:
                without_opening.append(key)
                continue
            blocks.append(Block(
                key=key,
                rate_percent=int(row["rate_percent"]),
                opening_wdv_paise=int(row["opening_wdv_paise"]),
                additions=tuple(additions.get(key, ())),
                deletions=tuple(deletions.get(key, ())),
                assets_remain=row.get("assets_remain"),
            ))

        result: Section32Result = compute(blocks, fy_end=fy_end)
        gaps = list(result.gaps)
        # §32(1)(iia)'s own gaps come FIRST, because the business fact settles
        # every asset at once and a CA works down the list. Before IT-09 the
        # additional-depreciation row was a structural ₹0 with no sentence at
        # all, which reads as "there was none" rather than "nobody said".
        eligibility = addl.report(
            section_32_1_iia_business=(
                (client_rows[0] if client_rows else {}).get("section_32_1_iia_business")),
            additions=addl_additions)
        gaps = list(eligibility.gaps) + gaps
        if unclassified:
            gaps.append(
                f"{len(unclassified)} asset(s) bought or sold this year are not "
                f"assigned to a §32 block, so their cost is in no block's "
                f"written-down value. §2(11) groups by nature AND rate and the "
                f"Schedule II category does not decide it — assign them before "
                f"relying on this figure.")
        for key in without_opening:
            gaps.append(
                f"Block \"{key}\" has assets but no opening written-down value on "
                f"record for {financial_year}. It comes off last year's return; "
                f"a zero would allow no depreciation at all on a block that may "
                f"have been running for years, so the block is omitted.")

        return {
            "financial_year": financial_year,
            "period_start": fy_start.isoformat(),
            "period_end": fy_end.isoformat(),
            "blocks": [block_to_dict(b, (by_key.get(b.key) or {}).get("itr_schedule_row")) for b in result.blocks],
            "depreciation_paise": result.depreciation_paise,
            "additional_depreciation_paise": result.additional_depreciation_paise,
            # What the book-to-tax bridge deducts.
            "allowance_paise": result.total_allowance_paise,
            # NOT netted into the allowance — it belongs in the capital-gains
            # schedule, and §74 does not let a capital loss relieve business
            # income anyway.
            "short_term_capital_gain_paise": result.short_term_capital_gain_paise,
            # The §32(1)(iia) working, so the screen renders WHY the row is
            # what it is rather than a number with no account of itself.
            "additional_depreciation": eligibility.to_dict(),
            "unclassified_assets": unclassified,
            "blocks_without_opening_wdv": without_opening,
            "statutory_gaps": gaps,
            # The one thing a caller must not have to infer: whether this figure
            # is safe to put in a return.
            "is_complete": not gaps,
        }


section_32_service = Section32Service()
