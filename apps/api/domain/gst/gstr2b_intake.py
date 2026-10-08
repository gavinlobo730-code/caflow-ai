"""Whose GSTR-2B is this file, and for which month — decided from the FILE (gst-09).

WHAT WAS WRONG
    The 2B screen asked the CA to TYPE the period (MMYYYY) and to paste a
    multi-megabyte JSON into a textarea, although the file already says both
    things that matter: `data.rtnprd` is the month and `data.gstin` is the
    RECIPIENT's registration. The parser has returned both since it was written
    and neither decided anything.

    So the two could disagree, and the disagreement was not refused. The service
    appended a sentence to `problems` and then wrote the file's documents under
    the TYPED period all the same — replacing that month's previous
    reconciliation with another month's documents, matched against the wrong
    month's bills. That is not a warning; it is a wrong figure under Rule 36(4)
    (CGST Rules 2017) for a month somebody had already reconciled correctly, and
    §16(2)(aa) turns the credit on exactly what that table says.

    The GSTIN was not asked at all. A 2B belongs to ONE registration — CGST §25
    makes registration state-wise and GSTR-2B is generated per GSTIN — so a file
    downloaded for another client is reconciled against this client's bills and
    reported, bill by bill, as the supplier not having filed.

WHAT THIS DECIDES, AND WHAT IT DOES NOT
    It is pure: it takes the parsed file, the period the caller typed (if any)
    and the registrations the client holds, and answers with the period to use
    and the reasons the file must be refused. It reads nothing and writes
    nothing; `services/gst_2b_reconciliation_service` and the router fetch its
    inputs and act on the answer.

    **THE FILE DECIDES THE MONTH, AND A TYPED MONTH IS ONLY EVER A CHECK.** Where
    the two disagree the file is REFUSED rather than one of them picked — taking
    the typed value reproduces the defect above, and taking the file's silently
    discards what somebody typed on a screen that offered them the box; the
    same shape `SalesInvoiceIn` takes where `supply_state_code` and
    `place_of_supply` disagree. A file naming no period at all falls back to the
    typed one and SAYS the typed month could not be checked; with neither there
    is no month to reconcile against, and that is refused.

    **A GSTIN THE CLIENT DOES NOT HOLD IS REFUSED, AND SO IS ONE THE FILE DOES NOT
    NAME.** `registrations.resolve` refuses a GSTIN the client does not hold and
    never defaults to the primary, for the reason this module repeats: filing one
    registration's figures under another's is invisible until somebody notices.
    A file with no `data.gstin` cannot be checked, and a portal download always
    carries one, so its absence means the file was edited or is not a download —
    refused with the sentence saying so. With no registrations list at all (mock
    mode has no `client_gst_registrations` table to read) the check is NOT MADE
    and the answer says so; "not checked" is never rendered as "matches".

    **A FILE THAT IS NOT A GSTR-2B IS NOT THIS MODULE'S QUESTION.** `docdata_seen`
    false means the parser found no `data.docdata`; nothing here can be asked of
    it, and the existing path reports it (`persisted: false`, the parser's own
    sentences) without persisting anything.

WHAT IT DELIBERATELY DOES NOT DO
    It does not split the client's purchase bills by registration. No bill
    records which registration it was received under (attributing each document
    to a registration is what adds that),
    so a client holding several registrations has one reconciliation per MONTH,
    not per GSTIN: a second registration's 2B matches against ALL the client's
    bills and REPLACES the first's. That is named on every answer for such a
    client (`registration_caveat`) rather than refused, because refusing would
    make a client with two registrations impossible to reconcile at all, and it
    is the same direction `registrations.documents_not_split_caveat` takes for
    the returns.

It does not accept the portal's Excel download. The layout of that workbook was
not available to read here, and a parser written from memory of it would be the
"invented field list" this product refuses everywhere else.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from typing import Optional, Sequence

from domain.gst.gstr2b import GSTR2BFile
from domain.gst.registrations import Registration
from domain.gst.return_period import parse_month
from domain.spreadsheet_cells import parse_cell_date

#: Where the period the answer carries came from.
FROM_FILE = "file"
FROM_REQUEST = "typed"
NOWHERE = "none"

#: Said when no registrations were supplied to check against. Not a refusal:
#: the check was not made, which is different from the check passing.
GSTIN_NOT_CHECKED = (
    "This file's GSTIN was NOT checked against the client's registrations — "
    "there is no database here to read them from.")


def label_of(period: str) -> str:
    """'042025' → 'April 2025 (042025)'. The code beside the name because the
    portal, the return and the database all speak the code."""
    mm, yyyy = parse_month(period)
    return f"{calendar.month_name[mm]} {yyyy} ({period})"


def _valid(period: Optional[str]) -> bool:
    try:
        parse_month(str(period or "").strip())
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class Intake:
    """What a file may be reconciled as, or why it may not be."""
    #: The month to reconcile, canonical MMYYYY; None where the file is refused
    #: or is not a GSTR-2B at all.
    period: Optional[str]
    period_source: str
    #: The recipient GSTIN the FILE names, normalised; "" where it names none.
    gstin: str
    #: The registration the client holds that the file is for; None where the
    #: check was not made or the file was refused.
    registration: Optional[Registration]
    #: Sentences. Non-empty means the file must not be reconciled.
    refusals: tuple[str, ...] = ()
    #: Things said and not refused — a typed month that could not be checked,
    #: a GSTIN check that was not made.
    notes: tuple[str, ...] = ()
    #: Always present, null where the client holds one registration or none.
    registration_caveat: Optional[str] = None
    #: `data.docdata` was present — this IS a GSTR-2B, whatever it contained.
    is_gstr2b: bool = True

    @property
    def can_reconcile(self) -> bool:
        return self.is_gstr2b and not self.refusals


def two_b_not_split_caveat(regs: Sequence[Registration],
                           chosen_gstin: str) -> Optional[str]:
    """The sentence a 2B owes when its client holds several registrations.

    Applies to EVERY registration of such a client, the primary included, for
    `documents_not_split_caveat`'s reason: the primary's 2B is matched against
    the same client-wide bills, so it over-reports exactly as much.
    """
    if len(regs) < 2 or not any(r.gstin == chosen_gstin for r in regs):
        return None
    others = ", ".join(r.gstin for r in regs if r.gstin != chosen_gstin)
    return (
        f"This client holds {len(regs)} GST registrations and no purchase bill "
        f"records which one it was received under. This GSTR-2B for "
        f"{chosen_gstin} is therefore matched against ALL of the client's bills "
        f"for the month, including any that belong to {others}, and it REPLACES "
        f"any GSTR-2B already reconciled for this month under another "
        f"registration — a month holds one reconciliation per client, not one "
        f"per GSTIN.")


# ── a download that replaces an earlier one ──────────────────────────────────
#
# A reconciliation is replaced whole, so an upload for a client and month that
# already has one needs a word (gst-10): "a stale download dropped into a folder
# of sixty must not silently overwrite a newer one". The word is only NEEDED when
# the new file might be the older one. Asked of every replacement it was said as
# "Check this is the newer file" — including when the same file was dropped twice
# (PRE-A-001, found by re-dropping an identical download), which taught the CA to
# read past it.

SAME_DOWNLOAD = "same"
OLDER_DOWNLOAD = "older"
NEWER_DOWNLOAD = "newer"
UNKNOWN_DOWNLOAD = "unknown"

#: What the screen says under the "replaced" line, by relation. The sentences are
#: the server's: the screen decides nothing about which download is newer.
DOWNLOAD_NOTES = {
    SAME_DOWNLOAD: ("This is the same download, so only the books have been read "
                    "again."),
    NEWER_DOWNLOAD: "This download is newer than the one it replaced.",
    OLDER_DOWNLOAD: ("This download is OLDER than the one it replaced. Check it is "
                     "the file you meant before relying on these figures."),
    UNKNOWN_DOWNLOAD: ("The date either download was generated could not be read, "
                       "so which is newer is not known. Check this is the newer file."),
}

#: Only these two leave the CA something to check. A newer download replacing an
#: older one is the ordinary case, and an identical one changes nothing.
DOWNLOAD_NEEDS_A_LOOK = frozenset({OLDER_DOWNLOAD, UNKNOWN_DOWNLOAD})


def download_relation(earlier_generated_on: Optional[str],
                      new_generated_on: Optional[str]) -> str:
    """How the new download stands to the one it replaced, by the date the portal
    generated each (`data.gendt`, written day-first: 14-05-2025).

    `same` when both dates read and are equal, or when both are the same
    non-empty text that does not read; `older` / `newer` when both read and
    differ; `unknown` when either is missing or unreadable, which is never
    treated as `same` or `newer` (a date nobody can read proves nothing about
    which file is the stale one). The date is a DAY, so two downloads on one day
    are `same` — the portal's 2B for a period is a statement, regenerated, not a
    stream.
    """
    before = (earlier_generated_on or "").strip()
    after = (new_generated_on or "").strip()
    if not before or not after:
        return UNKNOWN_DOWNLOAD
    a, b = parse_cell_date(before), parse_cell_date(after)
    if a is None or b is None:
        return SAME_DOWNLOAD if before == after else UNKNOWN_DOWNLOAD
    if b == a:
        return SAME_DOWNLOAD
    return NEWER_DOWNLOAD if b > a else OLDER_DOWNLOAD


def assess(parsed: GSTR2BFile, *, typed_period: Optional[str] = None,
           registrations: Optional[Sequence[Registration]] = None) -> Intake:
    """Decide the month and whose the file is. See the module docstring.

    `registrations=None` means "not supplied" (the check cannot be made);
    an EMPTY sequence means the client holds none, which is a refusal.
    """
    if not parsed.docdata_seen:
        return Intake(period=None, period_source=NOWHERE,
                      gstin=parsed.gstin, registration=None, is_gstr2b=False)

    refusals: list[str] = []
    notes: list[str] = []

    # ── the month ────────────────────────────────────────────────────────────
    in_file = (parsed.return_period or "").strip()
    typed = (typed_period or "").strip()
    period: Optional[str] = None
    source = NOWHERE

    if in_file and not _valid(in_file):
        refusals.append(
            f"The file names its return period as '{in_file}', which is not a "
            f"month in the portal's MMYYYY form (for example 042025), so it "
            f"cannot be told which month this GSTR-2B is for.")
    elif typed and not _valid(typed):
        refusals.append(
            f"The period given, '{typed}', is not MMYYYY (for example 042025).")
    elif in_file and typed and in_file != typed:
        refusals.append(
            f"This file is GSTR-2B for {label_of(in_file)} but the period given "
            f"was {label_of(typed)}. Nothing was reconciled: matching it against "
            f"{label_of(typed)}'s bills would replace that month's reconciliation "
            f"with another month's documents.")
    elif in_file:
        period, source = in_file, FROM_FILE
    elif typed:
        period, source = typed, FROM_REQUEST
        notes.append(
            f"The file names no return period, so {label_of(typed)} is the month "
            f"you gave and could not be checked against the file.")
    else:
        refusals.append(
            "This file names no return period and none was given, so there is no "
            "month to reconcile it against. A GSTR-2B as downloaded from the "
            "portal carries one — do not edit the file.")

    # ── whose it is ──────────────────────────────────────────────────────────
    gstin = (parsed.gstin or "").strip().upper()
    registration: Optional[Registration] = None
    caveat: Optional[str] = None

    if registrations is None:
        notes.append(GSTIN_NOT_CHECKED)
    elif not registrations:
        refusals.append(
            "This client has no GST registration recorded, so no GSTR-2B can be "
            "reconciled for it. Record the GSTIN on the client first.")
    elif not gstin:
        refusals.append(
            "This file names no recipient GSTIN (`data.gstin`), so it cannot be "
            "checked against this client's registrations. A GSTR-2B as "
            "downloaded from the portal always carries one — do not edit the "
            "file.")
    else:
        registration = next((r for r in registrations if r.gstin == gstin), None)
        if registration is None:
            held = ", ".join(r.gstin for r in registrations)
            refusals.append(
                f"This file is GSTR-2B for {gstin}, which is not a registration "
                f"recorded for this client. The registrations on file are: "
                f"{held}. Upload the file downloaded for one of those, or record "
                f"{gstin} under the client's GST registrations first.")
        else:
            caveat = two_b_not_split_caveat(registrations, gstin)

    if refusals:
        # A refused file has no month to reconcile against and no registration
        # it is cleared for, whatever was half-worked-out above.
        period, source, registration = None, NOWHERE, None

    return Intake(period=period, period_source=source, gstin=gstin,
                  registration=registration, refusals=tuple(refusals),
                  notes=tuple(notes), registration_caveat=caveat)
