"""What the TDS screen counts and totals over a client's register, decided once on the server (POST-A-276).

The screen used to read `tds_deductions`, `tds_challans`, `tds_returns` and `tds_certificates` itself and work these figures out
in the browser: the footer under the deductions table, the "Returns Due" and "Certificates Pending" cards, and the Not filed /
Filed / Overdue split of the Returns tab. Each was a rule about statuses and a due date, in a second language, over whatever rows
the browser happened to have paged in. They are asked here, over ALL of a client's rows and not over the window a list shows, so a
list that stops at a number cannot make a count shorter than the truth.

Pure: rows in, figures out. Integer paise throughout.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

#: A return in either of these has been filed. `tds_returns.status` is CHECKed to ('pending', 'prepared', 'ca_approved', 'filed',
#: 'revised') (migration 037), so every other value is a return still to be filed. There is no stored "overdue": a return is
#: overdue when it is not filed and its Rule 31A due date has passed (`return_counts`).
FILED_RETURN_STATUSES = frozenset({"filed", "revised"})

#: A certificate in either of these has not been issued yet (`tds_certificates.status` is CHECKed to ('pending', 'generated',
#: 'issued', 'downloaded'), migration 037).
PENDING_CERTIFICATE_STATUSES = frozenset({"pending", "generated"})


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def deduction_totals(rows: Iterable[dict]) -> dict:
    """The footer under the deductions table: how many deductions, and the gross amount and the tax column added up over ALL of them
    (the columns as stored, `payment_amount_paise` and `tds_paise`; surcharge and cess are not in the second, as they are not in
    the column the footer is labelled with)."""
    count = gross = tax = 0
    for row in rows:
        count += 1
        gross += _int(row.get("payment_amount_paise"))
        tax += _int(row.get("tds_paise"))
    return {"count": count, "payment_amount_paise": gross, "tds_paise": tax}


def is_filed(status: Optional[str]) -> bool:
    return str(status or "").strip().lower() in FILED_RETURN_STATUSES


def is_overdue(row: dict, today: date) -> bool:
    """A return that is not filed and whose due date has passed. `today` is the Indian day: a due date is a date in India. A return
    with no due date is never called overdue (an absent date is unknown, not a date in the past)."""
    due = str(row.get("due_date") or "")[:10]
    return (not is_filed(row.get("status"))) and bool(due) and due < today.isoformat()


def return_counts(rows: Iterable[dict], *, today: date) -> dict:
    """Not filed / Filed / Overdue over all of a client's returns. Overdue is a subset of Not filed, as it always was on the tab."""
    rows = list(rows)
    filed = sum(1 for r in rows if is_filed(r.get("status")))
    return {"not_filed": len(rows) - filed, "filed": filed, "overdue": sum(1 for r in rows if is_overdue(r, today)),
            "total": len(rows)}


def certificate_counts(rows: Iterable[dict]) -> dict:
    """Certificates still to be issued, out of all of a client's."""
    rows = list(rows)
    pending = sum(1 for r in rows if str(r.get("status") or "").strip().lower() in PENDING_CERTIFICATE_STATUSES)
    return {"pending": pending, "total": len(rows)}
