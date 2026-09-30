"""What an extracted invoice line actually SAID, and what it did not. (AI-01.)

WHAT WAS WRONG
    `routers/document_intelligence_v1._parse_extraction_json` read every line
    with `int(item.get("gst_rate_bps") or 1800)` and
    `float(item.get("quantity") or 1)`. Both are truthiness tests on a number
    whose legitimate value can be ZERO-adjacent:

      * `0` is falsy, so a line the model read as 0% — nil-rated or exempt —
        came back as **18%**. The draft bill fed the purchase editor, so input
        tax credit on an exempt purchase was overstated unless the CA spotted
        it on one line of a long invoice;
      * a missing quantity became **1**, a figure nobody read; and
      * the editor then put `unit: "NOS"` on every line and `gst_rate ?? 1800`
        beside it, so the screen showed an invented unit and an invented rate
        exactly as it showed the ones the document carried.

    The header-only totals check (`domain/extraction_totals.py`) cannot see any
    of this — it compares five header figures and never reads a line.

THE RULE
    Only an ABSENT value is unknown. A genuine `0` is a reading and stays `0`.
    An unknown value is `None` — never a default — and the line carries
    `not_read`, the names of the fields nobody read, so a screen can leave them
    empty and flagged instead of rendering a guess as if the document said it.

    `rate` is treated the same way for the same reason: a rate the model could
    not read is not a rate of nil, and a line priced at nil is a line that
    reports no taxable value.

    `unit` is read only where it IS one of CBIC's Unit Quantity Codes
    (`domain/gst/uqc`). A printed word that is not one (`Kg`, `Pieces`) is NOT
    silently converted to the code it probably meant — `uqc.closest_code`'s own
    docstring says it is a suggestion and never a substitution — so the unit is
    unread and the text as printed travels beside it in `unit_as_printed` for
    the CA to pick from.

WHAT THIS DOES NOT DECIDE
    Whether a rate is the RIGHT rate, or a quantity the right one. It says what
    was READ. Everything downstream (`_compute_bill_lines_and_totals`)
    recomputes from whatever the CA confirms.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from domain.gst import uqc

# The four field names a line can carry in `not_read`. Named so the router, the
# purchase-bill door and the tests cannot spell one differently from the screen.
QUANTITY = "quantity"
UNIT = "unit"
GST_RATE = "gst_rate"
RATE = "rate"

# What a CA is told, per field. The wording is the server's so the from-document
# refusal and the screen's flag say the same thing.
LABELS = {
    QUANTITY: "quantity",
    UNIT: "unit of measure",
    GST_RATE: "GST rate",
    RATE: "rate",
}


def _number(value: Any) -> Optional[float]:
    """A finite number, or None. Never raises: a model's output is text, and a
    field it garbled is an unread field, not a failed extraction."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value:
            return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def unread_fields(line: dict) -> list[str]:
    """The fields of one extracted line that nobody read.

    Computed from the VALUES rather than from a stored flag, so a line that
    arrives from anywhere — the parser's own output, or an `extracted_data`
    body a client posts back to `POST /api/purchase-bills/from-document` —
    is judged the same way. A quantity that is not positive is unread too: a
    line of nil quantity is not something a document states.
    """
    out: list[str] = []
    qty = _number(line.get("quantity"))
    if qty is None or qty <= 0:
        out.append(QUANTITY)
    unit = line.get("unit")
    if not (isinstance(unit, str) and unit.strip()):
        out.append(UNIT)
    bps = _number(line.get("gst_rate_bps"))
    if bps is None or bps < 0:
        out.append(GST_RATE)
    if _number(line.get("rate_paise")) is None:
        out.append(RATE)
    return out


def read_line(item: dict) -> dict:
    """Coerce one extracted line in place, leaving what was not read as None.

    Returns the same dict for chaining. `not_read` is always present — `[]`
    where everything was read — because an absent key and an empty list read
    the same to `line.not_read ?? []` and are different states: empty says the
    check ran and found nothing, absent says this build did not run it.
    """
    qty = _number(item.get("quantity"))
    item["quantity"] = qty if qty is not None and qty > 0 else None

    bps = _number(item.get("gst_rate_bps"))
    # int() of a finite float: the prompt asks for whole basis points, and a
    # model that answers 1800.0 has still said 18%.
    item["gst_rate_bps"] = int(bps) if bps is not None and bps >= 0 else None

    rate = _number(item.get("rate_paise"))
    item["rate_paise"] = int(rate) if rate is not None else None

    printed = item.get("unit")
    printed_text = printed.strip() if isinstance(printed, str) and printed.strip() else None
    code = uqc.normalise(printed_text)
    if code is not None and uqc.is_valid(code):
        item["unit"] = code
        item.pop("unit_as_printed", None)
    else:
        item["unit"] = None
        # Kept only where something WAS printed: the CA picks the code from the
        # word on their own document, and `Kg` is the commonest of them.
        if printed_text is not None:
            item["unit_as_printed"] = printed_text
        else:
            item.pop("unit_as_printed", None)

    item["not_read"] = unread_fields(item)
    return item
