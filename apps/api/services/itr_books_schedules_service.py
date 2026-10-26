"""Part A of the return from the books: the reads behind `domain/income_tax/books_schedules` (POST-A-070).

This module reads and hands over; it decides nothing. The decisions (which box a figure answers, what is left for the CA to split, the
tie-out) are the domain module's, and the figures are other modules' answers, taken whole:

    the year-end statements  — `year_end_financial_service.generate_financial_statements`, the one place the ledger becomes a balance
                               sheet and a profit and loss account, so what is keyed is what the CA signed;
    the §32 working          — `section_32_service.assemble`, the one place the block register becomes an allowance;
    the register's movement  — `domain/reporting/fixed_asset_movement`, the one place the register becomes a gross block.

A second read of the ledger here would be a second answer to "what does the balance sheet say", which is the defect this repository
keeps recording. The reads this module makes itself are the register's rows, because the movement function takes rows and every read
of `fixed_assets` goes through `core.db_paging.fetch_all`, and, for the one form that takes tangible and intangible assets apart (ITR-6),
the chart account each asset category is booked to (POST-A-344): the account is found by the posting kernel's own lookup
(`domain/fixed_assets/asset_ledger` names the ledger and `_find_account` resolves it, as the acquisition, capitalisation and disposal
journals do) and what is read of it is only its type, subtype and the CA's Schedule III mapping, handed to the one function that says
which line an account is on. No balance is read from it.

THE FILING DECIDES THE FORM AND THE YEAR, never the request: the sheet is for the return that is being furnished, as the keying sheet
is. A filing for a form that carries no balance sheet is refused in a sentence and not answered with an empty sheet.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to the Income Tax Portal
"""
from __future__ import annotations

from typing import Any, Optional

from core.db_paging import fetch_all
from domain.fixed_assets.asset_ledger import ledger_pattern
from domain.income_tax import books_schedules
from domain.reporting import fixed_asset_movement as fa_movement
from domain.reporting.year_end_lines import schedule_line_for_account
from services.section_32_service import fy_window, section_32_service


class NotAssembled(Exception):
    """The return has no Part A to assemble (its form carries none), or the books cannot be assembled for its year."""


def _ledger_lines(db: Any, firm_id: str, client_id: str, categories: list[str]) -> dict[str, Optional[str]]:
    """The Schedule III line of the ledger each asset category is booked to; None for a category whose ledger cannot be found.

    The ledger is the one the journals debit (`ledger_pattern` and `_find_account`, so a category is read from the account the posting
    used and not from a second guess), and its line is the one the year-end statements derive for it, the CA's own Schedule III mapping
    on the account included. A stored `account_group_mappings` row, which the statements let override the derived line, is NOT read (no
    screen writes one and production holds none); an account such a row moved is on a different line there than here, so its category's
    net block fails the tie and the split is withheld, never placed.
    """
    from services.phase2_journal_service import phase2_journal_service

    out: dict[str, Optional[str]] = {}
    for category in categories:
        try:
            account_id = phase2_journal_service._find_account(db, firm_id, client_id, ledger_pattern(category))
        except ValueError:
            out[category] = None
            continue
        found = (db.table("chart_of_accounts").select("account_type,account_subtype,schedule_iii_mapping")
                 .eq("firm_id", firm_id).eq("id", account_id).limit(1).execute().data or [])
        out[category] = (schedule_line_for_account(found[0].get("account_type"), found[0].get("account_subtype"),
                                                   found[0].get("schedule_iii_mapping")) if found else None)
    return out


def _register(db: Any, firm_id: str, client_id: str, fy_end: str, form: str):
    """The fixed-asset register's closing gross block, accumulated depreciation and net block, or None where there is no database.

    For a form that takes tangible and intangible assets apart the answer also carries the movement of each category and the line each
    is booked to, and the domain module splits the register by them only where it ties to the ledger.
    """
    if db is None:
        return None
    rows = fetch_all(
        lambda: (db.table("fixed_assets").select("*")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .is_("deleted_at", "null")),
        label="itr_books_schedules.fixed_assets")
    movement = fa_movement.movement_from_rows(rows, fy_end)
    totals = movement.totals
    out = {"gross": totals["closing_gross_paise"], "accumulated": totals["closing_accum_paise"],
           "net": totals["closing_net_paise"], "split_known": movement.split_known}
    if books_schedules.splits_fixed_assets(form):
        out["classes"] = movement.classes
        out["ledger_lines"] = _ledger_lines(db, firm_id, client_id, books_schedules.register_categories_to_place(movement.classes))
    return out


def for_filing(db: Any, *, firm_id: str, filing: dict) -> dict:
    """Part A-BS, Part A-P&L and the depreciation schedules for one ITR filing, from the books as they stand."""
    from services.year_end_financial_service import generate_financial_statements

    form = str(filing.get("itr_form") or "")
    if form not in books_schedules.FORMS:
        raise NotAssembled(
            f"{form or 'This filing'} carries no balance sheet or profit and loss account of its own to assemble; Part A is for "
            f"{', '.join(books_schedules.FORMS)}.")
    client_id = str(filing.get("client_id") or "")
    financial_year = str(filing.get("financial_year") or "")
    try:
        fy_start, fy_end = fy_window(financial_year)
    except (ValueError, TypeError) as exc:
        raise NotAssembled(f"The filing's financial year ({financial_year!r}) is not a year the books can be read for.") from exc

    try:
        statements = generate_financial_statements(db, client_id, firm_id, fy_start.isoformat(), fy_end.isoformat())
    except ValueError as exc:
        # The statements refuse a ledger whose balance sheet does not balance, and say why in a sentence of their own.
        raise NotAssembled(str(exc)) from exc

    if db is None:
        # No database configured (mock mode, local dev): the statements above are the mock's, and there are no blocks or register.
        section_32 = {"blocks": [], "allowance_paise": 0, "short_term_capital_gain_paise": 0, "statutory_gaps": [],
                      "unclassified_assets": [], "blocks_without_opening_wdv": []}
    else:
        section_32 = section_32_service.assemble(db, firm_id, client_id, financial_year)

    return books_schedules.assemble(
        form=form, assessment_year=str(filing.get("assessment_year") or ""), financial_year=financial_year,
        statements=statements, section_32=section_32, register=_register(db, firm_id, client_id, fy_end.isoformat(), form))
