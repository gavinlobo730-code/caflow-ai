"""The filing season's pipeline for income-tax returns, as one pure rule (POST-A-068): which stage a client's return is at, and whether a
saved computation can be run again.

WHAT IT IS NOT. The product records a return's status (`itr_filings.status`: draft, review, partner_review, ready_for_filing, filed, where
`filed` means the CA recorded the portal's acknowledgement) and, separately, a saved computation (`tax_computation_snapshots`: draft or
reviewed). It records NOTHING about documents received from the client and nothing about e-verification, so those two steps of a season
are not stages here and the list says so (`NOT_TRACKED`): a stage the data cannot answer is named, never drawn as a count of zero.

A STAGE IS A READING OF THE RECORDS, NEVER A CLAIM. `not_started` is the absence of both a return record and a saved computation for the
year; it does not say nothing has been done outside the product. Nothing here moves a return from one status to another: that is a
person's act on the return (`itr_workflow.transition_itr_status`), and the bulk run saves a draft computation and goes no further.
"""
from __future__ import annotations

from typing import Optional

#: In pipeline order. `computed` is a saved computation with no return record yet; the rest are the return's own status.
STAGES: tuple[str, ...] = ("not_started", "computed", "draft", "review", "partner_review", "ready_for_filing", "filed")

STAGE_LABELS: dict[str, str] = {
    "not_started": "Not started",
    "computed": "Computed, no return yet",
    "draft": "Return drafted",
    "review": "In review",
    "partner_review": "With the partner",
    "ready_for_filing": "Ready for filing",
    "filed": "Filed (acknowledgement recorded)",
}

#: What a season has that the records cannot answer. Said beside the list, so a missing step is not read as an empty one.
NOT_TRACKED: tuple[str, ...] = (
    "Whether the client's documents have been received: nothing records it.",
    "Whether a filed return has been e-verified, and how long ago it was filed: nothing records it.",
)

#: Most clients one bulk run takes, so a request finishes in one go and a refusal is a sentence, not a timeout.
MAX_BULK_CLIENTS = 100


def stage_of(filing: Optional[dict], snapshot: Optional[dict]) -> str:
    """The stage of a client's return for one year, from the latest return record and the latest saved computation (either may be None)."""
    if filing:
        status = str(filing.get("status") or "")
        return status if status in STAGES and status not in ("not_started", "computed") else "draft"
    return "computed" if snapshot else "not_started"


def latest_by_client(rows: list[dict], order_key: str) -> dict[str, dict]:
    """The newest row per client by `order_key` (a stamp or a version), ties broken by id so the same rows give the same answer."""
    out: dict[str, dict] = {}
    for r in rows:
        cid = str(r.get("client_id") or "")
        if not cid:
            continue
        rank = (r.get(order_key) is not None, r.get(order_key) or "", str(r.get("id") or ""))
        have = out.get(cid)
        if have is None or rank > (have.get(order_key) is not None, have.get(order_key) or "", str(have.get("id") or "")):
            out[cid] = r
    return out


def inputs_of(snapshot: dict) -> Optional[dict]:
    """The inputs a saved computation was made from, or None for one saved before the inputs were kept with it."""
    computation = snapshot.get("computation_json")
    if not isinstance(computation, dict):
        return None
    inputs = computation.get("inputs")
    return inputs if isinstance(inputs, dict) and inputs else None


def same_answer(old: dict, new: dict) -> bool:
    """Whether a re-run came to the figures the saved computation already holds (taxable income, total tax, net payable, the regime
    applied). It decides only whether another version is worth saving."""
    def pick(c: dict) -> tuple:
        return (
            (c.get("regime")),
            (c.get("income") or {}).get("taxable_income_paise"),
            (c.get("tax") or {}).get("total_tax_paise"),
            (c.get("payable") or {}).get("net_payable_paise"),
        )
    return isinstance(old, dict) and isinstance(new, dict) and pick(old) == pick(new) and None not in pick(old)
