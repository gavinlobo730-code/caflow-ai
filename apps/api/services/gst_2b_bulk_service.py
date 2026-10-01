"""Reconcile several clients' GSTR-2B files in one action, each routed by the
GSTIN inside it (gst-10).

WHAT WAS MISSING
    A 2B was reconciled one client at a time, from that client's own tab. A
    practice with sixty clients downloads sixty files in one sitting and opened
    sixty tabs to use them. This takes a drop of files, finds the client each
    belongs to from the GSTIN the file itself names (`domain/gst/gstr2b_routing`
    is the rule), runs the SAME per-client path the single upload runs, and
    answers per file.

IT IS THE SINGLE UPLOAD, REPEATED — NOT A SECOND RECONCILER
    Every file that routes goes through `gstr2b_intake.assess` (the month comes
    off the file; a GSTIN the client does not hold as a registration is refused)
    and `reconcile_2b` (the one writer of `gstr2a_records` and its header),
    then `keep_upload` and `log_discrepancies` — the very functions
    `POST /gstr2b/upload` calls. A rule added to one door is therefore a rule of
    both, which is the failure two parallel implementations are famous for.

A FILE THAT BELONGS TO NOBODY YOU MAY SEE IS REPORTED AND NOT KEPT
    An unmatched GSTIN, an ambiguous one, a file that is not a 2B, a file the
    intake refuses: each comes back as its own row with its own sentence and
    NOTHING is written for it. Not under the first client, not under a default,
    not under the firm. A file for a client outside the caller's assigned book is
    the same row as one nobody holds, in the same words (see the routing module
    on why). `can_access` asks the access check a SECOND time per routed client,
    belt and braces: the routing's `visible` set is the scope, and this is the
    firm-ownership and assignment check every other client-scoped route runs.

A BATCH FACT THAT NO SINGLE FILE CAN SEE
    Two files for the same client and month in one upload would each replace the
    other, and which one survived would be the order they were dropped in. The
    first is reconciled; the second is REFUSED, naming the first, and replaces
    nothing. Across separate requests that is not knowable here — a re-upload
    replaces, as it always has — so every result says whether it REPLACED an
    earlier reconciliation (`replaced_earlier`, with when and which download), and
    the screen shows it: an older download dropped into a folder of sixty must
    not overwrite a newer one without a word.

WHAT COMES BACK IS A SUMMARY, NOT THE MATCHES
    Sixty clients' per-document match lists are a response proportional to the
    month's volume for an answer a CA wants as a table of sixty rows. Each result
    carries the counts and the credit at risk; the documents are one click away
    on the client's own GSTR-2B tab, where they were always shown.

BOUNDED BY THE REQUEST, NOT BY A BACKGROUND JOB
    `lib/api` aborts a request at 45 seconds and never retries it, and Render's
    free tier cold-starts. A reconciliation reads a month of bills and replaces
    a month of documents across a Singapore-to-Mumbai link, so the route takes at
    most `MAX_FILES_PER_REQUEST` files and the screen sends them in turn: each
    request is bounded, a failure costs one file, and there is no job to lose on
    a restart. Nothing here is scheduled.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing is sent to a portal; the
# files the CA downloaded from gst.gov.in are read here and nowhere else.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional, Sequence

from fastapi import HTTPException

from domain.gst import gstr2b_intake, gstr2b_routing
from domain.gst.gstr2b import parse_gstr2b
from services import client_gst_registration_service as regs
from services import gst_2b_reconciliation_service as recon

_logger = logging.getLogger("caflow.gst_2b_bulk")

#: How many files one request may carry. See the module docstring: a request is
#: bounded because the browser aborts at 45 seconds and never retries.
MAX_FILES_PER_REQUEST = 5

RECONCILED = "reconciled"
UNMATCHED_GSTIN = gstr2b_routing.UNMATCHED_GSTIN
AMBIGUOUS_GSTIN = gstr2b_routing.AMBIGUOUS_GSTIN
REFUSED = "refused"
UNREADABLE = "unreadable"
FAILED = "failed"

#: Every status a result may carry, in the order a screen lists them.
STATUSES = (RECONCILED, UNMATCHED_GSTIN, AMBIGUOUS_GSTIN, REFUSED, UNREADABLE, FAILED)

_COUNTS = ("matched_count", "amount_mismatch_count", "missing_in_2b_count",
           "missing_in_books_count", "itc_at_risk_paise", "itc_blocked_by_2b_paise")


def _result(name: str, status: str, *, reason: Optional[str] = None,
            gstin: str = "", period: Optional[str] = None,
            client_id: Optional[str] = None, client_name: Optional[str] = None,
            summary: Optional[dict] = None, problems: Sequence[str] = (),
            caveat: Optional[str] = None, replaced: Optional[dict] = None,
            probable: int = 0) -> dict:
    """One row. EVERY key is always present and null where it does not apply —
    an absent key and a null key read the same to a screen and are different
    bugs, the discipline `journal_source` and `payment_account.row_notice` keep."""
    needs = False
    if status == RECONCILED and summary:
        needs = bool(
            summary.get("amount_mismatch_count") or summary.get("missing_in_2b_count")
            or summary.get("missing_in_books_count")
            or summary.get("itc_blocked_by_2b_paise") or probable
            or problems or caveat or replaced)
    return {
        "name": name,
        "status": status,
        "reason": reason,
        "gstin": gstin,
        "period": period,
        "client_id": client_id,
        "client_name": client_name,
        "needs_attention": needs,
        "summary": ({k: int(summary.get(k) or 0) for k in _COUNTS}
                    | {"probable_match_count": int(probable)}) if summary else None,
        "problems": list(problems),
        "registration_caveat": caveat,
        "replaced_earlier": replaced,
    }


def _client_names(db, firm_id: str, ids: Sequence[str]) -> dict[str, str]:
    ids = sorted({str(i) for i in ids if i})
    if not ids:
        return {}
    rows = (db.table("clients").select("id, client_name, legal_name")
            .eq("firm_id", firm_id).in_("id", ids).execute().data) or []
    return {str(r["id"]): (r.get("legal_name") or r.get("client_name") or "")
            for r in rows}


def process(db, *, firm_id: str, files: Sequence[dict],
            visible: Optional[set[str]],
            can_access: Callable[[str], bool],
            created_by: Optional[str], timeline) -> dict:
    """Route and reconcile each file; answer per file. Never raises for one file.

    `files` is `[{"name": str, "raw": dict}, ...]`. `visible` is the caller's
    assignment scope (`core.authz.effective_client_ids`: None is every client of
    the firm, a set is exactly those, an empty set is none). `can_access` is the
    per-client access check. `timeline` is the caller's `timeline_service`.
    """
    parsed = [(f.get("name") or "", f.get("raw"), parse_gstr2b(f.get("raw")))
              for f in files]
    holders = recon.holders_of(
        db, firm_id=firm_id,
        gstins=[p.gstin for _n, _r, p in parsed if p.docdata_seen])

    # Names only for clients the caller may see: a name that was never fetched
    # cannot be put on a row by a later change.
    names = _client_names(db, firm_id, [h.client_id for h in holders
                                        if visible is None or h.client_id in visible])
    done: dict[tuple[str, str], str] = {}
    results: list[dict] = []

    for name, raw, pf in parsed:
        try:
            results.append(_one(
                db, firm_id=firm_id, name=name, raw=raw, parsed=pf,
                holders=holders, names=names, visible=visible,
                can_access=can_access, created_by=created_by, timeline=timeline,
                done=done))
        except Exception:                                       # noqa: BLE001
            # ONE FILE'S FAILURE IS ONE ROW, never the batch's. The reason is
            # generic on purpose: an exception's text names tables and ids.
            _logger.exception("caflow.gst2b.bulk: %s failed", name)
            results.append(_result(
                name, FAILED, gstin=pf.gstin,
                reason=("This file could not be reconciled and the cause was "
                        "logged. Try it again on its own from the client's "
                        "GSTR-2B tab; nothing is claimed about what was stored.")))

    totals = {s: 0 for s in STATUSES}
    for r in results:
        totals[r["status"]] += 1
    return {
        "results": results,
        "totals": totals,
        "needs_attention": sum(1 for r in results if r["needs_attention"]),
    }


def without_a_database(files: Sequence[dict]) -> dict:
    """The answer in mock mode, where there is no client table to route against.

    Every file is READ — a file that is not a 2B is still said to be one that is
    not — and none is routed, matched or kept, and the row says so. It is never
    rendered as a reconciliation: the single upload's mock branch makes the same
    refusal for the same reason (a clean result from comparing nothing against
    nothing is the defect the 2B reconciliation exists to end).
    """
    results = []
    for f in files:
        parsed = parse_gstr2b(f.get("raw"))
        name = f.get("name") or ""
        if not parsed.docdata_seen:
            results.append(_result(name, UNREADABLE, gstin=parsed.gstin,
                                   reason=" ".join(parsed.problems)))
        else:
            results.append(_result(
                name, FAILED, gstin=parsed.gstin,
                reason=("Running without a database: the file was read and NOT "
                        "routed to a client or matched against any bill.")))
    totals = {s: 0 for s in STATUSES}
    for r in results:
        totals[r["status"]] += 1
    return {"results": results, "totals": totals, "needs_attention": 0}


def _one(db, *, firm_id, name, raw, parsed, holders, names, visible, can_access,
         created_by, timeline, done) -> dict:
    routing = gstr2b_routing.route(parsed, holders, visible)

    if routing.verdict == gstr2b_routing.NOT_A_GSTR2B:
        return _result(name, UNREADABLE, reason=routing.reason, gstin=routing.gstin)
    if routing.verdict == gstr2b_routing.NO_GSTIN:
        return _result(name, REFUSED, reason=routing.reason)
    if routing.verdict == gstr2b_routing.UNMATCHED_GSTIN:
        return _result(name, UNMATCHED_GSTIN, reason=routing.reason, gstin=routing.gstin)
    if routing.verdict == gstr2b_routing.AMBIGUOUS_GSTIN:
        return _result(name, AMBIGUOUS_GSTIN, reason=routing.reason, gstin=routing.gstin)

    client_id = str(routing.client_id)
    if not can_access(client_id):
        # The second, firm-ownership-and-assignment check. Answered as the SAME
        # row as a GSTIN nobody holds — see the module docstring.
        return _result(name, UNMATCHED_GSTIN, gstin=routing.gstin,
                       reason=gstr2b_routing.unmatched_sentence(routing.gstin))

    try:
        held = regs.held(db, firm_id, client_id)
    except HTTPException:
        return _result(name, UNMATCHED_GSTIN, gstin=routing.gstin,
                       reason=gstr2b_routing.unmatched_sentence(routing.gstin))

    intake = gstr2b_intake.assess(parsed, typed_period=None, registrations=held)
    client_name = names.get(client_id)
    if intake.refusals:
        return _result(name, REFUSED, reason=" ".join(intake.refusals),
                       gstin=routing.gstin, client_id=client_id,
                       client_name=client_name)

    period = str(intake.period)
    key = (client_id, period)
    if key in done:
        return _result(
            name, REFUSED, gstin=routing.gstin, period=period,
            client_id=client_id, client_name=client_name,
            reason=(f"'{done[key]}' in this same upload is already the GSTR-2B "
                    f"for this client and {gstr2b_intake.label_of(period)}. "
                    f"Nothing was replaced: choose which of the two is the one "
                    f"you mean and upload it on its own."))

    previous = recon.previous_reconciliation(
        db, firm_id=firm_id, client_id=client_id, period=period)

    try:
        out = recon.reconcile_2b(db, firm_id=firm_id, client_id=client_id,
                                 period=period, raw=raw)
    except ValueError as e:
        # reconcile_2b asks the period half of the intake again, because it is
        # the function that writes. A refusal there is this file's, not the batch's.
        return _result(name, REFUSED, reason=str(e), gstin=routing.gstin,
                       period=period, client_id=client_id, client_name=client_name)

    recon.keep_upload(db, firm_id=firm_id, client_id=client_id, period=period,
                      raw=raw, file_url=None, created_by=created_by, result=out)
    done[key] = name
    recon.log_discrepancies(timeline, firm_id=firm_id, client_id=client_id,
                            period=period, summary=out.get("summary"))

    if not out.get("persisted"):
        # A file that parsed as a 2B but wrote nothing. The service has already
        # said why in `problems`; it is reported, never counted as reconciled.
        return _result(name, REFUSED, gstin=routing.gstin, period=period,
                       client_id=client_id, client_name=client_name,
                       reason=" ".join(out.get("problems") or []) or
                       "Nothing was reconciled and nothing was saved.")

    replaced = None
    if previous:
        replaced = {"reconciled_at": previous.get("reconciled_at"),
                    "generated_on": previous.get("generated_on")}
    caveats = [c for c in (intake.registration_caveat,) if c]
    return _result(
        name, RECONCILED, gstin=routing.gstin, period=period,
        client_id=client_id, client_name=client_name,
        summary=out.get("summary"),
        problems=list(out.get("problems") or []) + list(intake.notes) + caveats,
        caveat=intake.registration_caveat, replaced=replaced,
        probable=len(out.get("probable_matches") or []))
