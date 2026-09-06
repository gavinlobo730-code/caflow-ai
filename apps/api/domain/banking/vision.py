"""
Reading a SCANNED bank statement — a photograph of paper — with a vision model.

WHY THIS IS THE RISKIEST OF THE THREE STATEMENT PATHS, AND WHAT MAKES IT SAFE

CSV and XLSX are parsed deterministically. A text PDF is parsed from real
characters and real coordinates. This path is a model looking at pixels, and it
will sometimes read 8 as 3 or drop a row at a page break.

That would be tolerable for an invoice, where a human checks the six fields the
model produced. It is NOT tolerable for a statement: nobody reads 300 lines to
check them, so a misread number would go into the books silently and be found
at reconciliation, months later, if at all.

So the arithmetic is the control, and on this path it is NOT OPTIONAL:

    opening + Σ credits − Σ debits == closing

The caller must supply the opening and closing balances printed on the
statement, and the import is refused unless the model's reading reproduces them
to the paisa. A model cannot fake that by being confident — it either read every
line or the sum does not land. That single check is the whole reason this path
is allowed to exist; see routers/banking.py, where it is enforced, and
domain/banking/tie_out.py for the arithmetic.

WHAT THE MODEL IS ASKED FOR, AND WHAT IT IS NOT TRUSTED WITH

It is asked to READ, not to interpret. It returns the cells it can see — date,
description, reference, the two amounts, the running balance — as strings,
exactly as printed. Turning those strings into dates and integer paise is done
HERE, by `_to_iso_date` and `_to_paise`, the same functions every CSV and XLSX
row goes through. So a model that writes "1,25,000.00" or "25/12/2026" is parsed
by the code that already knows what those mean, and there is one place where a
date format or a Dr/Cr suffix is understood rather than two.

WHAT IS DELIBERATELY NOT DONE HERE

No network call. The model is injected as `call_model`, so every test in this
repository exercises the real parsing, the real prompt and the real refusals
against a fabricated response, with no key and no traffic. The Gemini call is
five lines in services/statement_vision.py.
"""
from __future__ import annotations

import io
import json
import logging
from typing import Callable, Optional, Protocol

from .normalizer import NormalizedTxn, StatementParseError, _to_iso_date, _to_paise

_logger = logging.getLogger("caflow.banking.vision")

#: Rasterising resolution. 150dpi is enough for a model to read statement type
#: and small enough to keep a multi-page upload inside a request. Lower loses
#: the decimal point on a dense statement; higher costs tokens for no gain.
_RESOLUTION = 150

#: A hard stop on pages sent to the model. A statement longer than this is
#: almost certainly a whole year exported as one scan, and sending it silently
#: would be a large bill the CA never agreed to. Refused, with the count.
MAX_PAGES = 20


class ModelCall(Protocol):
    """`(image_bytes, mime_type, prompt) -> the model's raw text reply`."""
    def __call__(self, image: bytes, mime: str, prompt: str) -> str: ...


PROMPT = """
You are reading one page of an Indian bank statement. Return ONLY a JSON array,
no prose and no code fence.

Each element is one TRANSACTION ROW, in the order printed on the page:

  {"date": "...", "description": "...", "reference": "...",
   "debit": "...", "credit": "...", "balance": "..."}

Rules:
- Copy the text EXACTLY as printed. Do not reformat dates, do not strip commas
  from amounts, do not convert anything.
- "debit" is money OUT (withdrawal); "credit" is money IN (deposit). If the
  statement uses one amount column with a Dr/Cr marker, put the amount in the
  matching field and leave the other empty.
- Use an empty string for any cell that is blank on the page.
- Include ONLY transaction rows. Skip page headers, column headings, carried
  forward / brought forward lines, summary blocks, and totals.
- If the page has no transaction rows, return [].
""".strip()


def page_images(content: bytes, *, resolution: int = _RESOLUTION) -> list[bytes]:
    """Each page of a PDF as PNG bytes.

    Raises rather than returning a short list when the document is longer than
    MAX_PAGES — a truncated statement that then failed the tie-out would send
    the CA looking for a missing transaction that was never sent to the model.
    """
    import pdfplumber

    out: list[bytes] = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise StatementParseError(
                    f"This PDF has {len(pdf.pages)} pages, and at most {MAX_PAGES} "
                    f"can be read from a scan at once. Split it by month, or "
                    f"upload the CSV or Excel export instead.")
            for page in pdf.pages:
                buf = io.BytesIO()
                page.to_image(resolution=resolution).save(buf, format="PNG")
                out.append(buf.getvalue())
    except StatementParseError:
        raise
    except Exception as e:  # noqa: BLE001 — the PDF library's own exceptions
        _logger.warning("could not rasterise statement PDF: %s: %s", type(e).__name__, e)
        raise StatementParseError(
            "This file could not be opened as a PDF. If it downloaded from net "
            "banking, try downloading it again.") from e
    return out


def _rows_from_reply(reply: str) -> list[dict]:
    """The model's reply as a list of row dicts.

    A model that returns prose, a code fence, or an object instead of an array
    is a failure to read the page — not something to salvage by guessing. It is
    refused, because a partial reading that then fails the tie-out is harder to
    act on than a clear "it could not read this".
    """
    text = (reply or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.split("\n", 1)[1] if text.lower().startswith("json") else text
    def _unreadable(cause: Optional[Exception] = None) -> StatementParseError:
        return StatementParseError(
            "The statement image could not be read. Try a clearer scan, or "
            "upload the CSV or Excel export instead.")

    # The whole reply first. Only if that is not a JSON array does the bracket
    # scan run, and it is deliberately second: scanning for the outermost [ ... ]
    # would pull the empty list out of `{"rows": []}` and report "no
    # transactions on this page" for a reply that was the wrong SHAPE. Two
    # different failures reported as one is how a bad prompt looks like a bad
    # scan.
    rows = None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            rows = parsed
        else:
            raise _unreadable()
    except StatementParseError:
        raise
    except ValueError:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1 or end < start:
            raise _unreadable() from None
        try:
            rows = json.loads(text[start:end + 1])
        except ValueError as e:
            raise _unreadable(e) from e
    if not isinstance(rows, list):
        raise _unreadable()
    return [r for r in rows if isinstance(r, dict)]


def _to_txn(row: dict) -> Optional[NormalizedTxn]:
    """One model row as a NormalizedTxn, or None when it is not a transaction.

    Parsed by `_to_iso_date` and `_to_paise` — the same functions every CSV and
    XLSX cell goes through — so a date format or a trailing Dr/Cr is understood
    in ONE place rather than two.
    """
    iso = _to_iso_date(row.get("date"))
    desc = " ".join(str(row.get("description") or "").split())
    if not iso or not desc:
        return None
    # abs() on the two amount columns, sign kept on the balance — exactly what
    # _rows_to_txns does with the same parser, and for the same reason:
    # _to_paise treats a trailing "Dr" as a SIGN ("1,000.00 Dr" -> -100000)
    # because a statement's BALANCE column uses it to mean overdrawn. A negative
    # debit_paise would then make the tie-out's Σ debits smaller instead of
    # larger, and a wrong reading would add up.
    debit = abs(_to_paise(row.get("debit")))
    credit = abs(_to_paise(row.get("credit")))
    if not debit and not credit:
        # A row with a date and a narration but no money is a sub-heading or a
        # wrapped continuation line, not a transaction.
        return None
    ref = " ".join(str(row.get("reference") or "").split()) or None
    return NormalizedTxn(
        transaction_date=iso,
        description=desc,
        reference_no=ref,
        debit_paise=debit,
        credit_paise=credit,
        balance_paise=_to_paise(row.get("balance")),
    )


def read_statement(
    images: list[bytes],
    *,
    call_model: ModelCall,
    mime: str = "image/png",
) -> list[NormalizedTxn]:
    """Every transaction the model can see across the pages, in page order."""
    if not images:
        raise StatementParseError("There was nothing to read in this file.")

    txns: list[NormalizedTxn] = []
    for i, image in enumerate(images, 1):
        try:
            reply = call_model(image=image, mime=mime, prompt=PROMPT)
        except StatementParseError:
            raise
        except Exception as e:  # noqa: BLE001 — the provider's own exceptions
            # Which vendor and model this uses is an internal detail and is not
            # actionable for a CA; the real reason goes to the log only. Same
            # rule as routers/document_intelligence_v1.py.
            _logger.error("vision read failed on page %d (%s): %s", i, type(e).__name__, e)
            raise StatementParseError(
                f"The statement could not be read from page {i}. Please retry, "
                f"or upload the CSV or Excel export instead.") from e
        for row in _rows_from_reply(reply):
            txn = _to_txn(row)
            if txn is not None:
                txns.append(txn)

    if not txns:
        raise StatementParseError(
            "No transactions could be read from this scan. If it is a "
            "photograph, a flat, straight, well-lit image reads best — "
            "otherwise upload the CSV or Excel export.")
    return txns
