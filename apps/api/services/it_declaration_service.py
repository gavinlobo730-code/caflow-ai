"""Filing an employee's Form 12BB declaration: ONE database function, ONE transaction (POST-A-340, migration 548).

WHY THIS EXISTS
    A declaration is a header (`payroll_it_declarations`) and its Chapter VI-A lines (`payroll_it_declaration_items`). Both doors that
    file one, the employee's own (`PUT /api/portal/employee/tax-declaration`) and the staff one (`PUT /api/payroll/declarations`),
    wrote them as separate requests: the header, the new lines, the removal of the old ones. Two filings of one declaration at the
    same instant (a second tab, or the web client's retry after a network failure the server had already served) could leave the
    header of one beside the lines of the other, and the employee door carried a read-back and a put-back, the best a client of the
    database can do without a transaction. `public.file_it_declaration` does the whole filing in one transaction under a row lock;
    this module is the one place the API calls it and the one place its refusals are turned into words.

WHAT IT DECIDES AND WHAT IT LEAVES
    * It decides nothing about the declaration. Validation (`domain.payroll.declarations.validate`), who may file and the audit
      row are the doors' and happen before and after the call.
    * `refuse_verified` is the employee door's: a declaration the CA has finished verifying is no longer the employee's to change,
      and the function refuses it inside the same transaction that would have changed it (`DeclarationVerified`). The staff door
      passes False and replaces a verified declaration as it always has, with every verified column reset.
    * `DeclarationBusy` is the function giving up after three tries to take the row (SQLSTATE 40001): the filing was NOT made.

THE PAYLOAD
    `HEADER_KEYS` names the header columns the function reads out of `p_declaration`, written out in full so that the column check
    (`tests/test_backend_columns_exist_pg.py`) and the 548 test, which reads every column of the table from the schema and finds
    each one in the function, are the two places a misspelt or forgotten one is seen.
"""
from __future__ import annotations

import re
from typing import Any

from core.db_provider import privileged_for

#: What the function reads from `p_declaration`, in the order the table has them.
HEADER_KEYS = (
    "firm_id", "client_id", "employee_id", "fy", "regime",
    "rent_paid_declared_paise", "landlord_name", "landlord_address", "landlord_pan", "rent_is_metro",
    "lta_declared_paise", "home_loan_interest_declared_paise", "lender_name", "lender_pan",
    "other_income_declared_paise", "house_property_loss_declared_paise",
)

#: What the function reads from each element of `p_items`.
ITEM_KEYS = ("section", "label", "amount_declared_paise", "proof_reference", "proof_attachments")

FUNCTION = "file_it_declaration"

_VERIFIED = re.compile(r"^(?:ERROR:\s+)?declaration_verified:")
_NOT_THE_EMPLOYEES = re.compile(r"^(?:ERROR:\s+)?file_it_declaration: employee")


class DeclarationVerified(Exception):
    """The CA has finished verifying this declaration and the caller may not change it. Nothing was written."""


class DeclarationBusy(Exception):
    """The function could not take the declaration's row (another filing held it three times running). Nothing was written."""


class DeclarationOutOfScope(Exception):
    """The employee is not an employee of this client of this firm. Nothing was written (the routes prove it first)."""


def _message(exc: Exception) -> str:
    return str(getattr(exc, "message", None) or exc)


def _code(exc: Exception) -> str:
    return str(getattr(exc, "code", "") or "")


def file_declaration(
    db: Any, *, firm_id: str, client_id: str, employee_id: str, fy: str, regime: str,
    rent_paid_declared_paise: int, landlord_name: str, landlord_address: str, landlord_pan: str, rent_is_metro: bool,
    lta_declared_paise: int, home_loan_interest_declared_paise: int, lender_name: str, lender_pan: str,
    other_income_declared_paise: int, house_property_loss_declared_paise: int,
    items: list[dict], refuse_verified: bool,
) -> str:
    """File the declaration and return its id. The lines given are the declaration's lines; whatever else it held is gone.

    `db` is the doors' own server client (or a double); the call itself is made through `privileged_for(db)`. `items` are dicts with `ITEM_KEYS`. The caller decides which lines to give (the employee door leaves out a head declared at
    nothing, the staff door gives every line it was sent): this module does not second-guess it.
    """
    declaration = {
        "firm_id": firm_id, "client_id": client_id, "employee_id": employee_id, "fy": fy, "regime": regime,
        "rent_paid_declared_paise": rent_paid_declared_paise,
        "landlord_name": landlord_name, "landlord_address": landlord_address, "landlord_pan": landlord_pan,
        "rent_is_metro": rent_is_metro,
        "lta_declared_paise": lta_declared_paise,
        "home_loan_interest_declared_paise": home_loan_interest_declared_paise,
        "lender_name": lender_name, "lender_pan": lender_pan,
        "other_income_declared_paise": other_income_declared_paise,
        "house_property_loss_declared_paise": house_property_loss_declared_paise,
    }
    lines = [{k: it.get(k) for k in ITEM_KEYS} for it in items]
    try:
        # The function is executable by the service role alone, and called on a signed-in session's client the database refuses it
        # whoever asks, so it is called through `privileged_for`: the privileged client, carrying the person the request acts for to
        # the edit log (migration 547) where a person is in flight, and the caller's own `db` where no database is configured.
        out = privileged_for(db).rpc("file_it_declaration", {      # a literal, so the schema guard and the rpc scanner can read the name
            "p_declaration": declaration, "p_items": lines, "p_refuse_verified": bool(refuse_verified),
        }).execute()
    except Exception as exc:  # noqa: BLE001 - turned into the module's own refusals, or re-raised unchanged
        message, code = _message(exc), _code(exc)
        # PostgREST sends the function's own words as `message`; a client that reports the server's whole text (the real-database
        # test double does) puts "ERROR:  " in front of them.
        if _VERIFIED.match(message):
            raise DeclarationVerified(message) from exc
        if code == "40001":
            raise DeclarationBusy(message) from exc
        # 42501 is also what the database answers when the function is not granted to the client that called it ("permission denied
        # for function"), which is a deployment fault and must reach the caller as one, not as "employee not found".
        if code == "42501" and _NOT_THE_EMPLOYEES.match(message):
            raise DeclarationOutOfScope(message) from exc
        raise
    declaration_id = out.data
    # A uuid comes back as a bare JSON string. Anything else means the function did not do what this module was written against.
    if not declaration_id or not isinstance(declaration_id, str):
        raise RuntimeError(f"{FUNCTION} answered {declaration_id!r}, not the declaration's id")
    return declaration_id
