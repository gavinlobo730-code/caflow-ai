"""A brought-forward loss is offered from the record and used by the return that is filed (POST-A-073, IT-10's other half).

Two moments, one rule (`domain/income_tax/loss_utilisation.py`, which reads nothing):

    COMPUTE. A loss the screen names by its record id is offered at what the record says THIS YEAR may use (the loss less the uses of OTHER
    years' returns), not at the figure the browser sent. The computation response names every loss it changed and says so in a sentence.
    A loss with no id is a figure the CA typed and is computed exactly as it always was.

    FILING. When a return's acknowledgement is recorded, the losses the pinned computation set off are written back to their records: the use
    is stored per filing and per financial year, and a revised return replaces the original's use for the same year. The write NEVER FAILS
    THE ACKNOWLEDGEMENT (the CA has said the return is filed): whatever it did not write comes back in the answer, loss by loss, with the
    reason.

WHAT IT DELIBERATELY DOES NOT DO
    * It does not trust the snapshot's amounts beyond the loss itself. The snapshot is what the CA's screen sent, so a loss id in it is
      checked against the filing's own client and firm, and the amount is capped at what the record could have offered.
    * It does not write for an UPDATED return (§139(8A)). How an updated return's set-off sits beside the return it updates, and whether a
      loss it uses is carried forward, has not been read from the Act, so nothing is assumed: the answer says no record was changed and the
      use is recorded by hand if it changed. A revised return (§139(5)) replaces the original for the year, which is what a revised return is.
    * It does not touch a loss the pinned computation does not list (one recorded after the computation was saved), nor a loss of another
      client.
    * It does not write twice for one filing: the same acknowledgement cannot be recorded twice, and the rule is idempotent regardless.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this records the use of a loss by a return the CA has already filed on the portal. It transmits
# nothing.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from core.authz import can_access_client
from domain.income_tax import computation_workspace as workspace
from domain.income_tax.loss_utilisation import after_filing, available_for_year_paise, entries_of
from domain.money_sentence import rupee_text

_logger = logging.getLogger("caflow.tax.bf_loss")

#: What `write_back_filing` answers. Its own word for each, because "nothing was written" has four different causes and a screen that
#: shows one sentence for all four hides the one the CA can act on.
WRITTEN = "written"
UNCHANGED = "unchanged"
NOT_WRITTEN = "not_written"
#: The return set off no brought-forward loss at all, so there is nothing to say; a screen shows no note for it.
NO_LOSSES = "no_losses"

#: What the engine's `BroughtForwardLoss` takes from a typed-in loss besides `loss_id`.
_ENGINE_KEYS = ("loss_type", "amount_paise", "assessment_year", "expiry_assessment_year", "is_expired", "source_itr_ack")

#: The return kinds a write-back acts on. `updated` is absent on purpose (see the module docstring).
_KINDS_WRITTEN_BACK = frozenset({"original", "revised"})


class LossNotFound(Exception):
    """A loss id the caller may not use: absent, another firm's, or a client outside the caller's assignment. One sentence for all three,
    so the answer does not say which clients exist."""


class DuplicateLoss(Exception):
    """The same loss record named twice in one computation, which would offer it twice."""


def _words(loss_type: Any) -> str:
    return str(loss_type or "").replace("_", " ").strip() or "brought-forward"


def resolve_for_compute(current_user: Mapping[str, Any], losses: list[dict], financial_year: str) -> tuple[list[dict], list[dict]]:
    """(the losses to compute with, a note for each one whose figure the record changed).

    Each item is a dict with the keys of `BroughtForwardLossInput` and an optional `id`. An item with an id is read from its record: the type,
    assessment year, expiry and acknowledgement are the RECORD's (an id means the stored row, so a screen cannot attach one loss's use to
    another's head), and the amount is `available_for_year_paise`. An item without an id is returned untouched.
    """
    out: list[dict] = []
    notes: list[dict] = []
    seen: set[str] = set()
    for item in losses:
        loss_id = str(item.get("id") or "").strip()
        if not loss_id:
            out.append({k: item.get(k) for k in _ENGINE_KEYS} | {"loss_id": None, "is_expired": bool(item.get("is_expired"))})
            continue
        if loss_id in seen:
            raise DuplicateLoss("The same loss record was sent twice, which would offer it twice. Send each recorded loss once.")
        seen.add(loss_id)
        row = workspace.get_bf_loss(current_user["firm_id"], loss_id)
        if not row or not can_access_client(current_user, row.get("client_id")):
            raise LossNotFound("Loss record not found")
        offered = available_for_year_paise(row, financial_year)
        sent = int(item.get("amount_paise") or 0)
        out.append({
            "loss_type": row.get("loss_type") or item.get("loss_type"),
            "amount_paise": offered,
            "assessment_year": row.get("assessment_year") or item.get("assessment_year"),
            "expiry_assessment_year": row.get("expiry_assessment_year"),
            "is_expired": bool(item.get("is_expired")),
            "source_itr_ack": row.get("source_itr_ack"),
            "loss_id": loss_id,
        })
        if offered != sent:
            notes.append({
                "loss_id": loss_id,
                "sent_paise": sent,
                "offered_paise": offered,
                "note": (f"The {_words(row.get('loss_type'))} loss of AY {row.get('assessment_year') or 'unknown'} is offered at "
                         f"{rupee_text(offered)}: the loss on record, less what the record shows as already used (by returns for other "
                         f"years, or recorded by hand). The figure the screen sent, {rupee_text(sent)}, was not used."),
            })
    return out, notes


def _lines_of(computation: Any) -> Optional[list[dict]]:
    """The set-off lines of a saved computation, or None when it holds none in the shape this reads."""
    if not isinstance(computation, Mapping):
        return None
    brought = computation.get("brought_forward")
    if not isinstance(brought, Mapping):
        return None
    lines = brought.get("lines")
    return [ln for ln in lines if isinstance(ln, Mapping)] if isinstance(lines, list) else None


def _answer(state: str, message: str, losses: Optional[list[dict]] = None) -> dict:
    return {"state": state, "message": message, "losses": losses or []}


def write_back_filing(current_user: Mapping[str, Any], filing: Mapping[str, Any]) -> dict:
    """Record what the filed return used of each brought-forward loss, and say what was and was not recorded. Never raises."""
    from core.observability import capture_soft_failure
    try:
        return _write_back(current_user, filing)
    except Exception as exc:                                          # noqa: BLE001
        capture_soft_failure(exc, operation="bf_loss_service.write_back_filing",
                             firm_id=current_user.get("firm_id"), client_id=filing.get("client_id"))
        return _answer(NOT_WRITTEN, "The acknowledgement is recorded, but the brought-forward loss records could not be updated just now. "
                                    "Record what this return used of each loss by hand.")


def _refusal_before_reading(filing: Mapping[str, Any]) -> Optional[dict]:
    """The answer for a filing that cannot be written back at all, or None when it can be tried."""
    kind = str(filing.get("return_type") or "original").strip().lower() or "original"
    if kind not in _KINDS_WRITTEN_BACK:
        return _answer(NOT_WRITTEN, f"This is a {kind} return. How a {kind} return's set-off sits beside the return it updates has not "
                                    "been confirmed from the Act, so no brought-forward loss record was changed. If the use of a loss "
                                    "changed, record it by hand.")
    if not (filing.get("id") and filing.get("client_id") and str(filing.get("financial_year") or "").strip()):
        return _answer(NOT_WRITTEN, "The filing does not say which client and year it is for, so no loss record was changed.")
    if not filing.get("computation_snapshot_id"):
        return _answer(NOT_WRITTEN, "This return pins no saved computation, so there is no record of which losses it used. "
                                    "No loss record was changed.")
    return None


def _snapshot_lines(firm_id: str, filing: Mapping[str, Any]) -> tuple[Optional[list[dict]], Optional[dict]]:
    """(the pinned computation's set-off lines, None) or (None, the answer for a computation that cannot be trusted for this return)."""
    snapshot = workspace.get_snapshot(firm_id, str(filing.get("computation_snapshot_id")))
    if not snapshot or str(snapshot.get("client_id") or "") != str(filing.get("client_id")):
        return None, _answer(NOT_WRITTEN, "The saved computation this return pins could not be read for this client, so no loss record "
                                          "was changed.")
    financial_year = str(filing.get("financial_year") or "").strip()
    if str(snapshot.get("financial_year") or "").strip() != financial_year:
        return None, _answer(NOT_WRITTEN, f"The saved computation is for FY {snapshot.get('financial_year')} and the return is for FY "
                                          f"{financial_year}, so no loss record was changed.")
    return _lines_of(snapshot.get("computation_json")) or [], None


def _uses_in(lines: list[dict]) -> tuple[dict[str, int], int, int]:
    """(paise set off per loss record id, how many lines named no record, how much those set off)."""
    used_by_loss: dict[str, int] = {}
    typed_in = typed_in_used = 0
    for ln in lines:
        loss_id = str(ln.get("loss_id") or "").strip()
        used = max(0, int(ln.get("set_off_paise") or 0))
        if loss_id:
            used_by_loss[loss_id] = used_by_loss.get(loss_id, 0) + used
        else:
            typed_in += 1
            typed_in_used += used
    return used_by_loss, typed_in, typed_in_used


def _refused_write(firm_id: str, loss_id: str, before: Mapping[str, Any]) -> str:
    """Why a write that matched no row was refused, told apart by reading the record again: its totals moved (a hand edit or another
    write landed first), or they did not (the row is not writable by this caller, which row security answers with no row and no error)."""
    now = workspace.get_bf_loss(firm_id, loss_id) or {}
    if (now.get("utilized_amount_paise"), now.get("remaining_amount_paise")) != (
            before.get("utilized_amount_paise"), before.get("remaining_amount_paise")):
        return ("The loss record changed while this was being written, so it was left as it was. "
                "Record what this return used of it by hand.")
    return ("This loss record could not be written with your access, so it was left as it was. "
            "Record what this return used of it by hand.")


def _write_one(firm_id: str, client_id: str, filing_id: str, financial_year: str, loss_id: str, used: int) -> dict:
    row = workspace.get_bf_loss(firm_id, loss_id)
    if not row or str(row.get("client_id") or "") != client_id:
        return {"loss_id": loss_id, "state": NOT_WRITTEN, "used_paise": used,
                "message": "A loss in the saved computation is not one of this client's records, so it was left alone."}
    row = dict(row)       # what was READ: the in-memory store hands back its live row, and a later write must be compared to this
    columns = after_filing(row, filing_id, financial_year, used)
    label = {"loss_id": loss_id, "assessment_year": row.get("assessment_year"), "loss_type": row.get("loss_type"),
             "used_paise": columns["utilisations"].get(filing_id, {}).get("amount_paise", 0)}
    if (columns["utilisations"] == entries_of(row)
            and columns["utilized_amount_paise"] == int(row.get("utilized_amount_paise") or 0)
            and columns["remaining_amount_paise"] == int(row.get("remaining_amount_paise") or 0)):
        return {**label, "state": UNCHANGED}
    if workspace.store_bf_loss_use(firm_id, loss_id, row, columns):
        return {**label, "state": WRITTEN}
    return {**label, "state": NOT_WRITTEN, "message": _refused_write(firm_id, loss_id, row)}


def _summary(results: list[dict], typed_in: int) -> str:
    wrote = sum(1 for r in results if r["state"] == WRITTEN)
    refused = sum(1 for r in results if r["state"] == NOT_WRITTEN)
    parts = []
    if wrote:
        parts.append(f"{wrote} brought-forward loss record(s) now show what this return used.")
    if not wrote and not refused:
        parts.append("The loss records already showed what this return used.")
    if refused:
        parts.append(f"{refused} loss record(s) could not be updated; see each.")
    if typed_in:
        parts.append(f"{typed_in} loss(es) in the computation were typed in rather than taken from a record, and were not written.")
    return " ".join(parts)


def _write_back(current_user: Mapping[str, Any], filing: Mapping[str, Any]) -> dict:
    firm_id = current_user["firm_id"]
    refusal = _refusal_before_reading(filing)
    if refusal:
        return refusal
    lines, refusal = _snapshot_lines(firm_id, filing)
    if refusal:
        return refusal
    used_by_loss, typed_in, typed_in_used = _uses_in(lines or [])
    if not used_by_loss:
        if not typed_in_used:
            return _answer(NO_LOSSES, "The saved computation set off no brought-forward loss, so no loss record was changed.")
        return _answer(NOT_WRITTEN, "The saved computation set off a loss that names no loss record (it was made before losses were "
                                    "tied to their records, or the loss was typed in), so no loss record was changed. "
                                    "Record the use of the loss by hand.")
    results = [_write_one(firm_id, str(filing["client_id"]), str(filing["id"]), str(filing["financial_year"]).strip(), loss_id, used)
               for loss_id, used in used_by_loss.items()]
    wrote = any(r["state"] == WRITTEN for r in results)
    refused = any(r["state"] == NOT_WRITTEN for r in results)
    return _answer(WRITTEN if wrote else (NOT_WRITTEN if refused else UNCHANGED), _summary(results, typed_in), results)
