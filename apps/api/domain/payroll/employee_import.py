"""
The employee bulk import — whole file, one decision.

WHAT IT REPLACES, AND WHY THAT WAS WRONG THREE WAYS

`apps/web/lib/imports/mappers.buildEmployees` validated a spreadsheet in the
BROWSER and the screen then POSTed one employee at a time in a loop. Three
separate problems, and the third is the one that hurt:

  1. It is business logic in the frontend, which the house rules forbid outright.
     PAN's shape, Aadhaar's truncation to four digits, the default HRA of 40% —
     all statutory or near-statutory, all decided in a place the backend cannot
     see and a second client would have to reimplement.

  2. It is one round trip per employee. `apps/api` runs in Singapore and Postgres
     is in Mumbai, so a fifty-row file was fifty cross-region round trips.

  3. IT ACCEPTED PART OF A FILE. Rows that validated were posted; rows that did
     not were listed as errors — and the CA was left with, say, thirty-one of
     fifty employees on the system and no way to tell which nineteen were
     missing except by comparing by hand. Fixing the file and re-importing then
     created a SECOND copy of the thirty-one, because nothing identified an
     employee across two imports.

     A payroll with a duplicated employee pays them twice, reports them twice on
     the ECR under one UAN, and issues two Form 16s.

SO: WHOLE-FILE VALIDATION, WHOLE-FILE REFUSAL

`validate` reads the entire file and returns EVERY problem it found, keyed to
the row the CA can see in their spreadsheet. If there is a single problem,
nothing is written. A spreadsheet is edited and re-uploaded in seconds; a
half-imported payroll is unpicked by hand.

The refusal is deliberately not "strict mode" — there is no lenient mode to
turn on. A partial import of a payroll master is never the outcome anybody
wanted; it is what happens when nobody decided.

AND IDEMPOTENT ON employee_code

Migration 333 added `payroll_employees.employee_code`, unique per client. An
imported row whose code is already on file UPDATES that employee; a row with a
new code, or no code at all, creates one. So re-importing a corrected file is
safe, which is the only way "fix the spreadsheet and upload it again" can be
the answer to a refusal.

A file that repeats a code WITHIN itself is refused, because the two rows
disagree about one person and nothing here can know which is meant.

WHAT IT VALIDATES, AND WHAT IT LEAVES ALONE

It checks the things a statutory output will otherwise reject after upload, when
the CA has already lost the round trip: PAN's shape (§139A / Rule 114B), UAN's
twelve digits (the ECR's mandatory field), the IFSC's format, Aadhaar reduced to
its last four digits and never stored whole, a date of birth that is a date and
is in the past.

It does NOT check that a PAN exists, that a UAN belongs to this person, or that
the bank account is real. Those are facts about the world, and a payroll master
is allowed to be built before every one of them is known — which is why the
columns stay nullable and only their SHAPE is enforced.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from core.validators import validate_pan

UAN_RE = re.compile(r"^\d{12}$")
# RBI's format: four letters (bank), '0' reserved, six alphanumerics (branch).
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
AADHAAR_RE = re.compile(r"^\d{12}$")

#: (column, whether the file must carry it). The header a CA is given.
COLUMNS: list[tuple[str, bool]] = [
    ("employee_code", False),
    ("name", True),
    ("pan", False),
    ("date_of_birth", False),
    ("gender", False),
    ("designation", False),
    ("department", False),
    ("joining_date", False),
    ("basic", True),
    ("hra_percent", False),
    ("da_percent", False),
    ("other_allowances", False),
    ("lta", False),
    ("medical", False),
    ("special_allowance", False),
    ("uan", False),
    ("esi_number", False),
    ("aadhaar", False),
    ("pf_applicable", False),
    ("esi_applicable", False),
    ("pt_applicable", False),
    ("pt_state", False),
    ("bank_account_no", False),
    ("bank_ifsc", False),
    ("bank_name", False),
]

REQUIRED = [c for c, req in COLUMNS if req]

#: HRA where the file says nothing. 40% is the non-metro §10(13A) limb and is
#: what the browser importer used, so an existing template keeps working.
DEFAULT_HRA_PERCENT = 40.0

_TRUE = {"y", "yes", "true", "1", "t"}
_FALSE = {"n", "no", "false", "0", "f"}


@dataclass
class ImportResult:
    """Every problem in the file, and the rows that would be written.

    `problems` empty is the ONLY condition under which anything is written.
    `to_create` / `to_update` are populated regardless, so a dry run can show a
    CA what a clean file would do before they commit to it.
    """
    problems: list[str] = field(default_factory=list)
    to_create: list[dict] = field(default_factory=list)
    to_update: list[tuple[str, dict]] = field(default_factory=list)  # (id, payload)

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> dict:
        return {
            "ok": self.ok,
            "problems": self.problems,
            "would_create": len(self.to_create),
            "would_update": len(self.to_update),
        }


def _text(row: dict, key: str) -> str:
    v = row.get(key)
    return "" if v is None else str(v).strip()


def _bool(row: dict, key: str, default: bool) -> tuple[Optional[bool], Optional[str]]:
    raw = _text(row, key).lower()
    if not raw:
        return default, None
    if raw in _TRUE:
        return True, None
    if raw in _FALSE:
        return False, None
    return None, f'{key} must be yes or no, got "{_text(row, key)}"'


def _paise(row: dict, key: str) -> tuple[Optional[int], Optional[str]]:
    """A rupee amount from a spreadsheet cell, as integer paise.

    Digits are CONCATENATED rather than multiplied by 100, for the reason
    apps/web/lib/money/rupeeInput.ts exists: float(x) * 100 on "1145.30" is
    114529.99999999999. Grouping is stripped because a spreadsheet exports
    "1,25,000" and a CA typing Indian amounts groups them — the browser's old
    parseFloat read that as 1.
    """
    raw = _text(row, key).replace(",", "").replace("₹", "").strip()
    if not raw:
        return 0, None
    neg = raw.startswith("-")
    if neg:
        raw = raw[1:]
    if not re.fullmatch(r"\d+(\.\d{0,2})?", raw):
        return None, f'{key} must be an amount in rupees, got "{_text(row, key)}"'
    if "." in raw:
        rupees, paise = raw.split(".")
        paise = (paise + "00")[:2]
    else:
        rupees, paise = raw, "00"
    value = int(rupees or "0") * 100 + int(paise)
    return (-value if neg else value), None


def _percent(row: dict, key: str, default: float) -> tuple[Optional[float], Optional[str]]:
    raw = _text(row, key).replace("%", "").replace(",", "").strip()
    if not raw:
        return default, None
    if not re.fullmatch(r"\d+(\.\d+)?", raw):
        return None, f'{key} must be a non-negative percentage, got "{_text(row, key)}"'
    return float(raw), None


def _date(row: dict, key: str) -> tuple[Optional[str], Optional[str]]:
    """An ISO date, or a named problem. Accepts DD/MM/YYYY and DD-MM-YYYY too.

    DAY FIRST, not month first. A spreadsheet in India writes 03/04/1985 for
    3 April, and reading it as 4 March moves a date of birth by a month —
    which, for someone born in March, is exactly the case that decides whether
    they were sixty during the year. ISO is accepted unambiguously and is what
    the column stores.
    """
    raw = _text(row, key)
    if not raw:
        return None, None
    for pattern, order in ((r"^(\d{4})-(\d{2})-(\d{2})$", "ymd"),
                           (r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", "dmy")):
        m = re.match(pattern, raw)
        if not m:
            continue
        a, b, c = m.groups()
        y, mo, d = (a, b, c) if order == "ymd" else (c, b, a)
        try:
            return date(int(y), int(mo), int(d)).isoformat(), None
        except ValueError:
            return None, f'{key} is not a real date: "{raw}"'
    return None, f'{key} must be a date as YYYY-MM-DD or DD/MM/YYYY, got "{raw}"'


def validate(rows: list[dict], *, existing_by_code: dict) -> ImportResult:
    """Read the whole file and decide once.

    `existing_by_code` maps an employee_code already on file for this client to
    its row id — the caller reads it in ONE query, which is what makes the
    import idempotent without a lookup per row.
    """
    result = ImportResult()
    if not rows:
        result.problems.append("The file has no rows.")
        return result

    seen_codes: dict[str, int] = {}

    for index, raw_row in enumerate(rows):
        # Row 1 is the first DATA row as the CA sees it in their spreadsheet
        # under a header — an off-by-one here sends them to the wrong line.
        n = index + 1
        row = {str(k).strip().lower(): v for k, v in (raw_row or {}).items()}
        problems: list[str] = []

        name = _text(row, "name")
        if not name:
            problems.append(f"Row {n}: name is required")

        code = _text(row, "employee_code")
        if code:
            if code.lower() in seen_codes:
                problems.append(
                    f"Row {n}: employee_code \"{code}\" is also on row "
                    f"{seen_codes[code.lower()]} — two rows for one person, and "
                    f"nothing here can know which is meant")
            else:
                seen_codes[code.lower()] = n

        basic, err = _paise(row, "basic")
        if err:
            problems.append(f"Row {n}: {err}")
        elif basic is not None and basic <= 0:
            problems.append(f"Row {n}: basic must be greater than zero")

        pan = _text(row, "pan").upper() or None
        if pan:
            pan_err = validate_pan(pan)
            if pan_err:
                problems.append(f"Row {n}: {pan_err}")

        uan = _text(row, "uan") or None
        if uan and not UAN_RE.match(uan):
            # The ECR rejects this AFTER upload, by which time the round trip is
            # lost — domain/payroll/ecr.py checks the same thing at file build.
            problems.append(f'Row {n}: UAN must be 12 digits, got "{uan}"')

        ifsc = _text(row, "bank_ifsc").upper() or None
        if ifsc and not IFSC_RE.match(ifsc):
            problems.append(f'Row {n}: bank IFSC must look like HDFC0001234, got "{ifsc}"')

        # Aadhaar is reduced to its last four digits HERE and the full number is
        # never placed on the payload — the same UIDAI rule models/payroll.py
        # enforces on the single-employee path.
        aadhaar_last4 = None
        aadhaar = re.sub(r"\D", "", _text(row, "aadhaar"))
        if aadhaar:
            if not AADHAAR_RE.match(aadhaar):
                problems.append(f"Row {n}: Aadhaar must be 12 digits")
            else:
                aadhaar_last4 = aadhaar[-4:]

        dob, err = _date(row, "date_of_birth")
        if err:
            problems.append(f"Row {n}: {err}")
        elif dob and dob >= date.today().isoformat():
            problems.append(f"Row {n}: date_of_birth {dob} is not in the past")

        joining, err = _date(row, "joining_date")
        if err:
            problems.append(f"Row {n}: {err}")

        hra, err = _percent(row, "hra_percent", DEFAULT_HRA_PERCENT)
        if err:
            problems.append(f"Row {n}: {err}")
        da, err = _percent(row, "da_percent", 0.0)
        if err:
            problems.append(f"Row {n}: {err}")

        amounts: dict[str, int] = {}
        for column, field_name in (("other_allowances", "other_allowances_paise"),
                                   ("lta", "lta_paise"),
                                   ("medical", "medical_paise"),
                                   ("special_allowance", "special_allowance_paise")):
            value, err = _paise(row, column)
            if err:
                problems.append(f"Row {n}: {err}")
            elif value is not None and value < 0:
                problems.append(f"Row {n}: {column} may not be negative")
            else:
                amounts[field_name] = value or 0

        flags: dict[str, bool] = {}
        for column, field_name, default in (("pf_applicable", "pf_applicable", True),
                                            ("esi_applicable", "esi_applicable", True),
                                            ("pt_applicable", "pt_applicable", False)):
            value, err = _bool(row, column, default)
            if err:
                problems.append(f"Row {n}: {err}")
            else:
                flags[field_name] = bool(value)

        if problems:
            result.problems.extend(problems)
            continue

        payload = {
            "name": name,
            "employee_code": code or None,
            "pan": pan,
            "date_of_birth": dob,
            "gender": _text(row, "gender").lower() or None,
            "designation": _text(row, "designation") or None,
            "department": _text(row, "department") or None,
            "joining_date": joining,
            "basic_paise": basic or 0,
            "hra_percent": hra,
            "da_percent": da,
            "uan": uan,
            "esi_number": _text(row, "esi_number") or None,
            "aadhaar_last4": aadhaar_last4,
            "pt_state": _text(row, "pt_state").upper() or None,
            "bank_account_no": _text(row, "bank_account_no") or None,
            "bank_ifsc": ifsc,
            "bank_name": _text(row, "bank_name") or None,
            **amounts,
            **flags,
        }

        existing_id = existing_by_code.get(code.lower()) if code else None
        if existing_id:
            result.to_update.append((existing_id, payload))
        else:
            result.to_create.append(payload)

    # A file that validated row by row can still be refused as a whole: the
    # duplicate-code check above is a FILE-level fact, not a row-level one.
    return result


def template_csv() -> str:
    """The header row, so a CA starts from the columns this actually reads.

    Header only. A template with example rows in it gets uploaded WITH the
    examples still in, and "Ravi Kumar, 50000" becomes an employee.
    """
    return ",".join(name for name, _required in COLUMNS) + "\n"
