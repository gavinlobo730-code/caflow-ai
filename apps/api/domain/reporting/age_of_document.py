"""How many days old a document is, for an ageing report, and what happens when its date cannot be read (POST-A-505).

An ageing report puts each open document in a bucket by the days since its due date (or its own date, where it has no due date). Three
places did that sum, each with the same fallback: a document whose stored date could not be read was aged ZERO days, which is the "current"
bucket, so an invoice or a bill the books could not date was reported as not yet due and the overdue total came out short. The date
columns are typed dates, so reaching the fallback means damage (a row written around the schema, a fixture, a migration gone wrong), and
damage is what a report must not paper over without a word.

So the fallback stays (a report must still print, and a document with no usable date has no better bucket than the first) and it now SAYS
SO: `capture_soft_failure` is called with the document's id and the text that did not parse, which is what lets somebody find the row.
A document with NO date at all (`None`, empty) is a different thing and is aged zero without a report, as it always was.
"""
from __future__ import annotations

from datetime import date, datetime

from core.observability import capture_soft_failure


def days_old(reference, today: date, *, operation: str, **context) -> int:
    """Days from `reference` to `today`: 0 for no date; 0 and a report for a date that cannot be read.

    `reference` is a date, a datetime or text whose first ten characters are an ISO date. `operation` names the report and must be
    unique to the caller; `context` carries what finds the row (a document id).
    """
    if not reference:
        return 0
    try:
        if isinstance(reference, datetime):
            day = reference.date()
        elif isinstance(reference, date):
            day = reference
        else:
            day = date.fromisoformat(str(reference)[:10])
        return (today - day).days
    except (TypeError, ValueError) as unreadable:
        capture_soft_failure(unreadable, operation=operation, reference=str(reference)[:40], **context)
        return 0
