"""
FORM GST ITC-04 — goods sent to a job worker and received back (GST-30).

WHAT WAS MISSING

    `delivery_challan.py` has tracked job-work challans, and the CGST §143 clock
    on them, since migration 392 — and named ITC-04 without building it: its
    `itc_04_period` returns a refusal and a pair of sentences. A manufacturer
    client who sends material out for job work therefore had the challans
    entered and the statement Rule 45(3) requires the principal to furnish typed
    out again by hand from them.

    A SECOND GAP SAT UNDERNEATH THE FIRST. A challan recorded ONE fact about the
    goods coming back — `received_back_on`, a single date for the whole challan.
    Job work is routinely returned in lots, and the ITC-04 form itself is built
    around that (a row per return, against the original challan), so "one
    challan sent, part returned" could not be recorded at all. Migration 462
    adds the returns; this module reads them.

WHAT THIS DOES

    It derives, from challans already entered, the rows the statement asks for
    and what is still with the job worker, and shows what the §143 clock says
    about the BALANCE. It reports. Nothing is filed and nothing is posted —
    ITC-04 is furnished on the GST portal by the principal.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.

        Table 4   goods sent to a job worker: one row per challan line
        Table 5A  goods received back from a job worker: one row per return
        balance   per challan line: sent, returned, still outstanding, and the
                  s.143 date the outstanding part is running towards

WHICH PERIOD IS NOT DECIDED, AND THAT IS THE POINT OF `windows_for`

    Rule 45(3)'s periodicity turns on the principal's own aggregate turnover in
    the preceding financial year and on a limit this environment could not
    confirm — `delivery_challan.ITC_04_REFUSAL` says why. So the module does
    NOT pick a cadence. `windows_for` lays out the windows of EVERY reading the
    repository holds — quarterly (the 2017 text), half-yearly and annual — each
    with its own due date, and the CA opens the one that applies. A turnover
    recorded on `client_gst_turnover` is shown beside them as CONTEXT; the limit
    that would turn it into an answer is the one thing still not held.

⚠️  GRADING. The form's table numbers and column names, the three cadences and
    their due dates are `[S]` — written from knowledge, because every `.gov.in`
    is refused at this environment's proxy — and `VERIFIED` is False.
    `tests/test_itc_04_is_derived_from_the_challans_already_entered.py` pins
    each so a later correction is deliberate. The arithmetic is not `[S]`.

WHAT IS REFUSED, AND NAMED ON THE ANSWER
    * Which cadence applies (above).
    * Tables 5B (goods sent from one job worker to another) and 5C (goods
      supplied from a job worker's premises): this product records neither
      movement. A nil there would declare that none happened.
    * Moulds, dies, jigs, fixtures and tools. §143(1)'s second proviso puts them
      outside both periods; the form's own two types of goods do not name them,
      so which the CA reports them as is not guessed here.
    * Whether goods lost or wasted count as "received back" for §143. They are
      recorded, shown and NEVER subtracted from the balance — the larger balance
      is the direction that cannot hide a deemed supply.
    * The TAX on a deemed supply. §143(3) fixes the DAY it is deemed made; its
      value is a §15 / Rule 28 question this product does not answer. The
      challan's taxable value is shown as the figure at stake, not as the value
      of the supply.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Iterable, Optional

from domain.gst import delivery_challan as dc
from domain.gst import uqc as _uqc

#: Everything about the FORM and its cadences is written from knowledge.
VERIFIED = False

#: The two job-work statuses a challan can be in once it has actually left.
#: A draft has not been issued and a cancelled one never moved goods.
SENT_STATUSES = ("issued", "received_back")

QUARTERLY = "quarterly"
HALF_YEARLY = "half_yearly"
ANNUAL = "annual"

#: The readings, in the order they are shown. Half-yearly and annual are the two
#: `delivery_challan.ITC_04_READINGS` already holds. Quarterly is the cadence of
#: Rule 45(3)'s 2017 text and is shown because a statement for a period under it
#: is still furnished on it — the fork shape, and the PERIOD decides which
#: reading applies, which is why none is chosen here. `[S]`.
CADENCES = (
    (QUARTERLY, "Quarterly — the 2017 text of Rule 45(3)"),
    (HALF_YEARLY, "Half-yearly — where the preceding year's turnover is above the limit"),
    (ANNUAL, "Annually — where it is at or below the limit"),
)

#: The form's tables, named as the CA reads them. `[S]`.
TABLE_4 = "Table 4 — goods sent to a job worker"
TABLE_5A = "Table 5A — goods received back from a job worker"

TABLE_5B_NOT_DERIVED = (
    "Table 5B (goods sent from one job worker to another) is not derived: this "
    "product records a movement between job workers nowhere, so a nil here "
    "would declare that none happened."
)
TABLE_5C_NOT_DERIVED = (
    "Table 5C (goods supplied from a job worker's premises) is not derived: a "
    "supply made from the job worker's premises is recorded nowhere here, and a "
    "nil would declare that none was made."
)
FORM_NUMBERING = (
    "The form's table numbers and column names are written from knowledge and "
    "were not read off the notified form, which could not be reached from this "
    "environment. Check them against the utility before keying anything."
)
WASTE_IS_NOT_SUBTRACTED = (
    "Losses and wastes are recorded and shown, but are NOT subtracted from what "
    "is outstanding. Whether scrap counts as 'received back' for CGST s.143 is a "
    "judgement this product does not take, and the larger balance is the "
    "direction that cannot hide a deemed supply."
)
TAX_ON_DEEMED_SUPPLY_NOT_COMPUTED = (
    "The tax on a deemed supply is not computed. s.143(3) fixes the DAY it is "
    "deemed made; its value is a s.15 and Rule 28 question. The challan's "
    "taxable value is shown as the figure at stake, rounded UP, and is not the "
    "value of the supply."
)
MOULDS_NOT_NAMED_BY_THE_FORM = (
    "Moulds, dies, jigs, fixtures and tools are outside CGST s.143's one-year "
    "and three-year periods (second proviso to s.143(1)), and the form's two "
    "types of goods do not name them. Which type the CA reports them as is not "
    "guessed here."
)
NOTHING_IS_FILED = (
    "ITC-04 is furnished on the GST portal by the principal. This reports the "
    "figures from the challans entered; it files nothing and posts nothing."
)


def _d(value) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _iso(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _qty(value: Decimal) -> str:
    """A quantity as the column keeps it — three decimals, as TEXT, never a
    float: a quantity turned into one is how a register stops footing."""
    return f"{value:.3f}"


# ── The windows ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Window:
    cadence: str
    key: str
    label: str
    start: str
    end: str
    due_date: str

    def as_dict(self) -> dict:
        return {"cadence": self.cadence, "key": self.key, "label": self.label,
                "start": self.start, "end": self.end, "due_date": self.due_date}

    def contains(self, day: Optional[str]) -> bool:
        return bool(day) and self.start <= str(day)[:10] <= self.end


def _due_after(end: str) -> str:
    """The 25th of the month AFTER the window's last month. `[S]`.

    One rule for all three readings: the half-year ending 30 September is due on
    25 October, the one ending 31 March on 25 April, the year on 25 April, and
    each quarter on the 25th after it closes (25 Jul, 25 Oct, 25 Jan, 25 Apr).
    """
    y, m = int(end[:4]), int(end[5:7])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y:04d}-{m:02d}-25"


def windows_for(financial_year: str) -> dict[str, list[Window]]:
    """Every window of every reading for one financial year, none chosen."""
    from core.ist_clock import fy_bounds, fy_quarters
    start, end = fy_bounds(financial_year)
    quarters = fy_quarters(financial_year)
    out: dict[str, list[Window]] = {
        QUARTERLY: [Window(QUARTERLY, f"{financial_year}:{q}", f"{q} {financial_year}",
                           s, e, _due_after(e)) for q, s, e in quarters],
        HALF_YEARLY: [],
        ANNUAL: [Window(ANNUAL, f"{financial_year}:FY", f"FY {financial_year}",
                        start, end, _due_after(end))],
    }
    # A half-year is two whole quarters, so its bounds are read off the quarters
    # rather than restating September.
    out[HALF_YEARLY] = [
        Window(HALF_YEARLY, f"{financial_year}:H1", f"April to September {financial_year}",
               quarters[0][1], quarters[1][2], _due_after(quarters[1][2])),
        Window(HALF_YEARLY, f"{financial_year}:H2", f"October to March {financial_year}",
               quarters[2][1], quarters[3][2], _due_after(quarters[3][2])),
    ]
    return out


def find_window(financial_year: str, key: str) -> Optional[Window]:
    for ws in windows_for(financial_year).values():
        for w in ws:
            if w.key == key:
                return w
    return None


# ── Reading a challan ────────────────────────────────────────────────────────

def is_job_work_sent(ch: dict) -> bool:
    return (str(ch.get("reason")) == dc.REASON_JOB_WORK
            and str(ch.get("status")) in SENT_STATUSES)


def _job_worker(ch: dict) -> dict:
    gstin = (ch.get("consignee_gstin") or "").strip().upper() or None
    state = (ch.get("place_of_supply") or "").strip() or (gstin[:2] if gstin else None)
    return {"name": ch.get("consignee_name"), "gstin": gstin,
            "state_code": None if gstin else state,
            "identified": bool(gstin or state)}


def _type_of_goods(kind: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(the form's type, why there is none)."""
    if kind == dc.GOODS_KIND_INPUTS:
        return "Inputs", None
    if kind == dc.GOODS_KIND_CAPITAL_GOODS:
        return "Capital goods", None
    if kind == dc.GOODS_KIND_EXCLUDED:
        return None, MOULDS_NOT_NAMED_BY_THE_FORM
    return None, ("The kind of goods (inputs or capital goods) is not recorded on "
                  "this challan, and the form asks for it. Record it — it also "
                  "decides which s.143 period runs.")


def _rates(rate_percent, is_inter_state: bool) -> dict:
    """The line's rate split the way the form lays it out. The GST rate is
    carried as stored; an intra-State supply halves it between CGST and SGST
    and an inter-State one is all IGST. Strings, never floats."""
    rate = _d(rate_percent)
    if is_inter_state:
        return {"igst_rate": _rate_text(rate), "cgst_rate": "0", "sgst_rate": "0"}
    half = _rate_text(rate / 2)
    return {"igst_rate": "0", "cgst_rate": half, "sgst_rate": half}


def _rate_text(rate: Decimal) -> str:
    """A rate with no trailing zeros, so NUMERIC(5,2)'s '18.00', a driver's
    '18.0' and a fixture's '18' all read '18' and 7.5% halves to '3.75'."""
    if rate == 0:
        return "0"
    return format(rate.normalize(), "f")


def _uqc_gap(unit) -> Optional[str]:
    return _uqc.problem_with(unit)


def _lines_by_challan(lines: Iterable[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for ln in lines or []:
        out.setdefault(str(ln.get("challan_id")), []).append(ln)
    for rows in out.values():
        rows.sort(key=lambda r: (int(r.get("line_order") or 0), str(r.get("id"))))
    return out


def _returns_by_line(returns: Iterable[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in returns or []:
        out.setdefault(str(r.get("challan_line_id")), []).append(r)
    return out


# ── Table 4 ──────────────────────────────────────────────────────────────────

def table_4(challans: list[dict], lines: list[dict], window: Window) -> dict:
    """Goods sent in the window, one row per challan line."""
    by_challan = _lines_by_challan(lines)
    rows: list[dict] = []
    gaps: list[dict] = []
    for ch in sorted(challans, key=lambda c: (str(c.get("document_date")),
                                              str(c.get("document_no")))):
        if not is_job_work_sent(ch) or not window.contains(ch.get("document_date")):
            continue
        worker = _job_worker(ch)
        kind, kind_gap = _type_of_goods(ch.get("goods_kind"))
        if not worker["identified"]:
            gaps.append({"challan_no": ch.get("document_no"), "kind": "job_worker_not_identified",
                         "reason": ("Neither the job worker's GSTIN nor their State is "
                                    "recorded, and the form asks for one of them.")})
        if kind_gap:
            gaps.append({"challan_no": ch.get("document_no"), "kind": "type_of_goods",
                         "reason": kind_gap})
        for ln in by_challan.get(str(ch.get("id")), []):
            problem = _uqc_gap(ln.get("unit"))
            if problem:
                gaps.append({"challan_no": ch.get("document_no"), "kind": "uqc",
                             "reason": problem})
            rows.append({
                "challan_id": ch.get("id"),
                "challan_line_id": ln.get("id"),
                "job_worker": worker,
                "challan_no": ch.get("document_no"),
                "challan_date": str(ch.get("document_date"))[:10],
                "type_of_goods": kind,
                "description": ln.get("description"),
                "hsn_sac": ln.get("hsn_sac"),
                "uqc": _uqc.normalise(ln.get("unit")),
                "quantity": _qty(_d(ln.get("quantity"))),
                "taxable_value_paise": int(ln.get("taxable_amount_paise") or 0),
                **_rates(ln.get("gst_rate_percent"), bool(ch.get("is_inter_state"))),
            })
    return {"title": TABLE_4, "rows": rows, "count": len(rows),
            "taxable_value_paise": sum(r["taxable_value_paise"] for r in rows),
            "gaps": gaps}


# ── Table 5A ─────────────────────────────────────────────────────────────────

def table_5a(challans: list[dict], lines: list[dict], returns: list[dict],
             window: Window) -> dict:
    """Goods received back in the window, one row per return — against the
    ORIGINAL challan, which may belong to an earlier period."""
    ch_by_id = {str(c.get("id")): c for c in challans if is_job_work_sent(c)}
    ln_by_id = {str(l.get("id")): l for l in lines}
    by_challan = _lines_by_challan(lines)
    returns_by_line = _returns_by_line(returns)
    rows: list[dict] = []
    gaps: list[dict] = []

    for r in sorted(returns, key=lambda x: (str(x.get("returned_on")), str(x.get("id")))):
        ch = ch_by_id.get(str(r.get("challan_id")))
        ln = ln_by_id.get(str(r.get("challan_line_id")))
        if ch is None or ln is None or not window.contains(r.get("returned_on")):
            continue
        worker = _job_worker(ch)
        if not r.get("job_worker_challan_no"):
            gaps.append({"challan_no": ch.get("document_no"), "kind": "job_worker_challan",
                         "reason": ("The challan the job worker issued when the goods came "
                                    "back is not recorded, and the form asks for its number "
                                    "and date.")})
        if not (r.get("nature_of_job_work") or "").strip():
            gaps.append({"challan_no": ch.get("document_no"), "kind": "nature_of_job_work",
                         "reason": "The nature of the job work done is not recorded."})
        problem = _uqc_gap(ln.get("unit"))
        if problem:
            gaps.append({"challan_no": ch.get("document_no"), "kind": "uqc", "reason": problem})
        rows.append({
            "challan_id": ch.get("id"), "challan_line_id": ln.get("id"),
            "job_worker": worker,
            "original_challan_no": ch.get("document_no"),
            "original_challan_date": str(ch.get("document_date"))[:10],
            "job_worker_challan_no": r.get("job_worker_challan_no"),
            "job_worker_challan_date": (str(r.get("job_worker_challan_date"))[:10]
                                        if r.get("job_worker_challan_date") else None),
            "nature_of_job_work": r.get("nature_of_job_work"),
            "returned_on": str(r.get("returned_on"))[:10],
            "description": ln.get("description"),
            "uqc": _uqc.normalise(ln.get("unit")),
            "quantity": _qty(_d(r.get("quantity_returned"))),
            "lost_or_wasted_quantity": _qty(_d(r.get("quantity_lost_or_wasted"))),
            "derived_from_whole_challan_return": False,
        })

    # A challan the CA marked as wholly back with `received_back_on` and no (or
    # fewer) per-line returns: the date and the fact are stated, the particulars
    # the form asks for are not. Reported, flagged and never silently dropped.
    for cid, ch in ch_by_id.items():
        back_on = ch.get("received_back_on")
        if not back_on or not window.contains(back_on):
            continue
        for ln in by_challan.get(cid, []):
            itemised = sum((_d(x.get("quantity_returned"))
                            for x in returns_by_line.get(str(ln.get("id")), [])),
                           Decimal(0))
            rest = _d(ln.get("quantity")) - itemised
            if rest <= 0:
                continue
            gaps.append({"challan_no": ch.get("document_no"),
                         "kind": "whole_challan_return",
                         "reason": ("This challan was marked wholly received back without "
                                    "recording the return line by line, so the job worker's "
                                    "own challan and the nature of the job work are not held.")})
            rows.append({
                "challan_id": ch.get("id"), "challan_line_id": ln.get("id"),
                "job_worker": _job_worker(ch),
                "original_challan_no": ch.get("document_no"),
                "original_challan_date": str(ch.get("document_date"))[:10],
                "job_worker_challan_no": None, "job_worker_challan_date": None,
                "nature_of_job_work": None,
                "returned_on": str(back_on)[:10],
                "description": ln.get("description"),
                "uqc": _uqc.normalise(ln.get("unit")),
                "quantity": _qty(rest), "lost_or_wasted_quantity": _qty(Decimal(0)),
                "derived_from_whole_challan_return": True,
            })
    rows.sort(key=lambda x: (x["returned_on"], str(x["original_challan_no"])))
    return {"title": TABLE_5A, "rows": rows, "count": len(rows), "gaps": gaps}


# ── What is still with the job worker, and the s.143 date for it ─────────────

def balances(challans: list[dict], lines: list[dict], returns: list[dict],
             as_at: str) -> list[dict]:
    """Per challan line: sent, returned, still outstanding — and the §143 clock
    that outstanding part is running against.

    THE CLOCK IS THE CHALLAN'S AND THE AMOUNT AT STAKE IS THE BALANCE'S. A part
    return does not move the day the goods were sent out, which is the day
    s.143(3) deems the supply made; it reduces only what is left to be deemed
    supplied. So `deemed_supply_clock` is asked with NO `received_back_on` for a
    challan that still has a balance, and the figure beside it is the balance's
    share of the line's taxable value, rounded UP.
    """
    by_challan = _lines_by_challan(lines)
    returns_by_line = _returns_by_line(returns)
    out: list[dict] = []
    for ch in sorted(challans, key=lambda c: (str(c.get("document_date")),
                                              str(c.get("document_no")))):
        if (not is_job_work_sent(ch) or ch.get("received_back_on")
                or str(ch.get("status")) == "received_back"):
            continue                    # the CA said all of it came back
        challan_lines = []
        outstanding_any = False
        for ln in by_challan.get(str(ch.get("id")), []):
            sent = _d(ln.get("quantity"))
            got = [x for x in returns_by_line.get(str(ln.get("id")), [])
                   if not x.get("returned_on") or str(x.get("returned_on"))[:10] <= as_at]
            returned = sum((_d(x.get("quantity_returned")) for x in got), Decimal(0))
            wasted = sum((_d(x.get("quantity_lost_or_wasted")) for x in got), Decimal(0))
            balance = sent - returned
            if balance <= 0:
                continue
            outstanding_any = True
            taxable = int(ln.get("taxable_amount_paise") or 0)
            at_stake = int((Decimal(taxable) * balance / sent)
                           .to_integral_value(rounding=ROUND_CEILING)) if sent > 0 else 0
            challan_lines.append({
                "challan_line_id": ln.get("id"),
                "description": ln.get("description"),
                "uqc": _uqc.normalise(ln.get("unit")),
                "sent": _qty(sent), "returned": _qty(returned),
                "lost_or_wasted": _qty(wasted), "outstanding": _qty(balance),
                "taxable_value_at_stake_paise": at_stake,
            })
        if not outstanding_any:
            continue
        clock = dc.deemed_supply_clock(
            reason=str(ch.get("reason")), challan_date=ch.get("document_date"),
            as_at=as_at, goods_kind=ch.get("goods_kind"),
            received_back_on=None, extended_to=ch.get("extended_to"))
        out.append({
            "challan_id": ch.get("id"),
            "challan_no": ch.get("document_no"),
            "challan_date": str(ch.get("document_date"))[:10],
            "job_worker": _job_worker(ch),
            "goods_kind": ch.get("goods_kind"),
            "lines": challan_lines,
            "taxable_value_at_stake_paise": sum(
                l["taxable_value_at_stake_paise"] for l in challan_lines),
            "clock": clock.as_dict(),
        })
    return out


# ── The statement ────────────────────────────────────────────────────────────

def window_counts(challans: list[dict], lines: list[dict], returns: list[dict],
                  financial_year: str) -> list[dict]:
    """Every reading, every window, with how many rows it would carry — so the
    CA can see which windows have anything in them before opening one."""
    ch_by_id = {str(c.get("id")): c for c in challans if is_job_work_sent(c)}
    # Grouped once: a count per window must not rescan every line per challan.
    line_count = {cid: len(rows) for cid, rows in _lines_by_challan(lines).items()}
    all_windows = windows_for(financial_year)
    out = []
    for cadence, label in CADENCES:
        wins = []
        for w in all_windows[cadence]:
            sent = sum(line_count.get(cid, 0) for cid, c in ch_by_id.items()
                       if w.contains(c.get("document_date")))
            back = sum(1 for r in returns
                       if str(r.get("challan_id")) in ch_by_id
                       and w.contains(r.get("returned_on")))
            wins.append({**w.as_dict(), "table_4_rows": sent, "table_5a_rows": back})
        out.append({"cadence": cadence, "label": label, "chosen": False,
                    "windows": wins})
    return out


def statement_gaps() -> list[str]:
    """What the statement cannot say, on every answer."""
    return [FORM_NUMBERING, TABLE_5B_NOT_DERIVED, TABLE_5C_NOT_DERIVED,
            WASTE_IS_NOT_SUBTRACTED, TAX_ON_DEEMED_SUPPLY_NOT_COMPUTED,
            NOTHING_IS_FILED]
