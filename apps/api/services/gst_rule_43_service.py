"""CGST Rule 43 — the capital-goods common-credit working for one tax period.

WHAT IT ANSWERS

    Te: the amount a client making both taxable and exempt supplies must add
    back to output tax this month, because one-sixtieth of the credit on each
    common capital good is attributable to the exempt part of the turnover.

    The statutory arithmetic is `domain/gst/rule_43.py` and nothing here
    duplicates it. This module's whole job is to fetch the two inputs the rule
    needs and hand them over:

      * the client's CAPITAL GOODS, from `fixed_assets` — its tax split
        (migration 343), whether the credit was taken (`itc_eligible`, 343)
        and which of Rule 43(1)'s three uses it is put to (`rule_43_use`,
        migration 372);
      * E and F, from `gst_return_service.outward_turnover`, which reads the
        same documents through the same computer that builds GSTR-3B Table
        3.1. A Rule 43 working and the return it belongs to cannot disagree
        about what was supplied.

WHAT IT DOES NOT DO: post anything, and declare anything.

    Giving credit back is a real movement — a credit to GST Input — and this
    codebase has one posting kernel. So the CA raises the journal and then
    classifies it through `itc_register_service.record_reversal` with
    reason_code 'rule_43', which is a ground that register has always
    accepted and that nothing could previously produce a figure for. That is
    what puts it in GSTR-3B Table 4(B)(1).

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. This computes a working. It
    # writes nothing, posts nothing and files nothing.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from core.db_paging import fetch_all
from domain.gst import rule_43

_logger = logging.getLogger("caflow.gst.rule_43")

class Rule43Error(Exception):
    """The working cannot be built at all."""


def _period_start(period: str) -> date:
    """'MMYYYY' → the first day of that month.

    The same 'MMYYYY' spelling every GST endpoint in this codebase uses. Rule
    43 counts its sixty instalments from the month of the invoice, so the
    first of the month is what the count is taken against — see
    `domain.gst.rule_43.period_index`.
    """
    if len(period) != 6 or not period.isdigit():
        raise Rule43Error("period must be MMYYYY")
    mm, yyyy = int(period[:2]), int(period[2:])
    if not 1 <= mm <= 12:
        raise Rule43Error("period month must be 01-12")
    return date(yyyy, mm, 1)


def _capital_goods(db, firm_id: str, client_id: str) -> list:
    """Every live asset of the client, oldest first.

    EVERY asset, not only the ones marked common. An asset outside its five
    years, one used exclusively for taxable supplies and one nobody has
    classified are three different answers, and the CA needs to see all three
    — an asset silently absent from a working reads as an asset with nothing
    to reverse.
    """
    # The projection is a LITERAL, not a constant: tests/_backend_query_parser
    # reads `.select("…")` with ast and cannot follow a name, so a constant
    # here would put this query in the unreadable budget and stop
    # test_backend_columns_exist_pg from checking `rule_43_use` — the newest
    # column in the query and the one most worth checking — against the real
    # schema. `id` is in it because fetch_all keysets on it: a paged query
    # whose select omits its cursor column works perfectly until the
    # thousandth row and then cannot advance.
    rows = fetch_all(
        lambda: (db.table("fixed_assets")
                 .select("id, asset_name, asset_code, purchase_date, "
                         "igst_paise, cgst_paise, sgst_paise, itc_eligible, "
                         "rule_43_use")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .is_("deleted_at", "null")),
        label="rule_43.fixed_assets")
    goods = []
    for r in rows:
        raw = r.get("purchase_date")
        try:
            inv = date.fromisoformat(str(raw)[:10]) if raw else None
        except ValueError:
            inv = None
        goods.append(rule_43.CapitalGood(
            asset_id=str(r.get("id")),
            asset_name=str(r.get("asset_name") or r.get("asset_code") or r.get("id")),
            invoice_date=inv,
            igst_paise=int(r.get("igst_paise") or 0),
            cgst_paise=int(r.get("cgst_paise") or 0),
            sgst_paise=int(r.get("sgst_paise") or 0),
            itc_eligible=r.get("itc_eligible"),
            use=r.get("rule_43_use"),
        ))
    # Oldest first, so a reader sees the instalments running out in order.
    # `fetch_all` imposes its own ORDER BY id, so any ordering the caller wants
    # is applied to the rows it got BACK — never inside the paged query. The
    # key is coalesced because `purchase_date` is nullable and comparing None
    # to a date raises TypeError in Python where Postgres sorted it happily.
    goods.sort(key=lambda g: (g.invoice_date or date.min, g.asset_name))
    return goods


def for_period(db, firm_id: str, client_id: str, period: str,
               *, turnover: Optional[dict] = None) -> dict:
    """The Rule 43 working for one tax period.

    `turnover` overrides the computed E and F, and exists for the proviso to
    Rule 43(1)(g): where the turnover of a period is nil or not available, E
    and F are taken from "the last tax period for which the details of such
    turnover are available". Those are a DIFFERENT period's figures and are
    never substituted automatically — the engine refuses and says so, and a CA
    who has looked the earlier period up passes them here deliberately.
    """
    period_start = _period_start(period)

    if turnover is not None:
        t = rule_43.Turnover(
            exempt_paise=int(turnover.get("exempt_paise") or 0),
            total_paise=int(turnover.get("total_paise") or 0))
        turnover_source = "supplied by the caller"
        breakdown = None
        turnover_caveats: list = []
    else:
        import services.gst_return_service as gst_return_service
        # NO FILING FREQUENCY, DELIBERATELY, AND THIS IS AN OPEN QUESTION
        # RATHER THAN AN OVERSIGHT (GST-11). `outward_turnover` can now read a
        # QRMP quarter, and Rule 43(1)(c) reverses Tm = Tc ÷ 60 per TAX PERIOD
        # — whether a quarterly filer's tax period for that fraction is the
        # quarter or still each month was not confirmable here, and reading it
        # as a quarter would silently triple E and F against a one-sixtieth
        # that did not move. So this stays the month it has always been, and
        # `rule_43.compute` keeps its own `period` semantics.
        book = gst_return_service.outward_turnover(db, firm_id, client_id, period)
        t = rule_43.Turnover(exempt_paise=int(book["exempt_paise"]),
                             total_paise=int(book["total_paise"]))
        turnover_source = "this period's posted outward supplies"
        breakdown = book["breakdown"]
        turnover_caveats = list(book.get("caveats") or [])

    result = rule_43.compute(
        _capital_goods(db, firm_id, client_id),
        period=period, period_start=period_start, turnover=t)

    out = result.to_dict()
    # A caveat about how E and F were MEASURED belongs on the answer they
    # produced, not in a log nobody reads.
    out["caveats"] = list(out["caveats"]) + turnover_caveats
    out["turnover_source"] = turnover_source
    out["turnover_breakdown"] = breakdown
    # WHAT TO DO WITH THE ANSWER. A figure with no route onto a return is the
    # defect this finding is about, so the working says which one it takes.
    out["how_to_declare"] = (
        "Rule 43(1)(h) adds Te to the output tax liability. In this product "
        "that is a manual journal crediting GST Input, registered through the "
        "ITC reversal register with ground 'rule_43' — a permanent reversal, "
        "so GSTR-3B Table 4(B)(1). Nothing here posts or declares it."
    )
    out["ca_review_required"] = True
    return out
