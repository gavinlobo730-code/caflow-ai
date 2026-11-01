"""A brought-forward loss is offered from the record and used by the return that is filed (POST-A-073, IT-10's other half).

Two moments, one rule (`domain/income_tax/loss_utilisation.py`, which reads nothing):

    COMPUTE. A loss the screen names by its record id is offered at what the record says THIS year may use (the loss less the uses of OTHER
    years' returns), not at the figure the browser sent, and only for the client being computed. The computation response names every loss it
    changed and says why in a sentence. A loss with no id is a figure the CA typed and is computed exactly as it always was.

    FILING. When a return's acknowledgement is recorded, the losses the pinned computation set off are written back to their records: the use
    is stored per filing and per financial year, and a revised return replaces the original's use for the same year. The write NEVER FAILS
    THE ACKNOWLEDGEMENT (the CA has said the return is filed) and each loss is written, or refused, on its own: whatever was not written comes
    back in the answer, loss by loss, with the reason.

WHAT IT DELIBERATELY DOES NOT DO
    * It does not trust the snapshot's amounts beyond the loss itself. The snapshot is what the CA's screen sent, so the ids in it are looked up
      among THIS CLIENT'S records only (a forged id for another client's loss spends nothing), the amount is capped at what the record could
      still take, and a cap is said aloud: a return that used more than its record could take means two returns together used more than the loss.
    * It does not write for an UPDATED return (§139(8A)). How an updated return's set-off sits beside the return it updates, and whether a
      loss it uses is carried forward, has not been read from the Act, so nothing is assumed: the answer says no record was changed.
    * It does not write when the caller may approve a return but not change loss records (the table's own write policy asks for the compute
      tier), and says so, rather than leaving row security to answer with no row and no error.
    * A revised return (§139(5)) replaces the original's use for the year, graded [S] (it is how `return_type.py` already treats it: it
      re-declares a year already declared) and put to the owner as S21. An original acknowledged AFTER the revised return that replaced it does
      not write over it.
    * It does not touch a loss the pinned computation does not list, except to clear the use an earlier return of the SAME year had recorded
      when this one (a revised return) used none of it.
    * It writes only for a filing created from a saved computation. A filing that was not can have its saved computation pinned afterwards and
      its loss records written again; and a person can record a year's use BY HAND, or take an entry back, on the Tax Computation screen
      (`record_year_use`, `take_back_use`; POST-A-368). A hand entry ranks below a return's, so the return's write replaces it.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this records the use of a loss by a return the CA has already filed on the portal. It transmits
# nothing.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from core.authz import can_access_client
from core.permissions import can_user
from domain.income_tax import computation_workspace as workspace
from domain.income_tax.loss_utilisation import (
    MANUAL, HeldByReturn, MoreThanTheRecordCanTake, NoSuchEntry, Superseded, after_filing, available_for_year_paise,
    entries_of, holds_entry_for, is_earlier_year, later_uses, record_by_hand, take_back, used_in_year_paise,
    uses_view,
)
from domain.money_sentence import rupee_text

_logger = logging.getLogger("caflow.tax.bf_loss")

#: What `write_back_filing` answers. Its own word for each, because "nothing was written" has several causes and a screen that shows one
#: sentence for all of them hides the one the CA can act on.
WRITTEN = "written"
UNCHANGED = "unchanged"
NOT_WRITTEN = "not_written"
#: The client has no loss on record, or the return set off none: there is nothing to say, and a screen shows no note.
NO_LOSSES = "no_losses"

#: What the engine's `BroughtForwardLoss` takes from a typed-in loss besides `loss_id`.
_ENGINE_KEYS = ("loss_type", "amount_paise", "assessment_year", "expiry_assessment_year", "is_expired", "source_itr_ack")

#: The return kinds a write-back acts on. `updated` is absent on purpose (see the module docstring).
_KINDS_WRITTEN_BACK = frozenset({"original", "revised"})

#: Said wherever the answer is "this was not recorded": where a person can put a record right. It ADVISES nothing: for an updated return (section
#: 139(8A)) how its set-off sits beside the return it updates has not been read from the Act, so no sentence about it tells anyone to record a use.
_WHERE_TO_CORRECT = "A loss record can be corrected on the Tax Computation screen, under the loss."


class LossNotFound(Exception):
    """A loss id the caller may not use for this client: absent, another firm's, another client's, or a client outside the caller's
    assignment. One sentence for all of them, so the answer does not say which clients exist."""


class DuplicateLoss(Exception):
    """The same loss record named twice in one computation, which would offer it twice."""


class ClientNotNamed(Exception):
    """A loss named by record id in a computation that names no client."""


def _words(loss_type: Any) -> str:
    return str(loss_type or "").replace("_", " ").strip() or "brought-forward"


def _name(row: Mapping[str, Any]) -> str:
    return f"{_words(row.get('loss_type'))} loss of AY {row.get('assessment_year') or 'unknown'}"


def _offer_note(row: Mapping[str, Any], offered: int, sent: int, financial_year: str) -> str:
    """Why the figure offered is not the figure the screen held, in the order a CA would ask: what the record holds, what it shows as used
    elsewhere, and what this very year's own earlier return used (offered back because that year is being computed again)."""
    original = int(row.get("original_amount_paise") or 0)
    same_year = used_in_year_paise(row, financial_year)
    text = (f"The {_name(row)} is offered at {rupee_text(offered)} for FY {financial_year}: the record holds {rupee_text(original)} and "
            f"shows {rupee_text(max(0, original - offered))} as already used by returns for other years or recorded by hand")
    if same_year:
        own_by_hand = any(e["return_type"] == MANUAL and e["financial_year"] == financial_year.strip() for e in entries_of(row).values())
        what = "recorded by hand for" if own_by_hand else "used by the return for"
        text += (f", and the {rupee_text(same_year)} {what} FY {financial_year} itself is offered back because that "
                 "year is being computed again")
    return f"{text}. The figure on the screen, {rupee_text(sent)}, was not used."


def _later_years_sentence(row: Mapping[str, Any], financial_year: str) -> Optional[str]:
    """Says which later years' returns have taken part of this loss, or None when none has (POST-A-367). The figure offered leaves their use
    out; the sentence names it, because using more of the loss for this year may mean that later return has to be revised. The record takes
    no view on which year should have had the loss first."""
    later = later_uses(row, financial_year)
    if not later:
        return None
    parts = ", ".join(f"FY {item['financial_year']}: {rupee_text(item['amount_paise'])}" for item in later)
    by_hand = [i["return_type"] == MANUAL for i in later]
    if all(by_hand):
        who, revise = "The uses recorded by hand for later years", "what was recorded for those years"
    elif any(by_hand):
        who, revise = "The returns for later years, and the uses recorded by hand for some of them,", "that later return, or what was recorded for it,"
    else:
        who, revise = "The returns for later years", "that later return"
    return (f"{who} have already used part of this loss ({parts}), and that use is left out of the figure offered. "
            f"Using more of it for this year may mean {revise} has to be revised; the record shows the arithmetic and takes no "
            "view on which year should have had it.")


def _unrecorded_returns(current_user: Mapping[str, Any], client_id: str, financial_year: str,
                        rows: Mapping[str, Mapping[str, Any]]) -> dict[str, list[dict]]:
    """For each loss record id in `rows`, the earlier-year returns recorded as filed whose saved computation set off part of that loss and
    which the record does not show (POST-A-367). A return acknowledged before the write-back existed, or one whose write was refused, leaves
    exactly this: next year's computation is then offered the whole loss again. Only a computation that names the loss by its record id can
    be told here; one that does not (saved before the ids) is not guessed at.

    Reading is advisory: a failure to read returns nothing and is reported, never raised into the computation.
    """
    from core.observability import capture_soft_failure
    from domain.income_tax import itr_workflow
    found: dict[str, list[dict]] = {}
    try:
        for filing in itr_workflow.list_itr_filings(current_user["firm_id"], client_id):
            fy = str(filing.get("financial_year") or "").strip()
            kind = str(filing.get("return_type") or "original").strip().lower() or "original"
            if (filing.get("status") != "filed" or kind not in _KINDS_WRITTEN_BACK or not filing.get("computation_snapshot_id")
                    or not is_earlier_year(fy, financial_year)):
                continue
            snapshot = workspace.get_snapshot(current_user["firm_id"], str(filing.get("computation_snapshot_id")))
            if (not snapshot or str(snapshot.get("client_id") or "") != str(client_id)
                    or str(snapshot.get("financial_year") or "").strip() != fy):
                continue
            for line in _lines_of(snapshot.get("computation_json")) or []:
                loss_id = str(line.get("loss_id") or "")
                row = rows.get(loss_id)
                set_off = int(line.get("set_off_paise") or 0)
                if row is None or set_off <= 0 or holds_entry_for(row, str(filing.get("id")), fy, kind):
                    continue
                by_hand = sum(e["amount_paise"] for e in entries_of(row).values() if e["return_type"] == MANUAL and e["financial_year"] == fy)
                found.setdefault(loss_id, []).append({
                    "filing_id": str(filing.get("id")), "financial_year": fy, "set_off_paise": set_off,
                    "acknowledgement_number": filing.get("acknowledgement_number"),
                    **({"recorded_by_hand_paise": by_hand} if by_hand else {}),
                })
    except Exception as exc:                                          # noqa: BLE001
        capture_soft_failure(exc, operation="bf_loss_service._unrecorded_returns",
                             firm_id=current_user.get("firm_id"), client_id=client_id)
        return {}
    return found


def uses_by_loss(current_user: Mapping[str, Any], client_id: str, rows: list[dict]) -> dict[str, dict]:
    """For each of the client's loss records, where it went: `loss_utilisation.uses_view` over the record and the client's filings, so the
    list of losses can say which return holds which part (POST-A-368). Reads only. A failure to read the filings is reported and leaves the
    items without an acknowledgement number and without a verdict on whether the return is still on file; it never fails the list."""
    from core.observability import capture_soft_failure
    from domain.income_tax import itr_workflow
    filings: Optional[dict[str, dict]]
    try:
        filings = {str(f.get("id")): f for f in itr_workflow.list_itr_filings(current_user["firm_id"], client_id)}
    except Exception as exc:                                          # noqa: BLE001
        capture_soft_failure(exc, operation="bf_loss_service.uses_by_loss", firm_id=current_user.get("firm_id"), client_id=client_id)
        filings = None
    return {str(r.get("id")): uses_view(r, filings) for r in rows}


def _unrecorded_sentence(items: list[dict]) -> str:
    parts = "; ".join(
        f"FY {item['financial_year']}"
        + (f" (acknowledgement {item['acknowledgement_number']})" if item.get("acknowledgement_number") else "")
        + f", {rupee_text(item['set_off_paise'])}"
        for item in items)
    held = [i for i in items if i.get("recorded_by_hand_paise")]
    if held:
        by_hand = "; ".join(f"FY {i['financial_year']}: {rupee_text(i['recorded_by_hand_paise'])}" for i in held)
        return (f"A return recorded as filed set off part of this loss, but the loss record shows what was recorded by hand for that year "
                f"instead of what the return used: {parts}. Recorded by hand: {by_hand}. Until the record is updated from that return "
                "(Tax Filing, Brought-forward losses), which replaces the hand entry, the figure offered counts the hand figure as used.")
    return (f"A return recorded as filed set off part of this loss, but the loss record does not show it: {parts}. Until the record is updated "
            "from that return (Tax Filing, Brought-forward losses), the figure offered counts that part as unused.")


def resolve_for_compute(current_user: Mapping[str, Any], losses: list[dict], financial_year: str,
                        client_id: Optional[str] = None) -> tuple[list[dict], list[dict]]:
    """(the losses to compute with, a note for each one whose figure the record changed).

    Each item is a dict with the keys of `BroughtForwardLossInput` and an optional `id`. An item with an id is read from its record, which
    must be THIS client's: the type, assessment year, expiry, acknowledgement and expired flag are the RECORD's (an id means the stored row,
    so a request cannot attach one loss's use to another's head), and the amount is `available_for_year_paise`. A loss with nothing to offer
    that the screen also held at nothing has nothing to say and is left out. An item without an id is returned untouched.
    """
    out: list[dict] = []
    notes: list[dict] = []
    seen: set[str] = set()
    rows: dict[str, Mapping[str, Any]] = {}
    offered_by_id: dict[str, tuple[int, int]] = {}
    for item in losses:
        loss_id = str(item.get("id") or "").strip()
        if not loss_id:
            out.append({k: item.get(k) for k in _ENGINE_KEYS} | {"loss_id": None, "is_expired": bool(item.get("is_expired"))})
            continue
        if not client_id:
            raise ClientNotNamed("A loss named by its record needs the client it belongs to. Send the client with the computation.")
        if loss_id in seen:
            raise DuplicateLoss("The same loss record was sent twice, which would offer it twice. Send each recorded loss once.")
        seen.add(loss_id)
        row = workspace.get_bf_loss(current_user["firm_id"], loss_id)
        if (not row or str(row.get("client_id")) != str(client_id) or not can_access_client(current_user, row.get("client_id"))):
            raise LossNotFound("Loss record not found")
        offered = available_for_year_paise(row, financial_year)
        sent = int(item.get("amount_paise") or 0)
        if offered == 0 and sent == 0:
            continue
        rows[loss_id] = row
        offered_by_id[loss_id] = (sent, offered)
        out.append({
            "loss_type": row.get("loss_type") or item.get("loss_type"),
            "amount_paise": offered,
            "assessment_year": row.get("assessment_year") or item.get("assessment_year"),
            "expiry_assessment_year": row.get("expiry_assessment_year"),
            "is_expired": bool(row.get("is_expired") or item.get("is_expired")),
            "source_itr_ack": row.get("source_itr_ack"),
            "loss_id": loss_id,
        })
        if offered != sent:
            notes.append({"loss_id": loss_id, "sent_paise": sent, "offered_paise": offered,
                          "note": _offer_note(row, offered, sent, financial_year)})
    return out, _with_what_the_record_says_about_other_years(current_user, notes, rows, offered_by_id, financial_year, client_id)


def _with_what_the_record_says_about_other_years(current_user: Mapping[str, Any], notes: list[dict], rows: Mapping[str, Mapping[str, Any]],
                                                 offered_by_id: Mapping[str, tuple[int, int]], financial_year: str,
                                                 client_id: Optional[str]) -> list[dict]:
    """The notes with two more facts added to each loss they apply to (POST-A-367): a later year's return has taken part of the loss, and an
    earlier return recorded as filed is missing from the record. One note per loss, so the screen's list stays one line per loss."""
    if not rows or not client_id:
        return notes
    unrecorded = _unrecorded_returns(current_user, str(client_id), financial_year, rows)
    by_id = {n["loss_id"]: n for n in notes}
    for loss_id, row in rows.items():
        extra = [text for text in (_later_years_sentence(row, financial_year),
                                   _unrecorded_sentence(unrecorded[loss_id]) if loss_id in unrecorded else None) if text]
        if not extra:
            continue
        if loss_id in by_id:
            by_id[loss_id]["note"] = " ".join([by_id[loss_id]["note"], *extra])
        else:
            sent, offered = offered_by_id[loss_id]
            notes.append({"loss_id": loss_id, "sent_paise": sent, "offered_paise": offered, "note": " ".join(extra)})
            by_id[loss_id] = notes[-1]
        if loss_id in unrecorded:
            by_id[loss_id]["unrecorded_returns"] = unrecorded[loss_id]
        if later_uses(row, financial_year):
            by_id[loss_id]["later_years"] = later_uses(row, financial_year)
    return notes


def _lines_of(computation: Any) -> Optional[list[dict]]:
    """The set-off lines of a saved computation, or None when it holds none in the shape this reads (which is not the same as holding none)."""
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
        return _answer(NOT_WRITTEN, "The acknowledgement is recorded, but the brought-forward loss records could not be updated just now, "
                                    "and some may have been. Check each loss on the Tax Computation screen.")


def _refusal_before_reading(filing: Mapping[str, Any]) -> Optional[dict]:
    """The answer for a filing that cannot be written back at all, or None when it can be tried."""
    kind = str(filing.get("return_type") or "original").strip().lower() or "original"
    if kind not in _KINDS_WRITTEN_BACK:
        return _answer(NOT_WRITTEN, "This is an updated return. How an updated return's set-off sits beside the return it updates has not "
                                    f"been confirmed from the Act, so no brought-forward loss record was changed. {_WHERE_TO_CORRECT}")
    if not (filing.get("id") and filing.get("client_id") and str(filing.get("financial_year") or "").strip()):
        return _answer(NOT_WRITTEN, "The filing does not say which client and year it is for, so no loss record was changed.")
    if not filing.get("computation_snapshot_id"):
        return _answer(NOT_WRITTEN, "This return was not created from a saved computation, so nothing says which losses it used and no loss "
                                    "record was changed. Choose the saved computation on the return, then update the loss records from it.")
    return None


def _snapshot_lines(firm_id: str, filing: Mapping[str, Any]) -> tuple[Optional[list[dict]], Optional[dict]]:
    """(the pinned computation's set-off lines, None) or (None, the answer for a computation that cannot be trusted for this return)."""
    snapshot = workspace.get_snapshot(firm_id, str(filing.get("computation_snapshot_id")))
    if not snapshot or str(snapshot.get("client_id") or "") != str(filing.get("client_id")):
        return None, _answer(NOT_WRITTEN, "The saved computation this return is built on could not be read for this client, so no loss "
                                          "record was changed.")
    financial_year = str(filing.get("financial_year") or "").strip()
    if str(snapshot.get("financial_year") or "").strip() != financial_year:
        return None, _answer(NOT_WRITTEN, f"The saved computation is for FY {snapshot.get('financial_year')} and the return is for FY "
                                          f"{financial_year}, so no loss record was changed.")
    lines = _lines_of(snapshot.get("computation_json"))
    if lines is None:
        return None, _answer(NOT_WRITTEN, "The saved computation does not list its brought-forward losses in a form this can read, so no "
                                          f"loss record was changed. {_WHERE_TO_CORRECT}")
    return lines, None


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


def _already_what_it_should_be(row: Mapping[str, Any], columns: Mapping[str, Any]) -> bool:
    return (columns["utilisations"] == entries_of(row)
            and columns["utilized_amount_paise"] == int(row.get("utilized_amount_paise") or 0)
            and columns["remaining_amount_paise"] == int(row.get("remaining_amount_paise") or 0))


def _after_a_refused_write(firm_id: str, loss_id: str, before: Mapping[str, Any], filing: Mapping[str, Any], used: int) -> tuple[str, str]:
    """(state, sentence) for a write that matched no row, told apart by reading the record again: it now holds exactly what this write would
    have stored (a second submit of the same acknowledgement got there first), its totals moved (a hand edit or another write landed first),
    or they did not (the row is not writable by this caller, which row security answers with no row and no error)."""
    now = workspace.get_bf_loss(firm_id, loss_id) or {}
    would_store: Optional[dict] = None
    try:
        would_store = after_filing(now, str(filing["id"]), str(filing["financial_year"]).strip(), used,
                                   str(filing.get("return_type") or "original"))
    except Superseded:
        would_store = None          # a revised return holds the year: this write could not have been stored, so it is not "already right"
    if would_store is not None and _already_what_it_should_be(now, would_store):
        return UNCHANGED, ""
    if (now.get("utilized_amount_paise"), now.get("remaining_amount_paise")) != (
            before.get("utilized_amount_paise"), before.get("remaining_amount_paise")):
        return NOT_WRITTEN, "the loss record changed while this was being written, so it was left as it was."
    return NOT_WRITTEN, "this loss record could not be written with your access, so it was left as it was."


def _write_one(firm_id: str, filing: Mapping[str, Any], row: Mapping[str, Any], used: int) -> dict:
    row = dict(row)       # what was READ: the in-memory store hands back its live row, and a later write must be compared to this
    loss_id = str(row["id"])
    label = {"loss_id": loss_id, "name": _name(row), "requested_paise": used}
    try:
        columns = after_filing(row, str(filing["id"]), str(filing["financial_year"]).strip(), used,
                               str(filing.get("return_type") or "original"))
    except Superseded:
        return {**label, "state": NOT_WRITTEN, "used_paise": 0,
                "message": f"a revised return for FY {str(filing['financial_year']).strip()} already holds this year's use of the loss, "
                           "so this return's use was not recorded over it."}
    recorded = columns["utilisations"].get(str(filing["id"]), {}).get("amount_paise", 0)
    label["used_paise"] = recorded
    capped = (f"this return set off {rupee_text(used)} but the record could still take only {rupee_text(recorded)} (other years' returns "
              f"and recorded uses had taken the rest), so {rupee_text(recorded)} is recorded. The returns together have used more of "
              "this loss than there was.") if recorded < used else ""
    # A use a person recorded by hand for this year stands in for the return until the return writes its own: say that it was replaced, and by
    # how much, so a figure typed by a person never changes without a word.
    fy = str(filing["financial_year"]).strip()
    by_hand = sum(e["amount_paise"] for e in entries_of(row).values() if e["return_type"] == MANUAL and e["financial_year"] == fy)
    if by_hand:
        label["replaced_by_hand_paise"] = by_hand
        capped = (f"the {rupee_text(by_hand)} recorded by hand for FY {fy} was replaced by what this return used"
                  + (f"; {capped}" if capped else ""))
    if _already_what_it_should_be(row, columns):
        return {**label, "state": UNCHANGED, **({"message": capped} if capped else {})}
    if workspace.store_bf_loss_use(firm_id, loss_id, row, columns):
        return {**label, "state": WRITTEN, **({"message": capped} if capped else {})}
    state, sentence = _after_a_refused_write(firm_id, loss_id, row, filing, used)
    return {**label, "state": state, **({"message": sentence} if sentence else {})}


def _write_one_on_its_own(firm_id: str, filing: Mapping[str, Any], row: Mapping[str, Any], used: int) -> dict:
    """One loss is written, or refused, without the others: a failure on the second must not discard the first's answer, because the first
    is already stored and an answer that said nothing was written would send the CA to record it again."""
    from core.observability import capture_soft_failure
    try:
        return _write_one(firm_id, filing, row, used)
    except Exception as exc:                                          # noqa: BLE001
        capture_soft_failure(exc, operation="bf_loss_service.write_one", firm_id=firm_id, client_id=filing.get("client_id"))
        return {"loss_id": str(row.get("id")), "name": _name(row), "requested_paise": used, "used_paise": 0, "state": NOT_WRITTEN,
                "message": "this loss record could not be updated just now, and may or may not have been; check it on the Tax "
                           "Computation screen before relying on it."}


def _targets(records: Mapping[str, Mapping[str, Any]], used_by_loss: Mapping[str, int], filing: Mapping[str, Any]) -> dict[str, int]:
    """The client's records this write touches and what each is to hold: those the computation names, and any other that an earlier return
    of the SAME year had recorded a use on (this return stands in its place and used none of it).

    A use recorded BY HAND is not cleared that way: it is replaced only where the return's own computation names the loss and says what it used
    of it. A computation that set off a loss it does not name by record (a typed-in figure) cannot say that this loss was untouched, so what a
    person recorded by hand for the year stays (found in review: the write-back used to erase it and report a success)."""
    financial_year = str(filing["financial_year"]).strip()
    targets = {loss_id: used for loss_id, used in used_by_loss.items() if loss_id in records}
    for loss_id, row in records.items():
        if loss_id not in targets and any(e["financial_year"] == financial_year and other != str(filing["id"]) and e["return_type"] != MANUAL
                                         for other, e in entries_of(row).items()):
            targets[loss_id] = 0
    return targets


def _summary(results: list[dict], unknown: int, typed_in: int, typed_in_used: int) -> str:
    wrote = sum(1 for r in results if r["state"] == WRITTEN)
    parts = []
    if wrote:
        parts.append(f"{wrote} brought-forward loss record(s) now show what this return used.")
    elif not any(r.get("message") for r in results) and not unknown and not typed_in_used:
        parts.append("The loss records already showed what this return used.")
    parts.extend(f"The {r['name']}: {r['message']}" for r in results if r.get("message"))
    if unknown:
        parts.append(f"{unknown} loss(es) named in the computation are not records of this client and were left alone.")
    if typed_in_used:
        parts.append(f"{typed_in} loss(es) in the computation were typed in rather than taken from a record, so what they set off was not "
                     "written.")
    return " ".join(parts)


def _write_back(current_user: Mapping[str, Any], filing: Mapping[str, Any]) -> dict:
    firm_id = current_user["firm_id"]
    client_id = str(filing.get("client_id") or "")
    # THE CLIENT'S OWN RECORDS, read once: a client with none has nothing to say, and every id in the saved computation is looked up here,
    # so an id that is not this client's (forged, stale or malformed) is one cheap miss and not a read of its own.
    records = {str(r["id"]): r for r in workspace.list_bf_losses(firm_id, client_id)} if client_id else {}
    if not records:
        return _answer(NO_LOSSES, "This client has no brought-forward loss on record.")
    refusal = _refusal_before_reading(filing)
    if refusal:
        return refusal
    lines, refusal = _snapshot_lines(firm_id, filing)
    if refusal:
        return refusal
    used_by_loss, typed_in, typed_in_used = _uses_in(lines or [])
    unknown = sum(1 for loss_id, used in used_by_loss.items() if loss_id not in records and used > 0)
    targets = _targets(records, used_by_loss, filing)
    if not targets and not unknown:
        if typed_in_used:
            return _answer(NOT_WRITTEN, "The saved computation set off a loss that names no loss record (it was made before losses were "
                                        f"tied to their records, or the loss was typed in), so no loss record was changed. {_WHERE_TO_CORRECT}")
        return _answer(NO_LOSSES, "The saved computation set off no brought-forward loss, so no loss record was changed.")
    if targets and not can_user(dict(current_user), "income_tax", "compute"):
        return _answer(NOT_WRITTEN, "You can approve a return but not change loss records, so no loss record was changed.")
    results = [_write_one_on_its_own(firm_id, filing, records[loss_id], used) for loss_id, used in targets.items()]
    problems = unknown or typed_in_used or any(r["state"] == NOT_WRITTEN for r in results)
    wrote = any(r["state"] == WRITTEN for r in results)
    return _answer(WRITTEN if wrote else (NOT_WRITTEN if problems else UNCHANGED), _summary(results, unknown, typed_in, typed_in_used),
                   results)


# ── A person corrects a loss record by hand (POST-A-368, items 2 and 3) ─────────────────────────────────────────────────────────────────

MAX_REASON_CHARS = 500


class UseRefused(Exception):
    """A hand correction that must not go ahead, with the sentence to show. `status` is the HTTP status the route answers."""

    def __init__(self, sentence: str, status: int = 422):
        super().__init__(sentence)
        self.sentence = sentence
        self.status = status


def clean_reason(reason: Optional[str]) -> str:
    """The reason as it will be kept, or a refusal in words. Every hand correction carries one: it is the only account of why a record that a
    filed return wrote, or one a person typed, was changed."""
    why = (reason or "").strip()
    if not why:
        raise UseRefused("Say why the loss record is being changed. The reason is kept with the change in the audit log.")
    if len(why) > MAX_REASON_CHARS:
        raise UseRefused(f"The reason is too long: keep it to {MAX_REASON_CHARS} characters.")
    return why


def _write_audit_or_refuse(*, firm_id: str, row: Mapping[str, Any], change: str, requested: Mapping[str, Any], reason: str,
                           actor: Mapping[str, Any]) -> None:
    """Keep what the record held, what was asked and the reason in the audit log, or refuse. Not `audit_service.log_event`, which swallows its
    failures: this entry is the only account of why the record changed, and a change with no account behind it is the thing the audit log is
    for. The entry says what was ASKED; a write that then finds the record changed under it is refused afterwards and the entry stays, a true
    account of the request."""
    from core.supabase_client import get_service_supabase
    try:
        get_service_supabase().table("audit_log").insert({
            "firm_id": firm_id,
            "actor_id": actor.get("auth_user_id"),          # the AUTH id: that is the audit log's flavour of actor
            "actor_email": actor.get("email"),
            "entity_type": "brought_forward_loss",
            "entity_id": row.get("id"),
            "action": "update",
            "old_data": {"utilisations": entries_of(row), "utilized_amount_paise": int(row.get("utilized_amount_paise") or 0),
                         "remaining_amount_paise": int(row.get("remaining_amount_paise") or 0)},
            "new_data": {"requested": dict(requested), "reason": reason},
            "metadata": {"client_id": row.get("client_id"), "change": change},
        }).execute()
    except Exception as exc:                                # noqa: BLE001
        from core.observability import capture_soft_failure
        capture_soft_failure(exc, operation="bf_loss_service.hand_correction_audit", firm_id=firm_id, client_id=row.get("client_id"))
        raise UseRefused("The loss record was not changed, because the audit log could not be written just now and the audit log is the only "
                         "account of why it would have. Nothing changed; try again in a moment.", status=503) from exc


def _store_or_refuse(firm_id: str, row: Mapping[str, Any], columns: Mapping[str, Any]) -> None:
    """Write the three columns only while the record still reads as it did, or refuse in words (told apart by reading it again, as the
    acknowledgement's write-back does: its totals moved, or it is not writable by this caller)."""
    row = dict(row)
    if workspace.store_bf_loss_use(firm_id, str(row["id"]), row, dict(columns)):
        return
    now = workspace.get_bf_loss(firm_id, str(row["id"])) or {}
    if (now.get("utilized_amount_paise"), now.get("remaining_amount_paise")) != (
            row.get("utilized_amount_paise"), row.get("remaining_amount_paise")):
        raise UseRefused("The loss record changed while this was being saved, so it was left as it was. Reload the loss and try again.", 409)
    raise UseRefused("This loss record could not be written with your access, so it was left as it was.", 403)


def _loss(firm_id: str, loss_id: str) -> dict:
    row = workspace.get_bf_loss(firm_id, loss_id)
    if not row:
        raise UseRefused("Loss record not found", 404)
    return row


def record_year_use(current_user: Mapping[str, Any], loss_id: str, financial_year: str, amount_paise: int, reason: str) -> dict:
    """Record that `financial_year` used `amount_paise` of this loss, by hand. The year's entry is SET (a second call replaces it, never adds),
    an amount of nothing takes it away, a year a return's entry holds is refused, and an amount past what the record could take is refused
    with the figure it could (`loss_utilisation.record_by_hand`). The reason and what the record held go into the audit log first."""
    firm_id = current_user["firm_id"]
    why = clean_reason(reason)
    row = _loss(firm_id, loss_id)
    fy = (financial_year or "").strip()
    try:
        columns = record_by_hand(row, fy, amount_paise)
    except HeldByReturn:
        raise UseRefused(f"A return on file already holds FY {fy}'s use of this loss, so it is corrected on that return (the Tax Filing screen "
                         "writes its loss records again) and not by hand. If that return's use is wrong, take it off the list first and "
                         "then record the year.", 409) from None
    except MoreThanTheRecordCanTake as exc:
        raise UseRefused(f"FY {fy} cannot be recorded as using more than {rupee_text(exc.room_paise)} of this loss: the loss is "
                         f"{rupee_text(int(row.get('original_amount_paise') or 0))}, and other years' uses and the part recorded by hand "
                         "have used the rest.") from None
    except ValueError as exc:
        raise UseRefused(f"{str(exc)[:1].upper()}{str(exc)[1:]}.") from None
    if _already_what_it_should_be(row, columns):
        return {"state": UNCHANGED, "loss_id": str(row["id"]), "financial_year": fy,
                "message": f"The record already shows {rupee_text(columns['utilisations'].get(f'{MANUAL}:{fy}', {}).get('amount_paise', 0))} "
                           f"for FY {fy}."}
    _write_audit_or_refuse(firm_id=firm_id, row=row, change="year_use_recorded_by_hand", reason=why, actor=current_user,
                           requested={"financial_year": fy, "amount_paise": int(amount_paise)})
    _store_or_refuse(firm_id, row, columns)
    recorded = columns["utilisations"].get(f"{MANUAL}:{fy}", {}).get("amount_paise", 0)
    return {"state": WRITTEN, "loss_id": str(row["id"]), "financial_year": fy, "recorded_paise": recorded,
            "message": (f"FY {fy} is recorded as having used {rupee_text(recorded)} of this loss." if recorded
                        else f"The hand entry for FY {fy} was taken off this loss.")}


def take_back_use(current_user: Mapping[str, Any], loss_id: str, entry_id: str, reason: str) -> dict:
    """Take one entry off the record: a hand entry, or the use a filed return had written. The part recorded by hand without a year (the old
    route's) is not an entry and is not taken back here. A return's entry comes back the next time that return's loss records are written, and
    the answer says so."""
    firm_id = current_user["firm_id"]
    why = clean_reason(reason)
    row = _loss(firm_id, loss_id)
    held = entries_of(row).get(str(entry_id))
    try:
        columns = take_back(row, entry_id)
    except NoSuchEntry:
        raise UseRefused("That use is not on this loss record (it may already have been taken back).", 404) from None
    _write_audit_or_refuse(firm_id=firm_id, row=row, change="use_taken_back", reason=why, actor=current_user,
                           requested={"entry_id": str(entry_id), "financial_year": (held or {}).get("financial_year"),
                                      "amount_paise": (held or {}).get("amount_paise"), "kind": (held or {}).get("return_type")})
    _store_or_refuse(firm_id, row, columns)
    by_a_return = (held or {}).get("return_type") != MANUAL
    note = (" It was written by a filed return, and it comes back the next time that return's loss records are written; to keep it off, "
            "do not write them again.") if by_a_return else ""
    return {"state": WRITTEN, "loss_id": str(row["id"]), "entry_id": str(entry_id),
            "message": f"The use of {rupee_text((held or {}).get('amount_paise') or 0)} for FY {(held or {}).get('financial_year')} was taken "
                       f"off this loss.{note}"}
