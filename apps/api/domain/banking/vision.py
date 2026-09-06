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

So the arithmetic is the control, and on this path it is NOT OPTIONAL. A model
cannot fake a sum by being confident — it either read every line or the figures
do not land. That is the whole reason this path is allowed to exist; see
routers/banking.py, where it is enforced, and domain/banking/tie_out.py for the
arithmetic.

There are two things the reading can be checked against, and EITHER will do:

  * the totals the statement PRINTS on itself — read by `read_printed_totals`
    below, from the last page, by a SEPARATE call that is shown no
    transactions. That independence is the point: a model asked for a grand
    total beside a list it has just written out will add the list up, and a
    reading that verifies itself is worth nothing while looking exactly like a
    passing check;
  * the opening and closing balances the CA types in, which is the only
    evidence that can say this file is the whole period.

Whichever is available runs, both run when both are, and the import is refused
unless what runs passes. The balances used to be demanded up front, before
anything was rasterised. They are now the FALLBACK, asked for only when the
totals probe finds nothing — one page-sized call in, rather than twenty — because
a CA photographing a statement that ends with its own Grand Total should not
have to retype two numbers off the same picture.

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
    text = _strip_fence(reply)

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


# ── The statement's own totals, read SEPARATELY ──────────────────────────────

TOTALS_PROMPT = """
You are looking at the LAST page of an Indian bank statement.

Many statements end with a row that states the TOTAL of all withdrawals and all
deposits for the whole statement — usually labelled "Grand Total", "Total" or
"Totals".

If such a row is printed on this page, return ONLY this JSON object, no prose
and no code fence:

  {"label": "<the label exactly as printed>",
   "total_withdrawals": "<the withdrawal/debit figure exactly as printed>",
   "total_deposits": "<the deposit/credit figure exactly as printed>"}

Rules:
- TRANSCRIBE. Copy the two figures character for character from the printed
  row. Keep the commas. Do NOT add up the transactions on the page, and do NOT
  work either figure out from anything else — if it is not printed, it is not
  an answer.
- This must be the total for the WHOLE statement. A page subtotal, a "carried
  forward" or "brought forward" line, or a closing balance is NOT it.
- If there is no such row on this page, or you are not certain, return exactly:
  {"label": null}
""".strip()


def read_printed_totals(
    image: bytes,
    *,
    call_model: ModelCall,
    mime: str = "image/png",
) -> Optional[dict]:
    """The totals row the statement prints, transcribed by a SECOND, separate call.

    WHY A SECOND CALL AND NOT ANOTHER FIELD ON THE FIRST

        The totals are worth having on this path for the same reason as on every
        other one: they are the evidence, printed on the statement, that every
        line was read, and they save the CA typing two numbers off the page.

        But a model that produced the transactions AND the totals in one reply
        can produce a total that AGREES BY CONSTRUCTION — asked for a grand
        total beside a list it has just written out, a language model will
        happily add the list up. The check would then be the reading verifying
        itself, which is worth nothing and looks exactly like a passing check.

        So this is a separate call, given ONE page and no transactions, whose
        only instruction is to transcribe a row or say there is none. It cannot
        add up rows it has not been shown. That independence is the whole reason
        the figures are allowed to gate an import.

    WHY IT REFUSES SO READILY
        A statement that prints no totals must come back as None, not as a
        plausible pair of numbers — None means the caller falls back to the
        balances the CA types, and a wrong pair means a real import is refused
        or, worse, a wrong one is accepted. So the label has to look like a
        totals label (the same pattern the parser uses) and both figures have to
        look like money. Anything else is None.
    """
    from .tie_out import _looks_numeric
    from .normalizer import _TOTAL_LABEL

    try:
        reply = call_model(image=image, mime=mime, prompt=TOTALS_PROMPT)
    except Exception as e:  # noqa: BLE001 — the provider's own exceptions
        # NOT fatal. The totals are a bonus on this path; the balances remain,
        # and the caller refuses if neither is available. Failing the whole
        # upload because the optional half of the evidence could not be fetched
        # would be the wrong trade.
        _logger.warning("printed-totals read failed (%s): %s", type(e).__name__, e)
        return None

    try:
        obj = json.loads(_strip_fence(reply))
    except ValueError:
        _logger.warning("printed-totals reply was not JSON")
        return None
    if not isinstance(obj, dict):
        return None

    label = " ".join(str(obj.get("label") or "").split())
    debit = str(obj.get("total_withdrawals") or "").strip()
    credit = str(obj.get("total_deposits") or "").strip()
    if not _TOTAL_LABEL.match(label):
        # Includes the {"label": null} case the prompt asks for, and an invented
        # label like "Sum of transactions" — which is what a model that computed
        # rather than read tends to write.
        return None
    if not (_looks_numeric(debit) and _looks_numeric(credit)):
        return None
    return {
        "label": label,
        "total_debits_paise": abs(_to_paise(debit)),
        "total_credits_paise": abs(_to_paise(credit)),
    }


def _strip_fence(reply: str) -> str:
    """A model that wrapped its JSON in a code fence, unwrapped. Same tolerance
    _rows_from_reply extends, and for the same reason: the fence is a formatting
    habit, not a failure to read the page."""
    text = (reply or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.split("\n", 1)[1] if text.lower().startswith("json") else text
    return text.strip()
