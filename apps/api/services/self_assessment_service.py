"""Fetches the Challan 280 records `domain/income_tax/self_assessment.py`
decides with (IT-13).

The split is the one every statutory module here makes: the domain module is
pure — it takes payments and dues and applies §140A(1)'s appropriation order —
and this one reads the rows. So the order can be unit-tested against a table of
figures with no database, and the reading is exercised separately.

WHAT THIS MODULE IS FOR BEYOND THE SCREEN

    The keying sheet (IT-17) printed `self_assessment_tax` as NIL on every
    return with the sentence *"Nothing here records a Challan 280"*. That is
    true of a product that holds no such record, and it stops being true here:
    `total_paid_paise` is the figure Schedule IT's own rows add up to, and it
    is passed INTO the sheet rather than derived there, because
    `keying_sheet` derives nothing and a test walks its AST to keep it that
    way.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to the Income Tax Portal
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from domain.income_tax import self_assessment as sa

_logger = logging.getLogger("caflow.self_assessment")

def list_challans(db, *, firm_id: str, client_id: str,
                  financial_year: str) -> list[dict]:
    """Every challan recorded for one client-year, oldest deposit first.

    Ordered by the DEPOSIT DATE rather than by `created_at`: §140A(1)'s
    appropriation walks the payments as they were MADE, and a CA entering an
    old receipt after a recent one must not change what settled first. The
    serial number breaks a tie on one day, so the order is total.

    The response is bounded by how many challans one return was accompanied by
    — in practice one or two, never more than a handful — so this is a row set
    whose size is the size of the answer, and it is not paged.

    THE PROJECTION IS A LITERAL AT THE CALL SITE and deliberately not a module
    constant, which reads like the thing to factor out and is not:
    `test_backend_columns_exist_pg` checks every `.select()` in `apps/api`
    against the real schema AS A STRING, and a projection reached through a
    name is invisible to it — it counts as an unreadable reference instead.
    The same decision `domain/firm/identity`'s three projections record.

    `minor_head` matters more than it looks: `position` names a challan paid
    under the wrong head, and a projection omitting it would make that check a
    silent no-op — the `is_opening` trap.
    """
    if not db:
        return []
    res = (db.table("self_assessment_challans").select(
        "id, client_id, financial_year, bsr_code, deposit_date, "
        "challan_serial_no, tax_paise, surcharge_paise, cess_paise, "
        "interest_paise, fee_paise, total_paise, major_head, minor_head, "
        "bank_name, notes, created_at")
           .eq("firm_id", firm_id).eq("client_id", client_id)
           .eq("financial_year", financial_year)
           .order("deposit_date").order("challan_serial_no").execute())
    return list(res.data or [])


#: Re-exported so a caller that has already fetched the rows totals them the
#: way the domain module does, rather than writing `sum(...)` a second time.
total_paise_of = sa.total_paise_of


def total_paid_paise(db, *, firm_id: str, client_id: str,
                     financial_year: str) -> int:
    """The same figure, for a caller that has not fetched the rows."""
    return sa.total_paise_of(list_challans(
        db, firm_id=firm_id, client_id=client_id,
        financial_year=financial_year))


def position(
    db,
    *,
    firm_id: str,
    client_id: str,
    financial_year: str,
    tax_due_paise: Optional[int] = None,
    interest_due_paise: Optional[int] = None,
    fee_due_paise: Optional[int] = None,
) -> dict[str, Any]:
    """The year's challans and, where the dues are stated, how they land.

    The dues are the CALLER's — the tax off the computation, the interest off
    the Advance Tax screen's §234A/B/C working, the fee off §234F, which is not
    modelled here at all. Passing them in rather than reading them is what
    keeps a second income-tax engine out of this module: see
    `self_assessment.INTEREST_IS_NOT_DERIVED_HERE`.
    """
    challans = list_challans(db, firm_id=firm_id, client_id=client_id,
                             financial_year=financial_year)
    return sa.position(
        financial_year=financial_year,
        challans=challans,
        tax_due_paise=tax_due_paise,
        interest_due_paise=interest_due_paise,
        fee_due_paise=fee_due_paise,
    ).to_dict()
