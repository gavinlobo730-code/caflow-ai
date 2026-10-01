"""
What a document reading is allowed to look like, checked on arrival. (ai-05, ai-16)

WHAT WAS WRONG
    The invoice reader did `json.loads(reply)` and then `int(data.get(field) or 0)`
    on five fields, trusting every key it did not touch; the notice reader did
    `json.loads(reply)` and then `extracted.get("notice_type", "other")`,
    `.get("response_due_date")`, and stored whatever was there. A model that
    returned a list, a string where an amount belongs, `"N/A"` for a total, a
    notice type that is not one the product has, or a due date no notice could
    carry, reached either a generic "AI extraction failed" (the parse raising
    somewhere unhelpful) or — worse, on the notice side — the database and a
    task's due date.

WHAT THIS IS
    A pydantic model per document kind and a `parse_*` that turns the model's
    reply into either a dict the routers already know how to use or an
    `ExtractionRefused` with a sentence saying what was wrong. The same module
    holds the JSON schema each provider is asked to honour, written next to the
    model so a test can hold the two to the same field list.

    The schema is a HINT (the gateway sends it only where the provider documents
    it, and drops it if the provider objects); the pydantic model is the CHECK,
    and runs on every reply from every model.

WHAT IT REFUSES AND WHAT IT LEAVES UNREAD
    A reply that is not a JSON object, an amount that is not a whole number of
    paise, a negative header amount, lines that are not objects: REFUSED — the
    reading is unusable and there is nothing honest to fill in.
    A header date that is not `YYYY-MM-DD`, or a notice date that is not: UNREAD
    (None), named in `not_read`, because an absent value is unknown and an
    unknown is never rendered as a value (AI-01's rule, applied to the header).
    A notice whose dates cannot be right — a response due before the notice was
    issued, or ten years in the past, or two years after issue — is REFUSED, and
    that is the rule that stops a hostile or garbled notice setting a deadline:
    a CA would see a wrong date as a real one, and a task would carry it.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from domain.ai.gateway import JsonSchema
from domain.extraction_lines import read_line


class ExtractionRefused(Exception):
    """A reply that cannot be accepted as a reading. `sentence` is for the person
    who uploaded the document; `http_status` is what the API answers with (502 —
    the model's reply was unusable — unless the caller says otherwise)."""

    def __init__(self, sentence: str, *, http_status: int = 502) -> None:
        super().__init__(sentence)
        self.sentence = sentence
        self.http_status = http_status


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: A header amount above this is not an invoice's figure, it is a misread: ten
#: thousand crore rupees, in paise. A ceiling, not a rule about size.
MAX_PAISE = 10 ** 15
MAX_LINES = 500

HEADER_AMOUNTS = ("taxable_amount_paise", "cgst_paise", "sgst_paise", "igst_paise", "total_paise")


def _iso_date(value: Any) -> tuple[Optional[date], bool]:
    """(the date, whether something was printed that could not be read as one)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, False
    if isinstance(value, str) and _ISO_DATE.match(value.strip()):
        try:
            return date.fromisoformat(value.strip()), False
        except ValueError:
            return None, True
    return None, True


def load_json_object(raw: Any, *, what: str, nothing: str = "filled in") -> dict:
    """The reply as a JSON OBJECT, or a refusal. Strips a markdown fence, because
    models wrap JSON in one more often than not; salvages nothing else — a reply
    that is prose around an object is not a reading, and picking an object out of
    it would be a guess about which one the model meant."""
    if not isinstance(raw, str):
        raise ExtractionRefused(f"The AI sent no text to read as {what}. Nothing was {nothing}.")
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else ""
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        obj = json.loads(text)
    except ValueError as exc:
        raise ExtractionRefused(
            f"The AI's reply could not be read as {what} (it was not valid JSON). Nothing "
            f"was {nothing}; try again, or enter the details by hand.") from exc
    if not isinstance(obj, dict):
        raise ExtractionRefused(
            f"The AI's reply could not be read as {what} (it was a "
            f"{type(obj).__name__}, not an object). Nothing was {nothing}; try again, or "
            "enter the details by hand.")
    return obj


def _problems(exc: ValidationError) -> str:
    """Field names and what was wrong with each — never the values, which are
    the model's output and may carry whatever the document said."""
    seen: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()) if not isinstance(p, int)) or "reply"
        msg = str(err.get("msg", "invalid")).rstrip(".")
        item = f"{loc} ({msg})"
        if item not in seen:
            seen.append(item)
    return "; ".join(seen[:6])


def _stringish(value: Any) -> Any:
    """An invoice number a model wrote as a JSON number is still an invoice
    number. Anything else that is not text is left for the model to refuse."""
    if isinstance(value, bool):
        raise ValueError("a yes/no value is not text")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return value


# ── an invoice ───────────────────────────────────────────────────────────────

class _Invoice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vendor_name: Optional[str] = Field(default=None, max_length=300)
    vendor_gstin: Optional[str] = Field(default=None, max_length=40)
    invoice_no: Optional[str] = Field(default=None, max_length=100)
    invoice_date: Optional[str] = Field(default=None, max_length=40)
    taxable_amount_paise: int = Field(default=0, ge=0, le=MAX_PAISE)
    cgst_paise: int = Field(default=0, ge=0, le=MAX_PAISE)
    sgst_paise: int = Field(default=0, ge=0, le=MAX_PAISE)
    igst_paise: int = Field(default=0, ge=0, le=MAX_PAISE)
    total_paise: int = Field(default=0, ge=0, le=MAX_PAISE)
    line_items: list[dict] = Field(default_factory=list, max_length=MAX_LINES)

    @field_validator(*HEADER_AMOUNTS, mode="before")
    @classmethod
    def _absent_amount_is_zero(cls, v: Any) -> Any:
        # `int(x or 0)` was the old reading of an absent header amount, and it is
        # kept: the PROMPT says "use null or 0 as appropriate" for a header field
        # the document does not carry, and `check_totals` treats a zero total as
        # "not read". Line items are the opposite and have their own rule.
        if isinstance(v, bool):
            raise ValueError("a yes/no value is not an amount")
        return 0 if v is None or (isinstance(v, str) and not v.strip()) else v

    @field_validator("vendor_name", "vendor_gstin", "invoice_no", "invoice_date", mode="before")
    @classmethod
    def _text_fields(cls, v: Any) -> Any:
        return _stringish(v)

    @field_validator("line_items", mode="before")
    @classmethod
    def _no_lines_is_empty(cls, v: Any) -> Any:
        return [] if v is None else v


def parse_invoice(raw: Any) -> dict:
    """The model's invoice reading as the dict the router and the editor use,
    or `ExtractionRefused`.

    Header figures come back as integer paise (absent → 0, as before), the date
    as an ISO string or None, and every line through `read_line`, so a quantity,
    rate or GST rate nobody read is None and named in the line's `not_read`.
    `not_read` on the HEADER lists the header fields that were printed but could
    not be read (today: only the date)."""
    obj = load_json_object(raw, what="an invoice")
    try:
        model = _Invoice.model_validate(obj)
    except ValidationError as exc:
        raise ExtractionRefused(
            "The AI's reading of this invoice could not be accepted — " + _problems(exc)
            + ". Nothing was filled in; try again, or enter the bill details by hand.") from exc
    data = model.model_dump()
    header_not_read: list[str] = []
    parsed, unreadable = _iso_date(data.get("invoice_date"))
    data["invoice_date"] = parsed.isoformat() if parsed else None
    if unreadable:
        header_not_read.append("invoice_date")
    data["header_not_read"] = header_not_read
    data["line_items"] = [read_line(dict(item)) for item in model.line_items]
    return data


_NUMBER_OR_NULL = {"type": ["number", "null"]}
_INT_OR_NULL = {"type": ["integer", "null"]}
_STR_OR_NULL = {"type": ["string", "null"]}

INVOICE_LINE_FIELDS = ("description", "hsn_sac", "quantity", "unit", "rate_paise", "gst_rate_bps")

#: What Groq is asked to honour for an invoice (`strict` mode: every property is
#: required and nothing else is allowed). A hint — see the module note.
INVOICE_SCHEMA = JsonSchema(name="invoice_reading", schema={
    "type": "object",
    "additionalProperties": False,
    "required": ["vendor_name", "vendor_gstin", "invoice_no", "invoice_date",
                 *HEADER_AMOUNTS, "line_items"],
    "properties": {
        "vendor_name": _STR_OR_NULL,
        "vendor_gstin": _STR_OR_NULL,
        "invoice_no": _STR_OR_NULL,
        "invoice_date": _STR_OR_NULL,
        **{k: {"type": "integer"} for k in HEADER_AMOUNTS},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(INVOICE_LINE_FIELDS),
                "properties": {
                    "description": _STR_OR_NULL,
                    "hsn_sac": _STR_OR_NULL,
                    "quantity": _NUMBER_OR_NULL,
                    "unit": _STR_OR_NULL,
                    "rate_paise": _INT_OR_NULL,
                    "gst_rate_bps": _INT_OR_NULL,
                },
            },
        },
    },
})


def _g(type_: str, **extra: Any) -> dict:
    return {"type": type_, **extra}


#: The same shape in the OpenAPI subset Gemini documents for `response_schema`.
INVOICE_GEMINI_SCHEMA: dict = _g("OBJECT", properties={
    "vendor_name": _g("STRING", nullable=True),
    "vendor_gstin": _g("STRING", nullable=True),
    "invoice_no": _g("STRING", nullable=True),
    "invoice_date": _g("STRING", nullable=True),
    **{k: _g("INTEGER") for k in HEADER_AMOUNTS},
    "line_items": _g("ARRAY", items=_g("OBJECT", properties={
        "description": _g("STRING", nullable=True),
        "hsn_sac": _g("STRING", nullable=True),
        "quantity": _g("NUMBER", nullable=True),
        "unit": _g("STRING", nullable=True),
        "rate_paise": _g("INTEGER", nullable=True),
        "gst_rate_bps": _g("INTEGER", nullable=True),
    })),
}, required=["vendor_name", "invoice_no", *HEADER_AMOUNTS, "line_items"])


# ── a government notice ──────────────────────────────────────────────────────

NOTICE_TYPES = ("gst_scrutiny", "income_tax_demand", "income_tax_notice",
                "mca_show_cause", "tds_default", "customs", "other")

#: Sanity bounds on a notice's own dates, relative to today (IST). They are not
#: statute: they are what separates a date a notice could carry from one a
#: garbled or hostile reading produced. Ten years back is the longest look-back
#: any assessment reaches; a response window of more than two years after issue,
#: or an issue date in the future, is not a notice.
MAX_PAST_YEARS = 10
MAX_RESPONSE_WINDOW_DAYS = 2 * 366
ISSUE_FUTURE_GRACE_DAYS = 1

NOTICE_FIELD_LIMITS = {"authority": 200, "reference_no": 100, "description": 1000}


class _Notice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    authority: str = Field(default="", max_length=NOTICE_FIELD_LIMITS["authority"])
    notice_type: Optional[str] = Field(default=None, max_length=80)
    reference_no: Optional[str] = Field(default=None, max_length=NOTICE_FIELD_LIMITS["reference_no"])
    issue_date: Optional[str] = Field(default=None, max_length=40)
    response_due_date: Optional[str] = Field(default=None, max_length=40)
    description: Optional[str] = Field(default=None, max_length=NOTICE_FIELD_LIMITS["description"])

    @field_validator("authority", mode="before")
    @classmethod
    def _authority_text(cls, v: Any) -> Any:
        return "" if v is None else _stringish(v)

    @field_validator("notice_type", "reference_no", "issue_date", "response_due_date",
                     "description", mode="before")
    @classmethod
    def _text_fields(cls, v: Any) -> Any:
        return _stringish(v)


def _normalise_type(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return re.sub(r"[\s\-/]+", "_", value.strip().lower())


def validate_notice_dates(issue: Optional[date], due: Optional[date], today: date) -> None:
    """Refuse a pair of dates no notice could carry. Raises `ExtractionRefused`."""
    oldest = today - timedelta(days=MAX_PAST_YEARS * 366)

    def refuse(what: str, reason: str) -> None:
        raise ExtractionRefused(
            f"The notice reading was refused: the {what} is {reason}, which no notice could "
            "carry. Nothing was saved. Check the text you pasted, or enter the notice by hand.",
            http_status=422)

    if issue is not None:
        if issue > today + timedelta(days=ISSUE_FUTURE_GRACE_DAYS):
            refuse(f"issue date ({issue.isoformat()})", "in the future")
        if issue < oldest:
            refuse(f"issue date ({issue.isoformat()})",
                   f"more than {MAX_PAST_YEARS} years in the past")
    if due is not None:
        if due < oldest:
            refuse(f"response due date ({due.isoformat()})",
                   f"more than {MAX_PAST_YEARS} years in the past")
        if issue is not None and due < issue:
            refuse(f"response due date ({due.isoformat()})",
                   f"before the notice was issued ({issue.isoformat()})")
        if issue is not None and (due - issue).days > MAX_RESPONSE_WINDOW_DAYS:
            refuse(f"response due date ({due.isoformat()})",
                   "more than two years after the notice was issued")
        if due > today + timedelta(days=MAX_RESPONSE_WINDOW_DAYS):
            refuse(f"response due date ({due.isoformat()})", "more than two years from today")


def parse_notice(raw: Any, *, today: date) -> dict:
    """The model's notice reading as a dict, or `ExtractionRefused`.

    `notice_type` is one of `NOTICE_TYPES`: a value that is not one of them is
    stored as `other` with what the model said kept in `notice_type_as_read`
    (`other` IS the product's own "none of the above", and the CA reviews every
    notice before anything is created from it). A date that is not `YYYY-MM-DD`
    is unread (None) and named in `not_read`; a date that cannot be right is
    refused — see `validate_notice_dates`. `today` is the IST date."""
    obj = load_json_object(raw, what="a government notice", nothing="saved")
    try:
        model = _Notice.model_validate(obj)
    except ValidationError as exc:
        raise ExtractionRefused(
            "The AI's reading of this notice could not be accepted — " + _problems(exc)
            + ". Nothing was saved; try again, or enter the notice by hand.") from exc

    data = model.model_dump()
    not_read: list[str] = []
    issue, issue_bad = _iso_date(data.get("issue_date"))
    due, due_bad = _iso_date(data.get("response_due_date"))
    if issue_bad:
        not_read.append("issue_date")
    if due_bad:
        not_read.append("response_due_date")
    validate_notice_dates(issue, due, today)
    data["issue_date"] = issue.isoformat() if issue else None
    data["response_due_date"] = due.isoformat() if due else None

    ntype = _normalise_type(data.get("notice_type"))
    if ntype in NOTICE_TYPES:
        data["notice_type"] = ntype
    else:
        if data.get("notice_type"):
            data["notice_type_as_read"] = data["notice_type"]
        data["notice_type"] = "other"
    data["description"] = data.get("description") or ""
    data["not_read"] = not_read
    return data


NOTICE_SCHEMA = JsonSchema(name="notice_reading", schema={
    "type": "object",
    "additionalProperties": False,
    "required": ["authority", "notice_type", "reference_no", "issue_date",
                 "response_due_date", "description"],
    "properties": {
        "authority": {"type": "string"},
        "notice_type": {"type": "string", "enum": list(NOTICE_TYPES)},
        "reference_no": _STR_OR_NULL,
        "issue_date": _STR_OR_NULL,
        "response_due_date": _STR_OR_NULL,
        "description": {"type": "string"},
    },
})
