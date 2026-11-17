"""An edit that can say "take this value away" (POST-A-399).

WHAT WAS WRONG
    A PATCH route that reads its body with `model_dump(exclude_none=True)` cannot tell "the person did not touch this box" from "the person
    emptied it": both arrive as no value. The edit screens made it worse by sending `value || undefined`, which drops the key from the JSON
    altogether. So a CA who emptied the note or the reference of an invoice and pressed Save was told it was saved, and the old value was
    still there when the invoice was opened again.

WHAT THIS DOES
    An update model names the fields a person MAY clear in `CLEARABLE`. `patch_dict` returns what `model_dump(exclude_none=True)` returned, and
    adds a field of that set as `None` when the request SENT it as null or, for text, as a blank: `None` in the dict is "write NULL". For a
    field that is not in `CLEARABLE` nothing changes: a null still reads "not sent" (and a default that is not None still appears, as it
    always did), so a caller that has always sent nulls for the fields it does not mean to change is not turned into one that erases them.
    The one other difference is a blank string for a CLEARABLE field: it used to be stored as "" (a date column refused it with a 500), and
    now it clears, because a note of nothing is no note.

    WHICH FIELDS ARE CLEARABLE IS A DECISION PER ROUTE, and the rule for it is short: a soft, optional, free-text particular that the person
    typed (a note, a reference) is clearable; anything that is the EVIDENCE of the document, a REQUIRED particular, a figure, or a value
    that every document of its kind carries (a due date: a create that names none resolves one, and the collections and ageing readers
    say so) is not. Those still read null as "not sent", and the screen, not the route, decides what to do about an emptied box over
    them: the evidence DATES are refused at the screen (POST-A-388: the shipping bill date, the Form 15CA date, a no-PE declaration date,
    a bank account's opening-balance date) and so is a due date that is on file (this slice); the evidence TEXTS (the bill number, a
    Form 15CA acknowledgement number and UDIN, a shipping bill number and a port code) are neither cleared nor refused yet, which is
    still POST-A-399's.

    Every `CLEARABLE` name on a model that is read through `patch_dict` is held by
    `tests/test_an_emptied_box_on_an_edit_clears_the_stored_value.py` to be an optional field of that model and a column that accepts NULL in
    the production schema snapshot of 3 September 2026 (a model with a CLEARABLE set that the test does not know the table of fails it), so a
    clear does not reach a NOT NULL column as that snapshot stood. The snapshot goes stale by design (see docs/schema-drift.md): a migration
    that made one of these columns NOT NULL would be caught only once the snapshot is refreshed, and a clear of it would answer 500 until then.
"""
from __future__ import annotations

from typing import Any, FrozenSet, Iterable

from pydantic import BaseModel


def clearable_fields(model: BaseModel) -> FrozenSet[str]:
    """The fields of this update model a person may clear: its `CLEARABLE` class attribute, or none."""
    return frozenset(getattr(type(model), "CLEARABLE", ()) or ())


def patch_dict(model: BaseModel) -> dict[str, Any]:
    """What an update route writes: `model_dump(exclude_none=True)`, plus each CLEARABLE field the request SENT as null or as a blank string, as `None`.

    A CLEARABLE field that was not sent is absent whatever the model's default is. Every other field is exactly what `exclude_none` returns for
    it. A route that moves from `exclude_none` to this changes behaviour only for the fields its model names.
    """
    out = model.model_dump(exclude_none=True)
    clearable = clearable_fields(model)
    for name in clearable - model.model_fields_set:
        out.pop(name, None)
    for name in clearable & model.model_fields_set:
        value = getattr(model, name, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            out[name] = None
    return out


def removed_identifier_problem(model: BaseModel, stored: dict, labels: dict[str, str]) -> str | None:
    """The sentence refusing an edit that EMPTIES an identifier the stored row carries, or None (POST-A-399, the party masters).

    A tax identifier a return reads off a party (its GSTIN and the state code that follows it, and a vendor's PAN and foreign tax number) is
    corrected and not removed by an edit: every GST return not yet filed reads the party's GSTIN and state code LIVE for the documents already
    issued to it (a recipient with a GSTIN is B2B, one without is B2C, and §16(2)(aa) sends the credit to whoever the GSTIN names), so emptying one
    would silently move documents already issued between tables of a return. A customer's PAN and TAN are not passed here, because no return reads
    them and the sentence would be untrue of them. `labels` maps each field the route refuses to empty to the words a person reads. A field the
    request SENT empty (null or blank) over a stored value is refused; one sent empty over nothing is not this function's to refuse (the route drops
    it, so nothing is written).
    """
    for name, label in labels.items():
        if name not in model.model_fields_set:
            continue
        value = getattr(model, name, None)
        if (value is None or (isinstance(value, str) and not value.strip())) and str(stored.get(name) or "").strip():
            return (f"The {label} on file can be corrected but not removed: enter the corrected {label}. "
                    f"Every return not yet filed reads it for the documents already issued to this party.")
    return None


def drop_empty(payload: dict[str, Any], names: Iterable[str]) -> dict[str, Any]:
    """Remove each of `names` the payload carries as a blank string, so an empty box over nothing writes nothing (and never a stored "")."""
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and not value.strip():
            payload.pop(name, None)
    return payload
