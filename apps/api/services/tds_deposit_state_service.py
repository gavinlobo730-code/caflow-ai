"""What became of a client's tax deductions, for the TDS screen: the deposit position and each deduction's state, from the register.

READS ONE CLIENT'S ROWS, not the firm's: the deductions (keyset-paged with `fetch_all`, no ordering of its own) and the challans of
the client, which is the volume the screen lists anyway. The position the cards show is the DATABASE's (`tds_position_service`, the
reader the hub's tile uses, so the card and the tile are one figure); each row's state is `domain/tds/deposit_state`, the same
register rule applied row by row (a quarter with a challan recorded is judged first in first out, one with none is NOT RECORDED).
`tests/test_the_tds_screen_asks_the_server_what_became_of_a_deduction.py` holds the two to one fixture over the registry's sections, so
the column cannot say a row is deposited while the card says the quarter is short.

A POSITION THAT CANNOT BE READ IS `None`, NOT A ZERO, AND IT DOES NOT TAKE THE ROWS DOWN WITH IT. The rows' states do not need the
database function (a deployment where migration 523 has not applied yet, or a failed call, loses the card and keeps the column), and
the screen shows the card as unread; the route still answers success, with `position` null. `figure_known` is false when the position's
nil judges nothing: tax was deducted and no quarter of it has a challan recorded, or the only tax deducted is salary, which payroll
deposits and this register never judges. A headline of ₹0.00 over a sentence in small type is the unknown shown as a value.

THE ANSWER IS SIZED BY ITS ROWS, NOT BY ITS WORDS. A row is its state, and only what is true of that row besides: the serials that
paid it, whether it is late (not paid by the date, or paid after it) and by when, and (for a part, or a challan dated before the tax)
its own sentence. The label and the
sentence of each state are sent once in `legend`, because a firm that keeps its deposits elsewhere has thousands of rows that would
each repeat them.
"""
from __future__ import annotations

import logging
from typing import Optional

from core.db_paging import fetch_all
from core.ist_clock import ist_today
from domain.hub.tiles import not_recorded_caveat
from domain.tds import deposit_due, deposit_state
from domain.tds.undeposited import is_salary
from services import compliance_engine, tds_position_service

_logger = logging.getLogger("caflow.tds.deposit_state")

#: Salary tax is never in these figures: payroll deducts and deposits it, and it is not a row of `tds_deductions` unless somebody typed
#: one. A client who runs payroll and has no other deduction would otherwise read ₹0.00 and "nothing is waiting".
BASIS_SALARY_NOT_IN_IT = " (salary tax is not in this figure: payroll deposits it)"
BASIS_JUDGED = "From the challan register, in quarters with a challan recorded" + BASIS_SALARY_NOT_IN_IT
BASIS_NOTHING_JUDGED = "No quarter with tax in it has a challan recorded, so there is nothing to judge it against"
BASIS_NOTHING_OWED = "No tax recorded here is waiting for a deposit" + BASIS_SALARY_NOT_IN_IT
BASIS_ONLY_SALARY = "The only tax recorded here is salary tax, which payroll deposits and this register does not judge"


def _due_date_of(on):
    # Rule 30(2): the one definition of the date a month's deductions fall due, `compliance_engine`'s.
    return compliance_engine.tds_deposit_due_date(on.year, on.month)


def read(db, firm_id: str, client_id: str, *, position: Optional[tuple[int, int]] = None) -> dict:
    """The deposit state of one client. `position` is given by a caller that already has the database's figure (a test)."""
    deductions = fetch_all(
        lambda: (db.table("tds_deductions")
                 .select("id, section, transaction_date, tds_paise, surcharge_paise, cess_paise")
                 .eq("firm_id", firm_id).eq("client_id", client_id)),
        label="tds.deposit_state.deductions")
    challans = fetch_all(
        lambda: (db.table("tds_challans")
                 .select("id, challan_no, bsr_code, section, financial_year, quarter, tds_paise, surcharge_paise, payment_date, "
                         "minor_head")
                 .eq("firm_id", firm_id).eq("client_id", client_id)),
        label="tds.deposit_state.challans")
    if position is None:
        try:
            position = tds_position_service.read(db, firm_id, [client_id])
        except Exception:                                       # noqa: BLE001 - the rows are still worth answering
            _logger.exception("caflow.tds.deposit_state: the position could not be read for client %s", client_id)
            position = None
    return assemble(client_id, deductions, challans, position)


def assemble(client_id: str, deductions: list, challans: list, position: Optional[tuple[int, int]]) -> dict:
    """The answer, from rows already read (also what mock mode serves). `position` None is a position that was not read."""
    judgement = deposit_state.judge(deductions, challans, due_date_of=_due_date_of, today=ist_today())
    states = judgement.states
    rows = {}
    for key, st in states.items():
        _label, own_sentence = deposit_state.words(st)
        row = {"state": st.state}
        # A key is present only when it says something: a client's year can be thousands of rows, and most are a state alone.
        for name, value in (("detail", own_sentence), ("due_note", deposit_state.due_note(st)), ("overdue", st.overdue or None),
                            ("paid_late", st.late_on is not None or None), ("challans", list(st.challans) or None),
                            ("dated_before", st.dated_before or None)):
            if value is not None:
                row[name] = value
        rows[key] = row
    judged_any = any(st.state in deposit_state.JUDGED for st in states.values())
    salary_tax = any(is_salary(d.get("section")) and deposit_due.tax_of(d) > 0 for d in deductions)
    out_position = None
    if position is not None:
        undeposited, not_recorded = position
        known = judged_any or (not_recorded == 0 and not salary_tax)
        if judged_any:
            basis = BASIS_JUDGED
        elif not_recorded > 0:
            basis = BASIS_NOTHING_JUDGED
        elif salary_tax:
            basis = BASIS_ONLY_SALARY
        else:
            basis = BASIS_NOTHING_OWED
        out_position = {"undeposited_paise": undeposited, "not_recorded_paise": not_recorded, "figure_known": known,
                        "basis": basis, "caveat": not_recorded_caveat(not_recorded)}
    return {
        "client_id": client_id,
        "position": out_position,
        # Everything deducted for the client, whatever the section (salary rows included) and with surcharge and cess: what the
        # "Total TDS Deducted" card shows, so that it and "Tax not yet deposited" count tax the same way.
        "totals": {"deducted_paise": sum(max(0, deposit_due.tax_of(d)) for d in deductions)},
        "deductions": rows,
        "legend": deposit_state.legend(),
        "warnings": deposit_state.register_warnings(challans) + judgement.surplus,
        "read": f"{len(deductions)} deduction{'' if len(deductions) == 1 else 's'} and {len(challans)} "
                f"challan{'' if len(challans) == 1 else 's'} of this client.",
    }
