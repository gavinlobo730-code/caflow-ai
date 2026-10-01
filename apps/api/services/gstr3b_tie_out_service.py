"""
Read the filed GSTR-1 and tie the GSTR-3B build out against it (GST-07).

`domain/gst/gstr1_3b_tie_out.py` is the rule and the reasoning. This module is
the reads that feed it, and it is called FROM `gst_return_service.gstr3b_from_books`
with the figures that build has already computed — it fetches nothing the build
holds, and it re-derives nothing.

WHAT IT READS
    * ONE `gstr1_returns` row — the registration's own, for this period — through
      `gst_exception_service.filed_gstr1`, the same read, by the same key, the
      Amendments tab uses. A GSTIN is required; migration 390 keyed that table
      on (client, period, gstin), and a read on (client, period) alone would
      compare the books against another registration's return.
    * ONE `gstr3b_returns` row, for whether the period's GSTR-3B is filed —
      because GSTR-1A closes the moment it is, so the advice differs.
    * Only where the two disagree: the GSTR-1 rebuilt from the books, to say WHY.
      That is the expensive read, so a tied return never pays for it.

IT NEVER BREAKS THE 3B BUILD. This is a cross-check beside a return, and a
failure to read the filed GSTR-1 must not stop a CA preparing the 3B. It is
REPORTED, through `capture_soft_failure` and as `status: "unavailable"` — a nil
tie-out that means "could not look" must not read as "nothing differs".

# CA REVIEW REQUIRED — this reports a difference. It adjusts neither return and
# files nothing.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from core.observability import capture_soft_failure
from domain.gst import gstr1_3b_tie_out as tie
from services import gst_exception_service as exceptions

_logger = logging.getLogger("caflow.gstr3b_tie_out")

NOT_FILED = "not_filed"
PAYLOAD_MISSING = "payload_missing"
OK = "ok"
UNAVAILABLE = "unavailable"

#: How many named documents a cause carries. The totals are over ALL of them;
#: only the list is cut, and `*_count` says how many there were.
MAX_DOCUMENTS = 25


def _gstr3b_filed(db, firm_id: str, client_id: str, period: str,
                  gstin: str) -> Optional[bool]:
    """Is this registration's GSTR-3B for the period recorded as filed?

    True / False where a row exists, and None where none does — a CA may have
    filed on the portal and not recorded it, so "no row" is NOT "not filed".
    """
    rows = (db.table("gstr3b_returns").select("id, status")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("period", period).eq("gstin", gstin)
            .limit(1).execute().data) or []
    if not rows:
        return None
    return str(rows[0].get("status") or "").lower() == "submitted"


def _cut(rows: list) -> dict:
    return {"count": len(rows), "documents": rows[:MAX_DOCUMENTS],
            "truncated": len(rows) > MAX_DOCUMENTS}


def build(db, firm_id: str, client_id: str, gstin: str, *, window: Any,
          result: Any, sales: list,
          registration_caveat: Optional[str]) -> dict:
    """The tie-out block for one GSTR-3B build. See the domain module.

    `window` is the `return_period.Window` the build resolved (key, start,
    frequency) and `result` its `GSTR3BResult`; `sales` is the list of
    `SalesTransaction`s the outward side was computed from, which is where the
    supplies no GSTR-1 can carry are named.
    """
    base = {
        "period": window.key,
        "gstin": gstin,
        "portal_locks_outward_tables": tie.locks_outward(window.start),
        "registration_caveat": registration_caveat,
        "verified": tie.VERIFIED,
        "ca_review_required": True,   # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    }
    try:
        return _build(db, firm_id, client_id, gstin, window=window,
                      result=result, sales=sales, base=base)
    except Exception as exc:                                    # noqa: BLE001
        capture_soft_failure(exc, operation="gstr3b.gstr1_tie_out",
                             firm_id=firm_id, client_id=client_id)
        return {**base, "status": UNAVAILABLE,
                "message": ("The filed GSTR-1 could not be read, so this "
                            "GSTR-3B has NOT been checked against it. That is "
                            "not the same as the two agreeing."),
                "gaps": [tie.NOT_HELD]}


def _build(db, firm_id: str, client_id: str, gstin: str, *, window: Any,
           result: Any, sales: list, base: dict) -> dict:
    filed_row = exceptions.filed_gstr1(db, firm_id, client_id, window.key, gstin)

    # NOT FILED IS AN ANSWER AND NOT A ZERO. A period with no GSTR-1 on record,
    # or only a draft, has nothing for the portal to fill Table 3.1 from — so
    # there is no filed figure to be equal or unequal to, and reporting "no
    # difference" would be the false clean result this block exists to prevent.
    if not filed_row or filed_row.get("status") != exceptions.SUBMITTED:
        return {**base, "status": NOT_FILED, "message": tie.NOT_FILED,
                "draft_exists": bool(filed_row),
                "gaps": [tie.NOT_HELD]}

    common = {**base,
              "filed_at": filed_row.get("submitted_at"),
              "arn": filed_row.get("arn")}
    filed_payload = filed_row.get("payload_json")
    if not filed_payload:
        return {**common, "status": PAYLOAD_MISSING,
                "message": tie.PAYLOAD_MISSING, "gaps": [tie.NOT_HELD]}

    filed = tie.read_gstr1_outward(filed_payload)
    books_3b = tie.read_gstr3b_outward(result)
    comparison = tie.compare(filed, books_3b)

    gaps: list[str] = [tie.NOT_HELD]
    if window.is_quarter:
        gaps.append(
            "A quarterly (QRMP) registration may also have furnished an IFF "
            "for the first two months; it is not held, and the portal fills "
            "Table 3.1 from it too.")
    if filed.amendment_sections:
        gaps.append(
            "The filed GSTR-1 also carries amendments ("
            + ", ".join(filed.amendment_sections)
            + "), which correct EARLIER periods. The portal nets them into "
              "Table 3.1; this comparison does not, so a difference that "
              "equals an amendment is not a missing invoice.")
    held_out = filed.held_out_reverse_charge
    if any(held_out.values()):
        gaps.append(
            "The filed GSTR-1 declares outward supplies on which the "
            "RECIPIENT pays the tax. They are left out of both sides here — "
            "this product's 3B does not declare them in 3.1(a) and whether "
            "the portal does could not be confirmed — and are shown in "
            "`held_out`.")
    if registration_note := base.get("registration_caveat"):
        gaps.append(registration_note)

    out = {**common, "status": OK, "tied": comparison["tied"],
           "rows": comparison["rows"], "held_out": dict(held_out),
           "filed_amendment_sections": list(filed.amendment_sections),
           "gaps": gaps}
    if comparison["tied"]:
        out["message"] = ("The books-built GSTR-3B's outward figures equal the "
                          "filed GSTR-1's, to the paisa.")
        return out

    # ── Why — only now, because this is the expensive part ─────────────────
    books_only = tie.books_only_figures(sales)
    gstr3b_filed = _gstr3b_filed(db, firm_id, client_id, window.key, gstin)
    books_return: dict = {}
    report: Optional[dict] = None
    try:
        books_return, report = exceptions.drift_since_filing(
            db, firm_id, client_id, window.key, gstin, filed_payload,
            frequency=window.frequency)
    except Exception as exc:                                    # noqa: BLE001
        capture_soft_failure(exc, operation="gstr3b.gstr1_tie_out.drift",
                             firm_id=firm_id, client_id=client_id)
        gaps.append("The GSTR-1 could not be rebuilt from the books, so the "
                    "difference is shown with no attribution.")
    books_now = (tie.read_gstr1_outward(books_return.get("payload"))
                 if books_return else None)
    split = tie.attribute(
        filed=filed, books_3b=books_3b, books_only=books_only,
        books_now=books_now, exception_report=report,
        books_gstr1_gaps=books_return.get("payload_gaps") if books_return else None)

    drift_docs = split["drift_documents"]
    causes = []
    if books_now is not None:
        causes.append({
            "kind": "documents_changed_since_filing",
            "label": ("Documents raised, edited or cancelled after the GSTR-1 "
                      "was filed"),
            "figures_paise": split["drift"],
            **{k: _cut(v) for k, v in drift_docs.items()},
        })
    if any(split["books_only"].values()):
        causes.append({
            "kind": "supplies_no_gstr1_can_carry",
            "label": ("Bank receipts marked as carrying GST and asset "
                      "disposals — real output tax with no tax invoice, so in "
                      "no GSTR-1"),
            "figures_paise": split["books_only"],
            "consequence": ("The portal's Table 3.1 will not show these, "
                            "because it is filled from GSTR-1."),
        })
    if any(split["remainder"].values()):
        causes.append({
            "kind": "the_two_builders_disagree",
            "label": ("The GSTR-1 and GSTR-3B builds classify some documents "
                      "differently, so even today's books do not give the "
                      "same figures on both"),
            "figures_paise": split["remainder"],
            "documents_the_gstr1_could_not_carry": split["held_out_of_gstr1"],
        })
    out.update({
        "gstr3b_filed": gstr3b_filed,
        "difference": {k: v["difference"]
                       for k, v in comparison["rows"][0]["figures"].items()},
        "attribution": split,
        "causes": causes,
        "route": tie.routes_for(
            portal_locks_outward=base["portal_locks_outward_tables"],
            gstr3b_filed=gstr3b_filed, drift_documents=drift_docs),
        "message": ("The books-built GSTR-3B's outward figures differ from the "
                    "filed GSTR-1's. Neither return has been changed."),
    })
    return out
