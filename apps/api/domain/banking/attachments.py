"""Re-export of `domain/attachments` — the rule is not bank-specific.

It was written for a bank transaction (migration 259) and `journal_entries`
has carried the same shape since migration 138, so the moment a second
subsystem needed it the module was in the wrong place: `models/accounting`
importing `domain.banking` to validate a manual journal's supporting documents
is the direction that ends in a cycle.

Kept as a re-export so `services/bank_batch_service` and the existing tests do
not have to move with it — the same shape `routers/fixed_assets.py` uses for
`domain/fixed_assets`.
"""
from domain.attachments import (  # noqa: F401
    ALLOWED_SCHEMES,
    MAX_ATTACHMENTS,
    MAX_NAME_LENGTH,
    MAX_URL_LENGTH,
    Attachment,
    AttachmentError,
    add,
    parse_attachment,
    parse_attachments,
    remove,
)

__all__ = [
    "ALLOWED_SCHEMES", "MAX_ATTACHMENTS", "MAX_NAME_LENGTH", "MAX_URL_LENGTH",
    "Attachment", "AttachmentError",
    "add", "parse_attachment", "parse_attachments", "remove",
]
