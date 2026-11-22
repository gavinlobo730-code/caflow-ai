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
    a bank account's opening-balance date) and so is a due date that is on file; the evidence TEXTS (the bill number, a Form 15CA
    acknowledgement number and UDIN, a shipping bill number and a port code) are refused at the screen the same way
    (`apps/web/lib/forms/removedEvidence`, the sixth slice).

    WHAT ONLY A DRAFT MAY TAKE AWAY (the sixth slice) is a second, smaller set, `CLEARABLE_ON_A_DRAFT`, read by `draft_only_clears`. A
    draft is the person's own working copy and may be incomplete: a draft note may point at no invoice or bill (a create takes none), may
    carry no reason, and a draft invoice may carry no place of supply (the server refuses to ISSUE without one, and resolves one from the
    customer when none is stored). Each of those was emptied on the screen and then silently kept, and the first is the one that
    mattered: changing the customer of a draft credit note empties its "Against invoice" box, and the note went on pointing at the OLD
    customer's invoice. On an ISSUED document the same fields are frozen particulars, so a null or a blank for one there still reads
    "not sent", exactly as it always did, and the route's own rule for what an issued document may change is not reached by it.

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


def draft_only_clears(model: BaseModel) -> dict[str, None]:
    """The fields of the model's `CLEARABLE_ON_A_DRAFT` that the request SENT as null or as a blank string, each as `None`.

    The route takes these keys OUT of what `patch_dict` returned (a blank would otherwise travel on as "" to a uuid column) and puts them
    back as `None` only once it has read the stored row and found it a draft (`put_back_on_a_draft`). A field that was not sent is not in
    the answer.
    """
    names = frozenset(getattr(type(model), "CLEARABLE_ON_A_DRAFT", ()) or ())
    out: dict[str, None] = {}
    for name in sorted(names & model.model_fields_set):
        value = getattr(model, name, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            out[name] = None
    return out


def put_back_on_a_draft(data: dict[str, Any], draft_clears: dict[str, None], status: Any) -> None:
    """Write the names held aside as NULL when the stored document is a DRAFT, and leave `data` as it is for any other status.

    One function so that the question "is it a draft?" is asked the same way in every route and in both of a route's branches, and so
    that a route cannot apply the clears without asking it.
    """
    if status == "draft":
        data.update(draft_clears)


def without(data: dict[str, Any], names: Iterable[str]) -> dict[str, Any]:
    """`data` with `names` taken out: what a route writes before it knows whether the stored document is a draft."""
    gone = set(names)
    return {k: v for k, v in data.items() if k not in gone}


def removed_identifier_problem(model: BaseModel, stored: dict, labels: dict[str, str], *, why: str | None = None) -> str | None:
    """The sentence refusing an edit that EMPTIES an identifier the stored row carries, or None (POST-A-399, the party masters).

    A tax identifier a return reads off a party (its GSTIN and the state code that follows it, and a vendor's PAN and foreign tax number) is
    corrected and not removed by an edit: every GST return not yet filed reads the party's GSTIN and state code LIVE for the documents already
    issued to it (a recipient with a GSTIN is B2B, one without is B2C, and §16(2)(aa) sends the credit to whoever the GSTIN names), so emptying one
    would silently move documents already issued between tables of a return. A customer's PAN and TAN are not passed here, because no return reads
    them and the sentence would be untrue of them. `labels` maps each field the route refuses to empty to the words a person reads. A field the
    request SENT empty (null or blank) over a stored value is refused; one sent empty over nothing is not this function's to refuse (the route drops
    it, so nothing is written). `why` replaces the second sentence where the reader is not a return about documents issued to a party (an
    employee's PAN, UAN, ESI number and bank account, POST-A-399's third slice).
    """
    for name, label in labels.items():
        if name not in model.model_fields_set:
            continue
        value = getattr(model, name, None)
        if (value is None or (isinstance(value, str) and not value.strip())) and str(stored.get(name) or "").strip():
            return (f"The {label} on file can be corrected but not removed: enter the corrected {label}. "
                    + (why or "Every return not yet filed reads it for the documents already issued to this party."))
    return None


def drop_empty(payload: dict[str, Any], names: Iterable[str]) -> dict[str, Any]:
    """Remove each of `names` the payload carries as a blank string, so an empty box over nothing writes nothing (and never a stored "")."""
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and not value.strip():
            payload.pop(name, None)
    return payload
