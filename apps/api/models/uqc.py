"""
THE UQC LIST MOVED TO `domain/gst/uqc.py`, WHICH IS THE AUTHORITY.

This module held the official CBIC Unit Quantity Code list and had **zero
importers** — three validators cited `VALID_UQC_CODES` in their comments and
none of them imported it, so the one place that knew which codes exist was
unreachable from every place that asks.

It moved because the RULE over the list (what is wrong with a unit, and what
to tell the CA about it) belongs in a domain module, and a domain module must
not import from `models/`, which is the API boundary — the wrong direction and
one refactor from a cycle. Same reasoning that moved Schedule II Part C out of
`routers/fixed_assets.py`.

Re-exported here so any import still resolves, exactly as
`routers/fixed_assets.py` re-exports the Schedule II names. Prefer importing
from `domain.gst.uqc` in new code.
"""
from domain.gst.uqc import UQC_CODES, VALID_UQC_CODES  # noqa: F401
