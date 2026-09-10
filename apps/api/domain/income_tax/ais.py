"""The Annual Information Statement, parsed — IT Act §285BB.

WHY THIS IS NOT A BROWSER PARSER ANY MORE

    apps/web/app/income-tax/ais/page.tsx held the whole thing: a JSON parser, a
    transaction table and a books-comparison grid, in React state, with no call
    to anything. Refresh and it was gone.

    That is the same shape as the 24Q the browser used to assemble
    (`generateTds24QData`) and the GST reconciliation the browser used to do —
    both deleted, both for the same reason. A statement the Income-tax
    Department publishes about a client is evidence: it is what a §143(1)(a)
    adjustment is raised from and what a §143(3) scrutiny starts with. Evidence
    that cannot be re-read tomorrow is not evidence.

WHAT AIS IS, AND WHAT IT IS NOT

    §285BB: the department's statement of what OTHERS reported about the
    taxpayer — banks, employers, registrars, mutual funds. It is NOT the
    client's books and it is not authoritative about them. A difference is a
    question, never a finding, and this module computes no difference at all:
    it reads the file and stops. The books figure is a CA's, and
    `ais_reconciliations.books_amount_paise` is where it goes.

    That refusal is deliberate and recent. detect_document_risks used to invent
    the book income as 85% of the AIS income and report the gap as a risk.

AMOUNTS

    An AIS row whose amount cannot be READ is not a zero. A zero here says the
    payer reported nothing, which is the opposite conclusion and the exact
    thing this reconciliation exists to establish. So an unreadable amount is a
    PROBLEM naming the row, and the row is not silently valued.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Optional


# The buckets the product sorts a line into. The portal's own wording is kept
# verbatim beside it (information_label) because a bucket is a lossy reading
# and the wording is what a CA searches the statement for.
TRANSACTION_TYPES = (
    "Salary", "Interest", "Dividend", "Stock Sale", "Property Sale",
    "Foreign Remittance", "Rent Received", "Other",
)

_TYPE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Salary", ("salary",)),
    ("Interest", ("interest",)),
    ("Dividend", ("dividend",)),
    ("Stock Sale", ("securities", "stock", "shares", "mutual fund", "equity")),
    ("Property Sale", ("property", "immovable")),
    ("Foreign Remittance", ("foreign", "remittance")),
    ("Rent Received", ("rent",)),
)

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def classify(label: str) -> str:
    """Which bucket a line's own wording puts it in.

    Order matters and is not alphabetical: "TDS on salary" contains neither
    "interest" nor "dividend", but "Interest from deposit with a salary
    account" contains both "interest" and "salary". Salary is tested first
    because the AIS category for it is worded around the deductor, and the
    interest categories name the instrument.
    """
    text = str(label or "").lower()
    for bucket, needles in _TYPE_HINTS:
        if any(n in text for n in needles):
            return bucket
    return "Other"


def rupees_to_paise(value: Any) -> Optional[int]:
    """Integer paise, or None when the value is not an amount.

    NEVER FLOAT (project rupee rule). The portal writes amounts as JSON
    numbers and as strings with grouping, and both go through Decimal — a
    float round-trip on "12345.67" is what puts a paise out on a figure a
    return is checked against.

    None is the refusal, and the caller must not turn it into 0.
    """
    if value is None or value == "":
        return 0
    text = str(value).strip().replace(",", "").replace("₹", "")
    text = text.replace(" ", "")
    if not text:
        return 0
    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        return None
    try:
        return int((Decimal(text) * 100).to_integral_value())
    except (InvalidOperation, ValueError):
        return None


@dataclass
class AISRecord:
    information_source: str = ""
    information_label: str = ""
    transaction_type: str = "Other"
    payer: str = ""
    amount_paise: int = 0
    tds_deducted_paise: int = 0
    source: str = "json"


@dataclass
class ParsedAIS:
    pan: Optional[str] = None
    taxpayer_name: Optional[str] = None
    records: list[AISRecord] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def total_amount_paise(self) -> int:
        return sum(r.amount_paise for r in self.records)

    @property
    def total_tds_paise(self) -> int:
        return sum(r.tds_deducted_paise for r in self.records)

    @property
    def is_usable(self) -> bool:
        """A file that parsed with problems is not a file that parsed.

        The records that DID read are still returned — a CA looking at a
        statement wants to see the nineteen lines that were fine as well as
        the one that was not — but nothing should be persisted as a complete
        reconciliation while a line is unaccounted for.
        """
        return not self.problems and bool(self.records)


def _label_from(descriptions: list, keys: tuple[str, ...]) -> str:
    for entry in descriptions or []:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label") or "").lower()
        if any(k in label for k in keys):
            return str(entry.get("value") or "")
    return ""


def parse(raw: str) -> ParsedAIS:
    """One AIS JSON as downloaded from the portal.

    Refuses rather than guessing at every step. A file that is not JSON, or is
    JSON of some other shape, comes back with a problem and no records — never
    an empty statement, which a CA would read as "this client had no reported
    transactions".
    """
    out = ParsedAIS()
    try:
        root = json.loads(raw)
    except (ValueError, TypeError):
        out.problems.append(
            "This file is not JSON. Download the AIS in JSON form from the "
            "income-tax portal — the PDF cannot be read here.")
        return out
    if not isinstance(root, dict):
        out.problems.append("This file is JSON but not an AIS statement.")
        return out

    statement = root.get("AnnualInformationStatement")
    if not isinstance(statement, dict):
        out.problems.append(
            "No AnnualInformationStatement block — this does not look like an "
            "AIS download (IT Act §285BB).")
        return out

    taxpayer = statement.get("taxpayerInfo") or {}
    if isinstance(taxpayer, dict):
        pan = str(taxpayer.get("pan") or "").strip().upper()
        out.pan = pan if PAN_RE.fullmatch(pan) else None
        if pan and out.pan is None:
            out.problems.append(
                f"The PAN in this file, {pan!r}, is not a PAN. It is quoted on "
                f"the statement and is the first thing to check against the "
                f"client's own.")
        out.taxpayer_name = str(taxpayer.get("name") or "").strip() or None

    categories = ((statement.get("aisInformation") or {})
                  .get("aisSubInformationCategory"))
    if not isinstance(categories, list):
        out.problems.append(
            "No aisSubInformationCategory list — the statement carries no "
            "information categories.")
        return out

    for index, cat in enumerate(categories, start=1):
        if not isinstance(cat, dict):
            out.problems.append(f"Row {index} is not a record.")
            continue
        descriptions = cat.get("informationDescription") or []
        label = (_label_from(descriptions, ("nature", "type"))
                 or str(cat.get("informationSource") or "")
                 or "Other")
        amount = rupees_to_paise(cat.get("amount", cat.get("informationValue")))
        tds = rupees_to_paise(cat.get("tdsAmount"))
        source_name = str(cat.get("informationSource") or "unknown source")
        if amount is None or tds is None:
            # NOT a zero. A zero says the payer reported nothing.
            out.problems.append(
                f"Row {index} ({source_name}) carries an amount this file "
                f"cannot read, so the row is not valued.")
            continue
        out.records.append(AISRecord(
            information_source=source_name,
            information_label=label,
            transaction_type=classify(label),
            payer=(_label_from(descriptions, ("deductor", "payer", "source"))
                   or source_name),
            amount_paise=amount,
            tds_deducted_paise=tds,
            source="json",
        ))

    if not out.records and not out.problems:
        out.problems.append(
            "The statement parsed and carries no information categories at "
            "all. That is a real answer for a client with nothing reported — "
            "confirm it is the right assessment year before relying on it.")
    return out


def file_hash(raw: str) -> str:
    """SHA-256 of the bytes uploaded.

    A re-upload of the SAME file is the ordinary case — a CA re-downloads to
    check — and must be recognised rather than duplicated. A DIFFERENT file for
    the same assessment year is a fresh statement and gets its own row.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
