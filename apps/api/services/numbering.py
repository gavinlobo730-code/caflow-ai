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

_logger = logging.getLogger("caflow.numbering")


def _is_unique_violation(err: Exception) -> bool:
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
            if _is_unique_violation(e) and attempt < attempts - 1:
                _logger.warning("numbering collision on %s (attempt %d) — retrying", table, attempt + 1)
                continue
            raise
    raise last  # pragma: no cover
