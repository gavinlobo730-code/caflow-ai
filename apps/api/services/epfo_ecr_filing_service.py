"""
Reading and writing what the CA filed with EPFO, so the sequence can be known.

WHAT THIS IS FOR

`domain/payroll/ecr_sequence.py` decides which returns a wage month still needs
and what is blocking it. It is pure: it takes months and filings and returns an
answer. This module is the only thing that turns database rows into those
inputs, and the only thing that writes a filing down.

WHY THE CA TYPES THIS IN

There is no EPFO API. None — not for ECR upload, not for challan generation, not
for UAN allotment (docs/compliance/04-mca-epfo-esic.md; the clearest evidence is
a documented case of an employer driving the portal with RPA). So the product
cannot observe that a return was filed. It can only be told.

That makes the recording step the load-bearing one. A CA who never records a
filing sees every month as outstanding, which is annoying but safe. A CA who
records one that did not happen sees a month as clear that the portal will
block, which is the failure this whole feature exists to prevent — so
`record_filing` writes what it is told and never infers a filing from anything
else happening, and in particular NOT from a run being finalised. Finalising a
run closes the books; it does not upload anything.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing in this module transmits
# anything to EPFO. It records what a human did on the portal, after they did it.
"""
from __future__ import annotations

import logging
from typing import Optional

from core.ist_clock import ist_today
from domain.payroll import ecr_sequence as seq

_logger = logging.getLogger("caflow.epfo_ecr")

# The table name is written out in full at every call site rather than held in a
# constant here. tests/test_backend_columns_exist_pg.py reads table and column
# names as source text and cannot follow a variable, so a constant would hide
# every column on this table from the check that catches a rename breaking a
# query. Two extra characters of typing against a silent class of bug.

#: Run statuses that mean a wage month's figures are settled and the month is
#: therefore one EPFO expects a return for. A draft run is not a month that is
#: outstanding at the portal — nothing has been closed yet.
FINALISED_RUN_STATUSES = ("finalized", "paid")


class ECRFilingError(ValueError):
    """A filing that cannot be recorded as given."""


def _member_rows(members) -> list[dict]:
    return [m.as_dict() for m in (members or [])]


def _members_from_row(raw) -> tuple[seq.FiledMember, ...]:
    """Rehydrate the frozen figures, skipping anything malformed.

    Skipping rather than raising: this is read on every ECR build, and one bad
    member entry must not make a client's whole filing history unreadable. A
    skipped member reads as "not on any approved return", which recommends a
    Supplementary — the safe direction, since filing a Supplementary for a
    member already on the Regular is visible at the portal, while omitting one
    is not.
    """
    out: list[seq.FiledMember] = []
    for m in (raw or []):
        if not isinstance(m, dict):
            continue
        uan = str(m.get("uan") or "").strip()
        if not uan:
            continue
        try:
            out.append(seq.FiledMember(
                uan=uan,
                epf_wages=int(m.get("epf_wages") or 0),
                epf_contribution=int(m.get("epf_contribution") or 0),
                eps_contribution=int(m.get("eps_contribution") or 0)))
        except (TypeError, ValueError):
            continue
    return tuple(out)


def members_from_ecr(ecr) -> tuple[seq.FiledMember, ...]:
    """The three comparable figures off a built ECRFile.

    Taken from the file that is about to be uploaded rather than from the
    payslips, so what gets frozen is what was actually filed. The two agree
    today; if they ever stop agreeing, the file is the thing EPFO holds.
    """
    return tuple(seq.FiledMember(
        uan=m.uan, epf_wages=m.epf_wages,
        epf_contribution=m.epf_contribution,
        eps_contribution=m.eps_contribution) for m in ecr.members)


def read_filings(db, *, firm_id: str, client_id: str) -> list[seq.RecordedFiling]:
    """Every live filing recorded for a client, as the domain's own type."""
    if not db or not client_id:
        return []
    rows = (db.table("epfo_ecr_filings")
            .select("wage_month, return_type, status, members")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .is_("deleted_at", "null")
            .execute().data) or []
    return [seq.RecordedFiling(
        wage_month=str(r.get("wage_month") or ""),
        return_type=str(r.get("return_type") or ""),
        status=str(r.get("status") or ""),
        members=_members_from_row(r.get("members"))) for r in rows]


def finalised_months(db, *, firm_id: str, client_id: str) -> list[str]:
    """Wage months this client has a finalised or paid run for.

    This is the whole basis of "outstanding", and its limit: a month run on
    paper, with a previous provider, or before onboarding is not here and will
    still block the upload. Callers surface that limit rather than presenting an
    empty list as "nothing owing" — see Sequence.note.
    """
    if not db or not client_id:
        return []
    rows = (db.table("payroll_runs").select("month, status")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("status", list(FINALISED_RUN_STATUSES))
            .execute().data) or []
    return sorted({str(r.get("month") or "") for r in rows
                   if seq.is_month(r.get("month"))})


def record_filing(
    db, *, firm_id: str, client_id: str, wage_month: str, return_type: str,
    status: str = seq.SUBMITTED, submitted_on: Optional[str] = None,
    approved_on: Optional[str] = None, trrn: Optional[str] = None,
    run_id: Optional[str] = None, members=(), recorded_by: Optional[str] = None,
) -> dict:
    """Write down a return the CA filed at the portal.

    Refuses before it writes rather than letting the CHECK constraints do it, so
    the CA gets a sentence about EPFO instead of a Postgres error — the same
    reason models/common wraps a database refusal.

    Updating in place on (client_id, wage_month, 'regular') is deliberate and
    only applies to a Regular: recording the submission and then the approval is
    two entries about ONE return, and the partial unique index would reject the
    second anyway. A Supplementary or a Revised is a new row every time, because
    a month can genuinely need several of either.
    """
    if not seq.is_month(wage_month):
        raise ECRFilingError(
            f"{wage_month!r} is not a wage month. Use YYYY-MM — the month whose "
            f"contributions the return reports, not the month you filed it in.")
    if return_type not in (seq.REGULAR, seq.SUPPLEMENTARY, seq.REVISED):
        raise ECRFilingError(
            f"{return_type!r} is not an EPFO return type. It is one of "
            f"{seq.REGULAR} (every active member for the month), "
            f"{seq.SUPPLEMENTARY} (members registered after the Regular was "
            f"approved) or {seq.REVISED} (figures already submitted, corrected).")
    if status not in (seq.SUBMITTED, seq.APPROVED):
        raise ECRFilingError(
            f"{status!r} is not a filing state. A return is {seq.SUBMITTED} "
            f"until EPFO validates it and {seq.APPROVED} after — and only an "
            f"approved return clears the month for the next one.")

    submitted = submitted_on or ist_today().isoformat()
    if status == seq.APPROVED and not approved_on:
        # An approved return needs a date; defaulting it to the submission date
        # is the honest fallback for a CA recording both at once, and the CHECK
        # would otherwise refuse the row with nothing useful to say.
        approved_on = submitted
    if approved_on and approved_on < submitted:
        raise ECRFilingError(
            "A return cannot be approved before it was submitted.")

    row = {
        "firm_id": firm_id, "client_id": client_id, "wage_month": wage_month,
        "return_type": return_type, "status": status,
        "submitted_on": submitted, "members": _member_rows(members),
    }
    if approved_on:
        row["approved_on"] = approved_on
    if trrn:
        row["trrn"] = str(trrn).strip()
    if run_id:
        row["run_id"] = run_id
    if recorded_by:
        row["recorded_by"] = recorded_by

    if return_type == seq.REGULAR:
        existing = (db.table("epfo_ecr_filings").select("id")
                    .eq("client_id", client_id).eq("wage_month", wage_month)
                    .eq("return_type", seq.REGULAR)
                    .is_("deleted_at", "null")
                    .limit(1).execute().data) or []
        if existing:
            db.table("epfo_ecr_filings").update(row).eq("id", existing[0]["id"]).execute()
            row["id"] = existing[0]["id"]
            return row

    inserted = (db.table("epfo_ecr_filings").insert(row).execute().data) or []
    if inserted and inserted[0].get("id"):
        row["id"] = inserted[0]["id"]
    return row


def retract_filing(db, *, firm_id: str, filing_id: str,
                   at_iso: Optional[str] = None) -> bool:
    """Soft-delete a filing recorded in error.

    Never a hard delete: retracting a Regular un-blocks every later month, and
    a row that simply vanished would leave no record that the sequence had
    changed or who changed it.
    """
    res = (db.table("epfo_ecr_filings")
           .update({"deleted_at": at_iso or ist_today().isoformat()})
           .eq("id", filing_id).eq("firm_id", firm_id)
           .is_("deleted_at", "null").execute().data)
    return bool(res)
