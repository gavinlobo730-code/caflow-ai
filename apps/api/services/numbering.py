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

_logger = logging.getLogger("caflow.numbering")


def draft_placeholder_invoice_no() -> str:
    """A unique, obviously-not-real invoice number for sales invoices created
    by an UNATTENDED process (recurring-invoice generation, billing-schedule
    generation) — no CA is present to type the real one. Sales invoice
    numbering is otherwise fully manual (Decision: no Caflow-generated
    scheme; see routers/sales_invoices.py), so this is deliberately NOT a
    plausible-looking series — "DRAFT-" makes it obvious at a glance that the
    CA must replace it with the client's real invoice number before Issue.
    Fits CGST Rule 46(b)'s 16-character cap exactly (6 + 10).
    """
    return f"DRAFT-{uuid.uuid4().hex[:10].upper()}"


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
