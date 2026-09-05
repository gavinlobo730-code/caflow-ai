"""
Why a customer or vendor cannot be permanently deleted — the statute, the date,
and the honest distinction between the two different reasons.

WHAT WAS WRONG

Both deletes refused with one sentence — "this customer has linked accounting
records and cannot be permanently deleted" — which names no law and no date, and
NEVER LAPSES. It would refuse identically in 2050, long after every statute had
released the record. From 13 May 2027 that is a standing failure to erase under
DPDP s. 8(7), and nobody reading it could tell whether the refusal was right.

TWO REASONS, AND THEY ARE NOT THE SAME REASON

The guard was doing two jobs under one sentence, and they come apart:

  RETENTION — the law requires the record kept. This one HAS AN END, and the end
  is computable from the financial year the record belongs to.

  REFERENTIAL — other rows point at this one. Customers' FKs are ON DELETE
  CASCADE, and two of the vendor tables carry a vendor_id with no FK at all, so
  a hard delete either destroys linked records silently or strands them pointing
  at a party that no longer exists.

Separating them is the point, because they expire differently: retention lapses
on a date, and the referential reason does not lapse at all while the documents
are still there.

WHY A LAPSED DUTY STILL DOES NOT PERMIT THE DELETE

This is the question #126 deliberately left open, and the answer is no.
Retention lapsing means "the law no longer REQUIRES you to keep this" — it does
not mean nothing else needs it. The invoices are still referenced by journal
entries, by GST returns already filed, and by the ageing schedules. Cascading
them away because a statute stopped compelling their retention would destroy
posted books to satisfy a request the law does not make.

So the refusal stands either way, and what changes is WHAT IT SAYS: before the
date, the statute is the reason; after it, the reason is referential and the
message says so, so a CA can see that the remaining obstacle is the books rather
than the law.
"""
from __future__ import annotations

from datetime import date

from domain.dpdp.retention import decision_for_record_date

#: The party's own word, for a sentence a CA reads.
CUSTOMER = "customer"
VENDOR = "vendor"


def _parse(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def refusal(
    party: str,
    *,
    latest_record_date: str | None,
    today: date | None = None,
) -> str:
    """The 409 detail for a permanent-delete refusal.

    `latest_record_date` is the newest DATED accounting record linked to the
    party; None means the only blockers are undated (a recurring template, an
    opening balance), which have no statutory clock.
    """
    parsed = _parse(latest_record_date)

    if parsed is None:
        # No dated record to anchor a duty to. Say the true reason rather than
        # invoking a statute whose period cannot be computed — an undated
        # blocker is a referential one.
        return (
            f"This {party} still has linked records that carry no accounting "
            f"date — a recurring template or an opening balance — so a "
            f"retention date cannot be computed for it. It cannot be "
            f"permanently deleted while they exist. Deactivate the {party} "
            f"instead to preserve history."
        )

    decision = decision_for_record_date("books_of_account", parsed, today=today)

    if decision.erasable:
        # Every statutory duty has lapsed. The delete is still refused, and the
        # message now says the reason is the books rather than the law.
        return (
            f"Statutory retention over this {party}'s records has lapsed — no "
            f"law now requires them kept. It still cannot be permanently "
            f"deleted: the invoices, receipts and notes linked to it are "
            f"referenced by posted journal entries and by returns already "
            f"filed, and deleting the {party} would cascade them away. "
            f"Deactivate the {party} instead to preserve history."
        )

    return (
        f"{decision.reason} Until then this {party} cannot be permanently "
        f"deleted — its records would cascade away with it. Deactivate the "
        f"{party} instead to preserve history."
    )
