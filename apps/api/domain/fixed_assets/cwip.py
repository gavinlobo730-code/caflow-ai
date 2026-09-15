"""Capital work-in-progress — Schedule III Division I (FA-11a).

WHY THIS EXISTS

`fixed_assets` is the only place an asset can live in this product, and
everything in it is depreciated. So a client building a factory either left it
out of the register — a balance sheet short by the whole of what has been spent
— or put it in, and had depreciation charged on an asset that is not ready for
use. AS-10 paragraph 20 and Schedule II both start depreciation when the asset
is AVAILABLE FOR USE: in the location and condition necessary for it to operate
as management intends.

MCA Notification G.S.R. 207(E) of 24 March 2021 — the same notification that
added the two ageing schedules `domain/reporting/ageing.py` builds — gives CWIP
three things in Schedule III Division I:

  * its own line under Non-current assets, immediately after Property, Plant
    and Equipment, never merged into it;
  * an AGEING SCHEDULE in the notes: the amount in CWIP for less than 1 year,
    1-2 years, 2-3 years and more than 3 years, with the total split between
    "Projects in progress" and "Projects temporarily suspended";
  * a COMPLETION SCHEDULE, in the same four bands, for every project OVERDUE
    against its originally approved completion date OR OVER its originally
    approved cost.

THIS MODULE READS NOTHING AND POSTS NOTHING. It takes projects and additions
that have already been fetched and returns the two schedules.

⚠️ [S] — the form's own row labels and the four band captions are written from
knowledge, because every `.gov.in` is refused at this environment's egress
proxy. The FIGURES are not affected: each is a total of amounts this product
recorded. A test pins the labels so a later correction is deliberate.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional

#: The four bands, in the order the prescribed table prints them. Months rather
#: than years so the arithmetic is exact — "1-2 years" measured in days would
#: disagree with itself across a leap year.
BUCKETS: tuple[tuple[str, Optional[int], Optional[int]], ...] = (
    ("less_than_1_year", None, 12),
    ("1_2_years", 12, 24),
    ("2_3_years", 24, 36),
    ("more_than_3_years", 36, None),
)

BUCKET_LABELS = {
    "less_than_1_year": "Less than 1 year",
    "1_2_years": "1-2 years",
    "2_3_years": "2-3 years",
    "more_than_3_years": "More than 3 years",
}

#: The two rows of the ageing schedule. A project that is neither is not in
#: CWIP at all — it has been capitalised or abandoned.
IN_PROGRESS = "in_progress"
SUSPENDED = "suspended"
ROW_LABELS = {
    IN_PROGRESS: "Projects in progress",
    SUSPENDED: "Projects temporarily suspended",
}

CWIP_DOES_NOT_DEPRECIATE = (
    "Capital work-in-progress is not depreciated. AS-10 paragraph 20 starts "
    "depreciation when the asset is available for use — in the location and "
    "condition necessary for it to operate as management intends — which is "
    "the date the project is capitalised and becomes a fixed asset."
)

APPROVAL_NOT_RECORDED = (
    "No originally approved completion date or cost is recorded for this "
    "project, so whether it is overdue or over budget cannot be determined. "
    "Schedule III's completion schedule measures both against the ORIGINAL "
    "approval, and neither can be inferred: the start date is not an approved "
    "completion date, and what has been spent is not an approved cost."
)

EXPECTED_DATE_NOT_RECORDED = (
    "This project is reportable in the completion schedule and no expected "
    "completion date is recorded, so the band it falls in cannot be stated. "
    "The schedule asks when an overdue project is NOW expected to finish, "
    "which is a fresh judgement rather than the original promise."
)

NOT_A_PROJECT_LEVEL_DISCLOSURE = (
    "Schedule III requires the ageing at the TOTAL level rather than per "
    "project, and the total must tie to the capital work-in-progress figure in "
    "the balance sheet. The per-project rows below are the working."
)


def _months_between(earlier: date, later: date) -> int:
    """Whole months from `earlier` to `later`, never negative.

    WHOLE months, counted on the calendar: 1 April to 31 March is eleven
    months and a day short of a year, so the amount is in the first band —
    which is what "outstanding for a period of less than 1 year" means. Days
    would have the same answer here and would disagree with themselves across
    a leap year, which is why `domain/gst/eway_validity` and this module both
    count units rather than days wherever the rule names a period.
    """
    if later < earlier:
        return 0
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    return max(0, months)


def bucket_for(incurred_on: date, as_of: date) -> str:
    months = _months_between(incurred_on, as_of)
    for name, lower, upper in BUCKETS:
        if (lower is None or months >= lower) and (upper is None or months < upper):
            return name
    return BUCKETS[-1][0]


@dataclass(frozen=True)
class Addition:
    """One tranche of cost, with the date the ageing is measured from."""
    cwip_id: str
    incurred_on: date
    amount_paise: int


@dataclass(frozen=True)
class Project:
    cwip_id: str
    name: str
    status: str
    started_on: date
    approved_completion_date: Optional[date] = None
    approved_cost_paise: Optional[int] = None
    expected_completion_date: Optional[date] = None
    capitalised_on: Optional[date] = None


@dataclass
class Ageing:
    as_of: date
    rows: dict = field(default_factory=dict)        # row -> bucket -> paise
    by_project: list = field(default_factory=list)
    total_paise: int = 0
    gaps: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "bucket_order": [b[0] for b in BUCKETS],
            "bucket_labels": dict(BUCKET_LABELS),
            "row_order": [IN_PROGRESS, SUSPENDED],
            "row_labels": dict(ROW_LABELS),
            "rows": {r: dict(b) for r, b in self.rows.items()},
            "by_project": list(self.by_project),
            "total_paise": self.total_paise,
            "gaps": list(self.gaps),
            "notes": list(self.notes),
        }


def _empty_row() -> dict:
    return {name: 0 for name, _l, _u in BUCKETS}


def in_cwip_at(project: Project, as_of: date) -> bool:
    """Whether the project was still capital work-in-progress on that date.

    AS AT A DATE, not as at now. A project capitalised in June is CWIP in a 31
    March note and a fixed asset in a 30 September one — the same discipline
    `stock_position_as_at` applies to the stock ledger, and the reason
    `capitalised_on` is recorded rather than the row being deleted.
    """
    if project.status == "abandoned":
        # An abandoned project was written off; the write-off is a journal the
        # CA raises and this module does not guess its date.
        return False
    if project.capitalised_on is not None and project.capitalised_on <= as_of:
        return False
    return True


def ageing(projects: Iterable[Project], additions: Iterable[Addition],
           *, as_of: date) -> Ageing:
    """The Schedule III CWIP ageing schedule as at a date."""
    out = Ageing(as_of=as_of)
    out.notes.append(NOT_A_PROJECT_LEVEL_DISCLOSURE)
    out.notes.append(CWIP_DOES_NOT_DEPRECIATE)

    live = {p.cwip_id: p for p in projects if in_cwip_at(p, as_of)}
    out.rows = {IN_PROGRESS: _empty_row(), SUSPENDED: _empty_row()}
    per_project: dict = {}

    for add in additions:
        project = live.get(add.cwip_id)
        if project is None:
            continue
        # An addition incurred AFTER the reporting date was not in CWIP then.
        if add.incurred_on > as_of:
            continue
        # A suspended project's balance is still in CWIP — it is the ROW that
        # differs, not the inclusion. Suspension is presentational, and reading
        # it as a removal would take the balance off the balance sheet.
        row = SUSPENDED if project.status == SUSPENDED else IN_PROGRESS
        bucket = bucket_for(add.incurred_on, as_of)
        out.rows[row][bucket] += int(add.amount_paise)
        out.total_paise += int(add.amount_paise)
        slot = per_project.setdefault(add.cwip_id, {
            "cwip_id": add.cwip_id, "project_name": project.name,
            "status": project.status, "total_paise": 0, **_empty_row()})
        slot[bucket] += int(add.amount_paise)
        slot["total_paise"] += int(add.amount_paise)

    # A live project with no cost yet is still listed, at nil. Dropping it
    # would make "no projects" and "no spend" look the same on a note whose
    # whole purpose is to show how long money has been sitting.
    for cwip_id, project in live.items():
        per_project.setdefault(cwip_id, {
            "cwip_id": cwip_id, "project_name": project.name,
            "status": project.status, "total_paise": 0, **_empty_row()})

    out.by_project = sorted(per_project.values(),
                            key=lambda r: (-r["total_paise"], r["project_name"]))
    return out


@dataclass
class CompletionSchedule:
    as_of: date
    rows: list = field(default_factory=list)
    buckets: dict = field(default_factory=_empty_row)
    gaps: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "bucket_order": [b[0] for b in BUCKETS],
            "bucket_labels": dict(BUCKET_LABELS),
            "rows": list(self.rows),
            "buckets": dict(self.buckets),
            "gaps": list(self.gaps),
        }


def reportable_reason(project: Project, spent_paise: int, as_of: date) -> Optional[str]:
    """Why this project appears in the completion schedule, or None.

    OVERDUE or OVER COST — Schedule III names both and either is enough. The
    test is against the ORIGINAL approval in each case, which is the one thing
    that cannot be derived: the start date is not an approved completion date
    and what has been spent is not an approved cost.
    """
    reasons = []
    if (project.approved_completion_date is not None
            and as_of > project.approved_completion_date):
        reasons.append("overdue against its approved completion date of "
                       f"{project.approved_completion_date.isoformat()}")
    if (project.approved_cost_paise is not None
            and spent_paise > int(project.approved_cost_paise)):
        reasons.append("cost has exceeded the approved "
                       f"{project.approved_cost_paise} paise")
    return " and ".join(reasons) or None


def completion_schedule(projects: Iterable[Project], additions: Iterable[Addition],
                        *, as_of: date) -> CompletionSchedule:
    """Projects overdue or over budget, and when each is now expected to finish."""
    out = CompletionSchedule(as_of=as_of)
    spent: dict = {}
    for add in additions:
        if add.incurred_on <= as_of:
            spent[add.cwip_id] = spent.get(add.cwip_id, 0) + int(add.amount_paise)

    for project in projects:
        if not in_cwip_at(project, as_of):
            continue
        incurred = spent.get(project.cwip_id, 0)

        if (project.approved_completion_date is None
                and project.approved_cost_paise is None):
            out.gaps.append(f"{project.name}: {APPROVAL_NOT_RECORDED}")
            continue

        reason = reportable_reason(project, incurred, as_of)
        if reason is None:
            continue

        if project.expected_completion_date is None:
            # NAMED rather than bucketed. A project reported in the schedule
            # with no band states nothing; one put in "more than 3 years"
            # because nobody said otherwise states something false.
            out.gaps.append(f"{project.name}: {EXPECTED_DATE_NOT_RECORDED}")
            bucket = None
        else:
            bucket = bucket_for(as_of, project.expected_completion_date)
            out.buckets[bucket] += incurred

        out.rows.append({
            "cwip_id": project.cwip_id,
            "project_name": project.name,
            "status": project.status,
            "reason": reason,
            "incurred_paise": incurred,
            "approved_cost_paise": project.approved_cost_paise,
            "approved_completion_date": (project.approved_completion_date.isoformat()
                                         if project.approved_completion_date else None),
            "expected_completion_date": (project.expected_completion_date.isoformat()
                                         if project.expected_completion_date else None),
            "bucket": bucket,
        })
    return out
