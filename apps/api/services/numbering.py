"""
Document numbering with graceful retry (Beta hardening — Phase B).

Auto document numbers (SINV-/CN-/DN-/RCPT-/VPMT-) are derived from a per-(firm,
client,FY) count, which can race under concurrency. The DB UNIQUE constraint on the
number GUARANTEES no duplicates; without a retry, though, the loser of a race gets a
raw 500. insert_with_number converts that into a transparent retry: on a unique
violation it recomputes the sequence (which now sees the winner's committed row) and
tries again, so users never see a spurious failure and numbers stay unique + gap-free
in the common case.
"""
import logging
import uuid
from typing import Optional

_logger = logging.getLogger("caflow.numbering")


#: What an unattended process puts in `invoice_no` until a CA replaces it.
PLACEHOLDER_INVOICE_NO_PREFIX = "DRAFT-"


def is_placeholder_invoice_no(invoice_no: Optional[str]) -> bool:
    """True for a number `draft_placeholder_invoice_no` made, or one typed to look like it. Case-blind and
    whitespace-tolerant, because the point is that nobody issues one by accident."""
    return str(invoice_no or "").strip().upper().startswith(PLACEHOLDER_INVOICE_NO_PREFIX)


def draft_placeholder_invoice_no() -> str:
    """A unique, obviously-not-real invoice number for sales invoices created
    by an UNATTENDED process (recurring-invoice generation, billing-schedule
    generation) — no CA is present to type the real one.

    IT STAYS A PLACEHOLDER EVEN THOUGH THERE IS NOW A SERIES. Until 2026-09-12
    the reason was that sales numbering had no scheme at all; SALES-12 gave it
    one (`services/sales_numbering_service.py` reads the firm's own
    `invoice_settings` and suggests the next number). That does not make it
    right to spend a number here. An unattended draft may never be issued, and
    a number taken by a draft that is later deleted leaves a permanent gap in
    the middle of the series — max+1 never hands it out again, by design, see
    sequence_after below. A gap is a standard GSTR-1 scrutiny query, so the
    background job must not create one on the CA's behalf.

    So this is deliberately NOT a plausible-looking series — "DRAFT-" makes it
    obvious at a glance that the CA must replace it with the real number before
    Issue, and the suggestion the form offers at that moment comes from the
    firm's own series. Fits CGST Rule 46(b)'s 16-character cap exactly (6 + 10),
    and its character set: letters, digits and a hyphen.
    """
    return f"{PLACEHOLDER_INVOICE_NO_PREFIX}{uuid.uuid4().hex[:10].upper()}"


#: Every series `next_sequence` reads back: table -> (number column, the columns its UNIQUE
#: constraint covers besides the number itself). (Other numbers are found elsewhere: the sales
#: invoice and the reverse-charge document by their own series modules, per client; the fee
#: invoice by a database counter; the engagement letter and the proposal firm-wide.)
#:
#: The scope is not decoration. A sequence computed over a NARROWER scope than
#: the constraint hands the same number to two rows the database will not accept
#: — which is exactly the launch blocker migration 151 fixed for
#: client_sales_invoices and credit_notes, and migration 159 for debit_notes and
#: receipts: the firm's SECOND client computed 0001 (its own tally was 0), the
#: per-firm UNIQUE rejected it, and the retry below recomputed the same 0001 on
#: every attempt. Migration 210 then created sales_debit_notes and
#: purchase_credit_notes with the old per-firm key and per-client numbering, so
#: the same blocker was live again on those two until migration 350 widened them.
#:
#: next_sequence refuses a scope that is not exactly this one, so the mismatch
#: cannot be reintroduced silently a third time.
NUMBER_SERIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "credit_notes":          ("credit_note_no", ("firm_id", "client_id")),
    "debit_notes":           ("debit_note_no",  ("firm_id", "client_id")),
    "sales_debit_notes":     ("debit_note_no",  ("firm_id", "client_id")),
    "purchase_credit_notes": ("credit_note_no", ("firm_id", "client_id")),
    "receipts":              ("receipt_no",     ("firm_id", "client_id")),
    "purchase_payments":     ("payment_no",     ("firm_id",)),
    # Not a document number, but the same rule and a worse consequence: the
    # asset code is what FA-ACQ-/FA-CAP-/FA-DEPN-/FA-DISP- references are built
    # from, and the posting kernel dedupes on (client_id, reference_no,
    # entry_date). A reused code makes a new asset's acquisition journal land on
    # the old asset's entry. Migration 351 is the UNIQUE index behind it.
    "fixed_assets":          ("asset_code",     ("firm_id", "client_id")),
}

#: How many numbers to read back before taking the numeric maximum. One row
#: would be enough while every number in a series is zero-padded to the same
#: width (lexicographic order is then numeric order), which is true of every
#: series above — all are formatted "{prefix}{n:04d}". Reading a window instead
#: costs the same single round trip and survives a series that has picked up an
#: unpadded or wider number from an import or a hand-typed correction, where
#: "…-9" would otherwise sort above "…-0042" and win.
_SEQUENCE_WINDOW = 50


def sequence_after(existing, prefix: str) -> int:
    """The next number in a `{prefix}{n:04d}` series: one past the HIGHEST
    number already used, never one past the COUNT of them.

    Count+1 is what the five document routers and the two payment services did,
    and it is deterministic — so once a middle document is deleted it returns a
    number that is already taken, on every attempt, for the rest of the
    financial year. insert_with_number's retry cannot save that: it recomputes
    the SAME value six times. Max+1 both ends the wedge and is what makes the
    retry converge, because re-reading after a concurrent insert returns a
    number that has moved.

    A deletion in the MIDDLE of a series leaves a permanent gap: the maximum has
    not moved, so 0002 is never handed out a second time. That is the correct
    outcome and not a defect to close — the audit_log holds a create and a
    delete event for it. Deleting the HIGHEST document does free its number
    again, and that is also correct: every delete path in the product is
    draft-only, and a draft was never issued to anybody.
    """
    highest = 0
    for value in existing:
        text = str(value or "").strip()
        if not text.startswith(prefix):
            continue
        tail = text[len(prefix):]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return highest + 1


def is_firm_wide(table: str) -> bool:
    """True for a series whose UNIQUE scope does not include the client: one number line for the whole firm."""
    return "client_id" not in NUMBER_SERIES[table][1]


def _firm_wide_db(request_db):
    """The client a FIRM-WIDE series is read with: every row of the firm, not the caller's.

    A series numbered per (firm, client) is read by someone who has that client's access, so their own view of it is the
    whole series. A series numbered for the FIRM (the vendor payment, today) is not: the table is assignment-scoped, so a
    Manager assigned to client A reads only A's payments (and none of the practice's own internal client, which only a
    Partner reads), the newest they can see is not the newest of the firm, and the next number can be one another client's
    payment already holds. The insert then fails on the firm-wide unique key and
    fails again on every retry, because their own maximum never passes the hidden numbers (the letter number of migration
    529 again). The read returns a number and nothing else, the scope carries the firm, and the caller has been
    authorised by the route, so it uses the privileged client. Without one (mock mode, a test double) the caller's own is
    all there is."""
    if not request_db:
        return request_db
    from core import db_provider
    return db_provider.service_db_or_none() or request_db


def next_sequence(db, table: str, prefix: str, **scope) -> int:
    """Read back the highest number in `table`'s series and return the next one.

    `scope` must name exactly the columns NUMBER_SERIES records for the table —
    the ones its UNIQUE constraint covers. Passing fewer produces numbers the
    database will reject; passing more silently narrows the series.

    A series that is numbered for the whole firm is read with `_firm_wide_db`, whatever client the caller passed.

    A read that fails RAISES. The previous `except Exception: return 1` turned a
    transient PostgREST failure into the number 1, which is either a collision
    with the live first document or, on a table without the constraint, a second
    document carrying a number that is already in the books.
    """
    number_field, expected = NUMBER_SERIES[table]
    if tuple(sorted(scope)) != tuple(sorted(expected)):
        raise ValueError(
            f"{table} is numbered per {expected}; got {tuple(sorted(scope))}. "
            "The sequence scope must match the UNIQUE constraint exactly.")
    if is_firm_wide(table):
        db = _firm_wide_db(db)
    query = db.table(table).select(number_field)
    for column, value in scope.items():
        query = query.eq(column, value)
    rows = (
        query.like(number_field, f"{prefix}%")
        .order(number_field, desc=True)
        .limit(_SEQUENCE_WINDOW)
        .execute()
    ).data or []
    return sequence_after((r.get(number_field) for r in rows), prefix)


def is_unique_violation(err: Exception) -> bool:
    """True when `err` is a Postgres unique-constraint violation (23505) —
    shared with routers that translate a raw DB collision into a friendly,
    user-facing duplicate message (e.g. a manually-typed duplicate invoice
    number) instead of a generic 500."""
    s = str(err).lower()
    return "23505" in s or "duplicate key" in s or "already exists" in s


def insert_with_number(db, table, base_payload, number_field, format_number, next_seq,
                       attempts: int = 6):
    """Insert base_payload with an auto-generated document number, retrying on a
    unique-number collision. Returns the inserted row (dict).

    Args:
      base_payload:  the row WITHOUT the number field.
      number_field:  e.g. "invoice_no".
      format_number: seq:int -> str (e.g. lambda s: f"SINV-{fy}-{s:04d}").
      next_seq:      callable returning the next sequence int (recomputed each attempt).
    """
    last: Exception | None = None
    for attempt in range(attempts):
        payload = {**base_payload, number_field: format_number(next_seq())}
        try:
            resp = db.table(table).insert(payload).execute()
            return (resp.data or [payload])[0]
        except Exception as e:            # noqa: BLE001
            last = e
            if is_unique_violation(e) and attempt < attempts - 1:
                _logger.warning("numbering collision on %s (attempt %d) — retrying", table, attempt + 1)
                continue
            raise
    raise last  # pragma: no cover


def insert_numbered_document_with_lines(
    db, header_table, base_payload, number_field, format_number, next_seq,
    lines_table, lines, lines_fk_column, attempts: int = 6,
):
    """Same retry-on-collision contract as insert_with_number, but for a
    numbered header with child line rows (debit/credit notes) — header and
    lines are inserted atomically per attempt via the numbered_document_atomic
    RPC (migration 167), so a lines-insert failure can never leave an
    orphaned header the way two separate unguarded inserts could (R3.11).

    Args:
      lines:            list of dicts, WITHOUT the header FK column (this
                         function attaches it from the header attempt's id).
      lines_fk_column:  e.g. "debit_note_id".
    """
    last: Exception | None = None
    for attempt in range(attempts):
        payload = {**base_payload, number_field: format_number(next_seq())}
        try:
            resp = db.rpc("numbered_document_atomic", {
                "p_header_table": header_table, "p_header": payload,
                "p_lines_table": lines_table, "p_lines": lines,
                "p_lines_fk_column": lines_fk_column,
            }).execute()
            return resp.data
        except Exception as e:            # noqa: BLE001
            last = e
            if is_unique_violation(e) and attempt < attempts - 1:
                _logger.warning("numbering collision on %s (attempt %d) — retrying", header_table, attempt + 1)
                continue
            raise
    raise last  # pragma: no cover
