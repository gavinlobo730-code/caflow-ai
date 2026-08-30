"""Registry of filing-demo flows. See common.py for the rules every flow obeys.

One key per statutory filing the product prepares. A flow module exposes
build(db, firm_id, client_id, ref) -> envelope dict; a module that is not yet
built raises ValueError so the endpoint answers honestly instead of 500ing.
"""
from __future__ import annotations

from services.filing_demo import (
    common,
    esi,
    gstr1,
    gstr3b,
    gstr9,
    itr,
    mca,
    pf_ecr,
    tds_return,
)

# flow key → (builder, rbac resource whose `read` the caller must hold).
# The resource keeps a payroll-only user out of a GST demo and vice versa —
# the demo shows the module's real figures, so it is gated like the module.
FLOWS: dict = {
    "gstr1": (gstr1.build, "gst"),
    "gstr3b": (gstr3b.build, "gst"),
    "gstr9": (gstr9.build, "gst"),
    "tds": (tds_return.build, "tds"),
    "itr": (itr.build, "income_tax"),
    "pf": (pf_ecr.build, "payroll"),
    "esi": (esi.build, "payroll"),
    "mca": (mca.build, "mca"),
}
