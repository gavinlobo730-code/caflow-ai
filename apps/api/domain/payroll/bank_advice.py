"""The salary payment advice — a file a human uploads to their bank (PAY-27).

WHAT WAS MISSING

    `payroll_employees.bank_account_no` and `bank_ifsc` have been collected
    since the module was built, `domain/payroll/register.py` carries both in
    its column list, and NOTHING read them. So after finalising a run the CA
    exported the register to Excel, deleted twenty-five columns, renamed four
    and built the bank file by hand — every month, for every client — which is
    the one step between computing the payroll and the employees being paid.

THIS FILE MOVES NO MONEY, AND THAT IS STRUCTURAL RATHER THAN A PROMISE

    It is a CSV the CA downloads and uploads to their own bank's portal, where
    their own authorised signatory approves it. Nothing here reaches a bank,
    holds a credential or schedules anything — the same posture the whole
    product takes to a government portal, for the same reason. A payment file
    generated is not a payment made, and the wording on every answer says so.

ONLY A RELEASED RUN, AND THIS IS THE SHARPEST REFUSAL IN THE MODULE

    PAY-04's rule is that a DRAFT run has deducted nothing and paid nobody. A
    bank advice built from a draft is an instruction to pay figures nobody has
    approved, into a file whose whole purpose is that somebody uploads it
    without re-reading every line. `_PAYROLL_RELEASED` (`finalized`, `paid`) is
    the gate and `refusal_for_status` is the one place that decides it.

AN EMPLOYEE WHO CANNOT BE PAID BY TRANSFER IS NAMED, NEVER EMITTED BLANK

    A row with no account number, or no IFSC, or an IFSC that is not one, is
    held OUT of the file and reported. Banks differ in what they do with a
    malformed row — some reject the upload whole, some process the rest and
    drop it silently — and the second is the dangerous one: the CA believes
    everybody was paid. So the file carries only rows a bank can act on, and
    the response says exactly who is missing and what is missing about them.

    Nil net pay is its own case and is also held out: a full-month LOP or a
    recovery that consumed the whole salary produces a genuine zero, and a
    zero-value transfer is not a payment instruction. NEGATIVE net pay is
    refused louder — it means the recoveries exceeded the salary, which is a
    payroll to look at rather than a transfer to make.

THE BANK-SPECIFIC LAYOUTS ARE NAMED AND NOT INVENTED

    Every bank's bulk-transfer upload has its own column order, its own header
    row and its own transaction-type code — HDFC, ICICI, SBI, Axis and Kotak
    all differ — and those layouts move. Writing one from memory produces a
    file that looks right and is rejected at upload, which is worse than a
    generic one the CA maps once: the mapping is a five-minute job done once
    per client, and a wrong layout is a failed payment run on the 1st.

    So this emits ONE generic layout carrying the five fields every format
    contains, and `LAYOUTS_NOT_HELD` says so on every answer. Adding a bank is
    a human step, like the state PT slabs and the ITR schemas.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Optional

from domain.payroll.identity import IFSC_RE

#: A run that has actually paid somebody. The same tuple payroll's own readers
#: use — imported rather than restated, because two spellings of "released" is
#: how a fifth status silently joins one of them.
_RELEASED = ("finalized", "paid")

MOVES_NO_MONEY = (
    "This file is prepared, not sent. Download it, upload it to your bank's "
    "own bulk-transfer portal, and have your authorised signatory approve it "
    "there. Nothing in this product reaches a bank."
)

LAYOUTS_NOT_HELD = (
    "This is a generic layout. Every bank's bulk-transfer upload has its own "
    "column order, header row and transaction-type code, and those move — a "
    "layout written from memory is a file that looks right and is rejected at "
    "upload. Map these five columns to your bank's template once per client."
)

DRAFT_HAS_PAID_NOBODY = (
    "This payroll run has not been released, so its figures are not what "
    "anybody has approved. Finalise the run before preparing a payment file."
)

#: The five fields every bulk-transfer format carries, in the order a person
#: reads them. Written down once so the file a CA maps in April is the file
#: they get in August.
COLUMNS: list[tuple[str, str]] = [
    ("Beneficiary Name",   "beneficiary_name"),
    ("Account Number",     "account_no"),
    ("IFSC",               "ifsc"),
    ("Amount",             "amount"),
    ("Narration",          "narration"),
]

#: Why a row cannot be paid by transfer. Each is a DIFFERENT thing for the CA
#: to go and do, so they are not one "invalid" bucket.
NO_ACCOUNT = "no_account_number"
NO_IFSC = "no_ifsc"
BAD_IFSC = "malformed_ifsc"
NIL_NET = "nil_net_pay"
NEGATIVE_NET = "negative_net_pay"

WHY = {
    NO_ACCOUNT: ("No bank account number is recorded for this employee. "
                 "Record it on the employee master."),
    NO_IFSC: ("No IFSC is recorded for this employee's bank branch. Record it "
              "on the employee master."),
    BAD_IFSC: ("The recorded IFSC is not an IFSC — RBI's format is four "
               "letters, then 0, then six alphanumeric characters. Correct it "
               "on the employee master."),
    NIL_NET: ("Net pay for the month is nil — a full month of loss of pay, or "
              "recoveries equal to the salary. A zero-value transfer is not a "
              "payment instruction, so this employee is not in the file."),
    NEGATIVE_NET: ("Net pay for the month is NEGATIVE: the recoveries exceed "
                   "the salary. That is a payroll to look at rather than a "
                   "transfer to make, and no bank file can express it."),
}


@dataclass(frozen=True)
class Payee:
    employee_id: str
    name: str
    account_no: str
    ifsc: str
    net_paise: int


@dataclass
class Excluded:
    employee_id: str
    name: str
    reason: str
    net_paise: int = 0

    def to_dict(self) -> dict:
        return {"employee_id": self.employee_id, "name": self.name,
                "reason": self.reason, "why": WHY.get(self.reason, ""),
                "net_paise": self.net_paise}


@dataclass
class Advice:
    month: str
    payable: list = field(default_factory=list)
    excluded: list = field(default_factory=list)
    total_paise: int = 0
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "rows": [{"employee_id": p.employee_id, "name": p.name,
                      # The account number is MASKED in the JSON the screen
                      # renders and is whole in the FILE the bank reads. A
                      # screen showing thirty account numbers in full is a
                      # shoulder-surfing surface for no gain — the CA is
                      # checking the amount and the name, not re-typing the
                      # account.
                      "account_no_masked": mask_account(p.account_no),
                      "ifsc": p.ifsc, "net_paise": p.net_paise}
                     for p in self.payable],
            "excluded": [e.to_dict() for e in self.excluded],
            "payable_count": len(self.payable),
            "excluded_count": len(self.excluded),
            "total_paise": self.total_paise,
            "notes": list(self.notes),
        }


def mask_account(account_no: str) -> str:
    """Last four digits, the convention a bank statement itself uses."""
    digits = re.sub(r"\s+", "", str(account_no or ""))
    if len(digits) <= 4:
        return digits
    return "x" * (len(digits) - 4) + digits[-4:]


def refusal_for_status(status: Optional[str]) -> Optional[str]:
    """Why this run may not produce a payment file, or None.

    The ONE place the released test is made, so a second door cannot answer it
    differently — and it takes the status rather than the run, so nothing here
    can reach into a row for a second reason.
    """
    if str(status or "").strip().lower() not in _RELEASED:
        return DRAFT_HAS_PAID_NOBODY
    return None


def _problem_with(account_no: str, ifsc: str, net_paise: int) -> Optional[str]:
    """Why this employee cannot be paid by transfer, or None.

    ORDER MATTERS AND THE MONEY IS ASKED LAST. An employee with no bank
    details AND nil net pay has two problems and only one that the CA can do
    anything about this month — recording the account is the durable fix, and
    reporting the nil instead would have them come back to it next month.
    """
    if not str(account_no or "").strip():
        return NO_ACCOUNT
    ifsc_text = str(ifsc or "").strip().upper()
    if not ifsc_text:
        return NO_IFSC
    if not IFSC_RE.match(ifsc_text):
        return BAD_IFSC
    if int(net_paise or 0) < 0:
        return NEGATIVE_NET
    if int(net_paise or 0) == 0:
        return NIL_NET
    return None


def build(slips, month: str, run_status: Optional[str]) -> Advice:
    """The advice for one run's slips.

    `slips` are `payroll_slips` rows with `payroll_employees` joined, exactly
    as `domain/payroll/register.flatten` expects — one shape for both readings
    of a run, so the register and the bank file cannot disagree about who was
    paid what.

    `run_status` IS REQUIRED AND HAS NO DEFAULT, and `None` refuses. A caller
    that did not establish the run is released has not established it, and on
    a payment file the direction of an unstated fact is not a judgement call:
    the file's whole purpose is that somebody uploads it without re-reading
    every line. Making the parameter required is the structural half — nobody
    can forget it — and making None refuse is the backstop for a caller that
    passes what it has.
    """
    out = Advice(month=month, notes=[MOVES_NO_MONEY, LAYOUTS_NOT_HELD])
    refusal = refusal_for_status(run_status)
    if refusal:
        out.notes.insert(0, refusal)
        return out

    for slip in slips:
        emp = slip.get("payroll_employees") or {}
        employee_id = str(slip.get("employee_id") or "")
        name = str(emp.get("name") or "").strip()
        account_no = str(emp.get("bank_account_no") or "").strip()
        ifsc = str(emp.get("bank_ifsc") or "").strip().upper()
        net = int(slip.get("net_paise") or 0)

        problem = _problem_with(account_no, ifsc, net)
        if problem:
            out.excluded.append(Excluded(employee_id=employee_id, name=name,
                                         reason=problem, net_paise=net))
            continue
        out.payable.append(Payee(employee_id=employee_id, name=name,
                                 account_no=account_no, ifsc=ifsc,
                                 net_paise=net))
        out.total_paise += net

    # Largest first: a CA scanning a payment file checks the big numbers.
    out.payable.sort(key=lambda p: (-p.net_paise, p.name.lower()))
    out.excluded.sort(key=lambda e: e.name.lower())
    if out.excluded:
        out.notes.append(
            f"{len(out.excluded)} employee(s) are NOT in this file and will "
            f"not be paid by it. Each is named with what is missing.")
    return out


def _rupees(paise) -> str:
    """Integer paise to a plain two-decimal rupee string.

    `domain/payroll/register._rupees`'s rule and its reason: no thousands
    separators and no symbol, because a bank upload is parsed by a program and
    `1,25,000` is what makes a parser read one rupee.
    """
    p = int(paise or 0)
    sign = "-" if p < 0 else ""
    p = abs(p)
    return f"{sign}{p // 100}.{p % 100:02d}"


def to_csv(advice: Advice, narration: str = "") -> bytes:
    """The payable rows as a bank-uploadable CSV.

    ONLY THE PAYABLE ROWS. An excluded employee is not a row with blanks in
    it — some banks reject the whole upload on a malformed row and some drop
    it silently, and the second leaves a CA believing everybody was paid.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([h for h, _k in COLUMNS])
    for p in advice.payable:
        writer.writerow([
            p.name,
            p.account_no,
            p.ifsc,
            _rupees(p.net_paise),
            narration or f"Salary {advice.month}",
        ])
    return buf.getvalue().encode("utf-8")
