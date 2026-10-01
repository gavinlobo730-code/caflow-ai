"""Bringing a client's fixed-asset register over, asset by asset, with the
depreciation each already carries (accounting-18).

Companies Act 2013 Schedule II and AS 10 / Ind AS 16 — an asset is carried at its
cost less the depreciation accumulated on it, and a migrated client's assets are
part-way through their lives. CGST Act s.7 — bringing a balance forward is not a
supply, so nothing here computes or declares any tax.

WHAT WAS MISSING
    The register could take an asset one way: `POST /api/fixed-assets`, which
    starts accumulated depreciation at nil and posts a fresh acquisition journal.
    A client arriving from Tally has a hundred assets at some position of their
    own, and the only routes to it were to let the runner charge every month since
    the purchase date on top of the balance the opening trial balance already
    carries, or to start the first posting late. Neither STATES where the asset
    stands, and `accumulated_depreciation_paise` has no writable door at all.

WHAT THIS MODULE DECIDES, AND WHAT IT DOES NOT
    Rows in, a verdict per asset out: no database handle, no clock (the caller
    passes `today`), no fetching. For every row it says whether the asset is NEW,
    ALREADY RECORDED (a re-upload) or REJECTED, and a rejected row carries EVERY
    problem it has — a file corrected one error at a time is a file uploaded
    nineteen times.

    The row is judged by the SAME rules the single form applies, not a looser set
    for a bulk door: the category must be one Schedule II Part C prescribes, a
    category with no prescribed life needs a rate or a life stated (the sentence
    is `schedule_ii.no_statutory_basis`, shared with `create_asset`), the code is
    judged by `asset_code.problem_with`, and then `integrity.register_findings` is
    asked of the finished row — "validate the register-integrity rules before
    saving" is that call, literally, so what a CA is told here is what
    `GET /register-integrity` would say after.

THE POSITION IS A FINANCIAL-YEAR END, AND THAT IS A DECISION
    Depreciation is charged one financial year at a time: a reducing balance is
    ONE annual figure computed from the year's OPENING written-down value and
    divided by twelve (`_annual_depreciation_for_period`). An asset stated as at
    30 September carries six months of that year's charge inside its accumulated
    figure, and nothing in the file says what the year opened at — so the next
    month's charge would be computed off the wrong base for the rest of the year.
    A 31 March position needs no such figure, because the next financial year's
    opening IS the stated one. Mid-year is REFUSED, with the way round it: load
    the register as at the 31 March before, and the range runner charges the
    months since. Same shape as the FY-versioned registries refusing a year they
    do not hold.

IT POSTS NO JOURNAL, AND NAMES THAT
    migration 391's decision for assets. The ledger's Fixed Assets and
    Accumulated Depreciation balances arrive through the opening balances or an
    imported trial balance, and this register is their asset-by-asset breakup.
    An acquisition posted per asset as well would open the same position twice.
    The summary says so on every answer rather than letting a quiet success read
    as "the balance sheet now carries these", and the CA compares the totals it
    reports with the ledger.

WHAT IS REFUSED RATHER THAN GUESSED
    * A blank accumulated depreciation. Nil is a real answer and is TYPED; a blank
      is the column header that did not match, which would otherwise arrive as a
      hundred assets that have never been depreciated and be charged from scratch.
    * A blank method. It decides every later charge.
    * A put-to-use date is never taken from the purchase date (IT Act s.32(1),
      second proviso) — absent stays absent and is NAMED in the summary.
    * Nothing is overwritten. A code already on the register is skipped when it is
      the same opening asset and refused, naming the difference, when it is not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from domain.fixed_assets import asset_code as asset_code_rule
from domain.fixed_assets import integrity as fa_integrity
from domain.fixed_assets import schedule_ii
from domain.money_text import rupees_paise
from domain.spreadsheet_cells import DATE_FORMAT_SENTENCE, fold_name, parse_cell_date

NEW = "new"
ALREADY_RECORDED = "already_recorded"
REJECTED = "rejected"

#: One import is judged whole and written in chunks, and no journal is posted, so
#: this is not about a request outliving its caller — it is a bound on what a
#: single upload may ask the server to hold. A client with more assets than this
#: splits the file by class; a re-upload skips what is already in.
MAX_ROWS = 2000

#: What every answer says about the ledger, once, by the module that decides it.
NOTHING_IS_POSTED = (
    "Nothing was posted to the ledger. These assets are the asset-by-asset "
    "breakup of the Fixed Assets and Accumulated Depreciation balances the "
    "opening balances or an imported trial balance carry — compare the totals "
    "below with those two figures as at the position date. Posting an acquisition "
    "for each asset as well would count the same cost twice.")

_METHODS = {
    "wdv": "WDV", "written down value": "WDV", "written-down value": "WDV",
    "reducing balance": "WDV",
    "sl": "SL", "slm": "SL", "straight line": "SL", "straight-line": "SL",
    "straight line method": "SL",
}

_LIFE = re.compile(r"\d{1,3}")
_RATE = re.compile(r"\d{1,3}(?:\.\d{1,2})?")

_CATEGORY_BY_FOLDED = {fold_name(c): c for c in schedule_ii.CATEGORIES}


def _r(paise: int) -> str:
    return f"₹{rupees_paise(paise)}"


# ── the position date ────────────────────────────────────────────────────────

def position_problem(text: Optional[str], today: date) -> tuple[Optional[date], Optional[str]]:
    """The date the register is stated AS AT, or the sentence that says why not.

    Request-level, not per row: one position for the whole file, the way a trial
    balance has one date, and a file that mixed several would make "the next run
    starts from each asset's stated position" a different month for each asset.
    """
    raw = (text or "").strip()
    d = parse_cell_date(raw)
    if d is None:
        if not raw:
            return None, "The position date is blank — the date the accumulated depreciation is stated as at."
        return None, (f"The position date \"{raw}\" is not a date — {DATE_FORMAT_SENTENCE}.")
    if (d.month, d.day) != (3, 31):
        return None, (
            f"The position date must be a financial-year end, 31 March — {d.isoformat()} "
            "is not. Depreciation is charged one financial year at a time from that "
            "year's opening written-down value, so a position taken part-way through a "
            "year would need the year's opening figure as well. Load the register as at "
            "the 31 March before the date you are migrating from; the depreciation "
            "runner then charges the months since.")
    if d > today:
        return None, (f"The position date {d.isoformat()} is in the future — an accumulated "
                      "depreciation can only be stated as at a date that has passed.")
    return d, None


def next_depreciation_month(as_at: date) -> str:
    """The month the next depreciation run starts at: the one after the position."""
    y, m = as_at.year, as_at.month + 1
    if m > 12:
        y, m = y + 1, 1
    return f"{y:04d}-{m:02d}"


# ── what a row is ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ImportRow:
    """One spreadsheet row, as typed.

    Dates, text and the two rate-like cells (life, rate) are TEXT: reading them is
    this module's rule, and a browser that did it would be a second
    implementation. Money is paise — `None` where the browser could not read the
    cell as an amount, so the row still arrives and is refused BY NUMBER instead
    of being dropped on the way and missing from the report.
    """
    row: int
    asset_code: str = ""
    asset_name: str = ""
    asset_category: str = ""
    purchase_date: str = ""
    put_to_use_date: str = ""
    cost_paise: Optional[int] = None
    accumulated_depreciation_paise: Optional[int] = None
    salvage_value_paise: Optional[int] = 0
    depreciation_method: str = ""
    useful_life_years: str = ""
    wdv_rate_percent: str = ""
    it_block_key: str = ""
    location: str = ""
    notes: str = ""


@dataclass(frozen=True)
class PlannedAsset:
    """The values of a `fixed_assets` row for an asset brought over.

    Written out as fields rather than a dict, and `as_row` is the DEFINITION of
    the columns: the service writes them literally (so the schema scanners can
    read the insert) and a test asserts its keys are exactly these.
    """
    asset_code: str
    asset_name: str
    asset_category: str
    purchase_date: str
    purchase_cost_paise: int
    salvage_value_paise: int
    accumulated_depreciation_paise: int
    depreciation_method: str
    useful_life_years: Optional[int]
    wdv_rate_percent: Optional[float]
    opening_position_date: str
    put_to_use_date: Optional[str] = None
    it_block_key: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None

    @property
    def current_wdv_paise(self) -> int:
        return self.purchase_cost_paise - self.accumulated_depreciation_paise

    def as_row(self) -> dict:
        return {
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "asset_category": self.asset_category,
            "purchase_date": self.purchase_date,
            "purchase_cost_paise": self.purchase_cost_paise,
            "salvage_value_paise": self.salvage_value_paise,
            "useful_life_years": self.useful_life_years,
            "depreciation_method": self.depreciation_method,
            "wdv_rate_percent": self.wdv_rate_percent,
            "accumulated_depreciation_paise": self.accumulated_depreciation_paise,
            "current_wdv_paise": self.current_wdv_paise,
            # "Posted through" the position date is what makes the next run start
            # the month after it and never the purchase month — and what lets a
            # skipped month be refused by name rather than silently charged.
            "depreciation_posted_through": self.opening_position_date,
            "opening_position_date": self.opening_position_date,
            "put_to_use_date": self.put_to_use_date,
            "it_block_key": self.it_block_key,
            "location": self.location,
            "notes": self.notes,
        }

    def register_row(self) -> dict:
        """The row as `register_findings` reads it — the stored shape plus what
        a freshly read asset carries (`is_disposed`, no journal, no bill)."""
        return {**self.as_row(), "id": None, "is_disposed": False,
                "journal_entry_id": None, "purchase_bill_id": None,
                "acquisition_mode": None}


@dataclass(frozen=True)
class AssetVerdict:
    row: int
    asset_code: str
    status: str
    problems: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    planned: Optional[PlannedAsset] = None
    existing_id: Optional[str] = None

    @property
    def sentence(self) -> str:
        return " ".join(self.problems)


def _text(v) -> str:
    return (v if isinstance(v, str) else ("" if v is None else str(v))).strip()


def _nothing(v: Optional[str]) -> Optional[str]:
    t = _text(v)
    return t or None


def _read_method(raw: str) -> tuple[Optional[str], Optional[str]]:
    t = fold_name(raw)
    if not t:
        return None, ("The depreciation method is blank. It decides every later "
                      "charge, so it is stated rather than assumed — WDV or SL.")
    got = _METHODS.get(t)
    if got is None:
        return None, f"\"{_text(raw)}\" is not a depreciation method — WDV or SL."
    return got, None


def _read_life(raw: str) -> tuple[Optional[int], Optional[str]]:
    t = _text(raw)
    if not t:
        return None, None
    if not _LIFE.fullmatch(t) or not 1 <= int(t) <= 100:
        return None, (f"The useful life \"{t}\" is not a whole number of years between "
                      "1 and 100.")
    return int(t), None


def _read_rate(raw: str) -> tuple[Optional[Decimal], Optional[str]]:
    t = _text(raw).rstrip("%").strip()
    if not t:
        return None, None
    if not _RATE.fullmatch(t):
        return None, (f"The WDV rate \"{_text(raw)}\" is not a percentage with at most "
                      "two decimals, e.g. 15 or 13.91.")
    try:
        d = Decimal(t)
    except InvalidOperation:                      # pragma: no cover — regex-guarded
        return None, f"The WDV rate \"{_text(raw)}\" is not a number."
    if d > 100:
        return None, f"The WDV rate {d}% is more than 100%."
    return d, None


def _read_money(label: str, v: Optional[int]) -> tuple[Optional[int], Optional[str]]:
    if v is None:
        return None, f"The {label} is not an amount."
    if v < 0:
        return None, f"The {label} cannot be negative."
    return v, None


def plan(rows: Iterable[ImportRow], existing_by_code: dict[str, dict],
         *, as_at: date) -> list[AssetVerdict]:
    """What each asset is, in file order.

    `existing_by_code` — casefolded asset code → the register row holding it,
    INCLUDING a soft-deleted one (migration 351's unique index covers it, so a
    deleted asset still owns its code): `id`, `asset_name`, `asset_category`,
    `purchase_date`, `purchase_cost_paise`, `opening_position_date`, `deleted_at`.
    """
    position = as_at.isoformat()
    out: list[AssetVerdict] = []
    first_row_of: dict[str, int] = {}

    for r in rows:
        problems: list[str] = []
        warnings: list[str] = []
        code = _text(r.asset_code)
        key = code.casefold()

        # ── identity ──────────────────────────────────────────────────────
        if not code:
            problems.append(
                "The asset code is blank. It is the asset's identity — the number on "
                "the machine, what every depreciation entry is referenced by and what "
                "lets uploading the same file again recognise an asset already in.")
        else:
            why = asset_code_rule.problem_with(code)
            if why:
                problems.append(why)
            elif key in first_row_of:
                problems.append(
                    f"The asset code \"{code}\" is also on row {first_row_of[key]} of this "
                    "file. Two assets cannot share one code.")
            else:
                first_row_of[key] = r.row
        name = _text(r.asset_name)
        if not name:
            problems.append("The asset name is blank.")

        # ── category ──────────────────────────────────────────────────────
        category = _CATEGORY_BY_FOLDED.get(fold_name(r.asset_category))
        if category is None:
            given = _text(r.asset_category)
            problems.append(
                (f"\"{given}\" is not an asset category this register holds. " if given
                 else "The asset category is blank. ")
                + "Use one of: " + ", ".join(schedule_ii.CATEGORIES) + ".")

        # ── dates ─────────────────────────────────────────────────────────
        bought = parse_cell_date(_text(r.purchase_date))
        if bought is None:
            given = _text(r.purchase_date)
            problems.append(
                f"The purchase date \"{given}\" is not a date — {DATE_FORMAT_SENTENCE}."
                if given else "The purchase date is blank.")
        elif bought > as_at:
            problems.append(
                f"Bought on {bought.isoformat()}, after the position date {position}. "
                "An asset acquired after the position is an addition, not an opening "
                "balance — add it with Add Asset so its acquisition is posted.")
        put_to_use = None
        if _text(r.put_to_use_date):
            put_to_use = parse_cell_date(_text(r.put_to_use_date))
            if put_to_use is None:
                problems.append(
                    f"The put-to-use date \"{_text(r.put_to_use_date)}\" is not a date — "
                    f"{DATE_FORMAT_SENTENCE}.")
            elif bought is not None and put_to_use < bought:
                problems.append(
                    f"Put to use on {put_to_use.isoformat()}, before it was bought on "
                    f"{bought.isoformat()}.")

        # ── money ─────────────────────────────────────────────────────────
        cost, why = _read_money("cost", r.cost_paise)
        if why:
            problems.append(why)
        elif cost == 0:
            problems.append("The cost is nil — an asset carried at nothing is not an asset "
                            "to put on the register.")
            cost = None
        accum, why = _read_money("accumulated depreciation", r.accumulated_depreciation_paise)
        if why:
            problems.append(why)
        salvage, why = _read_money("salvage value", r.salvage_value_paise)
        if why:
            problems.append(why)

        if cost is not None and salvage is not None and salvage >= cost:
            problems.append(f"The salvage value {_r(salvage)} is not below the cost {_r(cost)}.")
            salvage = None
        if cost is not None and accum is not None:
            if accum > cost:
                problems.append(
                    f"The accumulated depreciation {_r(accum)} is more than the cost "
                    f"{_r(cost)} — an asset cannot be written down below nothing.")
            elif salvage is not None and accum > cost - salvage:
                problems.append(
                    f"The accumulated depreciation {_r(accum)} takes the asset below its "
                    f"salvage value ({_r(salvage)} of {_r(cost)}). Depreciation stops at the "
                    "salvage value, so this position cannot be real — check the figures, or "
                    "the salvage value.")
        if category in schedule_ii.NOT_DEPRECIABLE and accum:
            problems.append(f"{category} is never depreciated (Schedule II) — its "
                            "accumulated depreciation is nil.")

        # ── method, life and rate: the same basis create_asset resolves ───
        if category in schedule_ii.NOT_DEPRECIABLE and not _text(r.depreciation_method):
            # Land is never depreciated whichever method the row carries, so a blank
            # here decides nothing and is not an invented answer — the column's own
            # default, exactly as the single form stores it.
            method, why = "WDV", None
        else:
            method, why = _read_method(r.depreciation_method)
        if why:
            problems.append(why)
        life, why = _read_life(r.useful_life_years)
        if why:
            problems.append(why)
        rate, why = _read_rate(r.wdv_rate_percent)
        if why:
            problems.append(why)

        life_stored: Optional[int] = life
        rate_stored: Optional[Decimal] = rate
        # Only once every fact the basis is resolved FROM is readable: a second
        # sentence about a missing rate would repeat the real problem.
        if category is not None and method is not None and not problems:
            default = schedule_ii.default_class(category)
            # `is not None`, never `or`: an explicit 0.00 is a real answer. The
            # life uses `or` — a life of 0 is refused above, so the only falsy
            # value left is "not stated" (create_asset's own comment).
            rate_stored = rate if rate is not None else default["wdv_rate_percent"]
            life_stored = life or default["useful_life_years"]
            if category not in schedule_ii.NOT_DEPRECIABLE:
                if method == "WDV" and rate_stored is None:
                    problems.append(schedule_ii.no_statutory_basis(category, "WDV"))
                if method == "SL" and not life_stored:
                    problems.append(schedule_ii.no_statutory_basis(category, "SL"))

        # ── the finished row, through the register-integrity rules ────────
        planned: Optional[PlannedAsset] = None
        if not problems:
            planned = PlannedAsset(
                asset_code=code, asset_name=name, asset_category=category,
                purchase_date=bought.isoformat(), purchase_cost_paise=cost,
                salvage_value_paise=salvage, accumulated_depreciation_paise=accum,
                depreciation_method=method, useful_life_years=life_stored,
                wdv_rate_percent=None if rate_stored is None else float(rate_stored),
                opening_position_date=position,
                put_to_use_date=put_to_use.isoformat() if put_to_use else None,
                it_block_key=_nothing(r.it_block_key),
                location=_nothing(r.location), notes=_nothing(r.notes))
            for f in fa_integrity.register_findings([planned.register_row()], set()):
                if f.get("kind") == "wdv_asset_has_no_stopping_point":
                    problems.append(f["what_it_means"])
                else:
                    # A departure from Schedule II is ALLOWED (Part A) and must be
                    # disclosed, so it is reported beside the row and never blocks
                    # it — and any kind a later change adds is shown rather than
                    # swallowed.
                    warnings.append(f.get("what_it_means") or f.get("kind", ""))
            if (method == "WDV" and rate is not None and 0 < rate < 1
                    and category not in schedule_ii.NOT_DEPRECIABLE):
                warnings.append(
                    f"A WDV rate of {rate}% is unusual. A spreadsheet percentage cell that "
                    "shows 15% holds 0.15, and is read as a rate of 0.15% — check it is "
                    "not that.")

        # ── is it already on the register? ────────────────────────────────
        existing_id = None
        if not problems and planned is not None:
            held = existing_by_code.get(key)
            if held is not None:
                existing_id = held.get("id")
                differs = _how_it_differs(held, planned)
                if held.get("deleted_at"):
                    problems.append(
                        f"The code \"{code}\" belongs to an asset that was deleted. A "
                        "deleted asset keeps its code for good, because every journal "
                        "reference is built from it — use another code.")
                elif not held.get("opening_position_date"):
                    problems.append(
                        f"\"{code}\" is an asset added through Add Asset, with an acquisition "
                        f"on the ledger of its own ({_r(int(held.get('purchase_cost_paise') or 0))}, "
                        f"bought {str(held.get('purchase_date') or '')[:10]}). An import never "
                        "overwrites one — use another code.")
                elif differs:
                    problems.append(
                        f"\"{code}\" is already on the register as an opening asset, but "
                        f"{differs}. Nothing is overwritten — if the file is right, delete "
                        "the asset (allowed while nothing has been depreciated since its "
                        "position) and upload again.")
                else:
                    out.append(AssetVerdict(
                        row=r.row, asset_code=code, status=ALREADY_RECORDED,
                        existing_id=existing_id))
                    continue

        if problems:
            out.append(AssetVerdict(row=r.row, asset_code=code, status=REJECTED,
                                    problems=tuple(dict.fromkeys(problems)),
                                    existing_id=existing_id))
        else:
            out.append(AssetVerdict(row=r.row, asset_code=code, status=NEW,
                                    warnings=tuple(dict.fromkeys(warnings)),
                                    planned=planned))
    return out


def _how_it_differs(held: dict, planned: PlannedAsset) -> Optional[str]:
    """What an existing opening asset disagrees with the row about, or None.

    Identity only — name, category, purchase date, cost and the position date.
    The accumulated depreciation is deliberately NOT compared: it moves, because
    a depreciation run after the import changes it, and a re-upload of the same
    file must still be recognised then.
    """
    parts = []
    if fold_name(held.get("asset_name")) != fold_name(planned.asset_name):
        parts.append(f"it is named \"{held.get('asset_name')}\"")
    if (held.get("asset_category") or "") != planned.asset_category:
        parts.append(f"it is a {held.get('asset_category')}")
    if str(held.get("purchase_date") or "")[:10] != planned.purchase_date:
        parts.append(f"it was bought on {str(held.get('purchase_date') or '')[:10]}")
    if int(held.get("purchase_cost_paise") or 0) != planned.purchase_cost_paise:
        parts.append(f"its cost is {_r(int(held.get('purchase_cost_paise') or 0))}")
    if str(held.get("opening_position_date") or "")[:10] != planned.opening_position_date:
        parts.append(f"it was stated as at {str(held.get('opening_position_date') or '')[:10]}")
    if not parts:
        return None
    return "this row says otherwise — " + ", ".join(parts) + " there"


# ── what the file amounts to ─────────────────────────────────────────────────

@dataclass(frozen=True)
class Summary:
    received: int
    new: int
    already_recorded: int
    rejected: int
    cost_paise: int
    accumulated_paise: int
    by_category: list[dict] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def net_paise(self) -> int:
        return self.cost_paise - self.accumulated_paise


def summarise(verdicts: Iterable[AssetVerdict]) -> Summary:
    vs = list(verdicts)
    new = [v.planned for v in vs if v.status == NEW and v.planned is not None]
    by_cat: dict[str, dict] = {}
    for p in new:
        b = by_cat.setdefault(p.asset_category, {
            "asset_category": p.asset_category, "assets": 0,
            "cost_paise": 0, "accumulated_paise": 0, "net_paise": 0})
        b["assets"] += 1
        b["cost_paise"] += p.purchase_cost_paise
        b["accumulated_paise"] += p.accumulated_depreciation_paise
        b["net_paise"] += p.current_wdv_paise

    gaps: list[str] = []
    no_use = sum(1 for p in new if p.put_to_use_date is None
                 and p.asset_category not in schedule_ii.NOT_DEPRECIABLE)
    if no_use:
        gaps.append(
            f"{no_use} depreciable asset{'s have' if no_use != 1 else ' has'} no put-to-use "
            "date. The Income-tax Act s.32 working names each as a gap instead of taking the "
            "purchase date for it — the second proviso to s.32(1) turns on the date an asset "
            "was put to use, which is not the date it was bought.")
    no_block = sum(1 for p in new if p.it_block_key is None)
    if no_block:
        gaps.append(
            f"{no_block} asset{'s are' if no_block != 1 else ' is'} in no Income-tax Act "
            "s.32 block. The block is a determination the CA makes (s.2(11) groups by nature "
            "and rate, which a Schedule II category does not decide), so none is assumed.")

    return Summary(
        received=len(vs),
        new=sum(1 for v in vs if v.status == NEW),
        already_recorded=sum(1 for v in vs if v.status == ALREADY_RECORDED),
        rejected=sum(1 for v in vs if v.status == REJECTED),
        cost_paise=sum(p.purchase_cost_paise for p in new),
        accumulated_paise=sum(p.accumulated_depreciation_paise for p in new),
        by_category=sorted(by_cat.values(), key=lambda b: b["asset_category"]),
        gaps=gaps)
