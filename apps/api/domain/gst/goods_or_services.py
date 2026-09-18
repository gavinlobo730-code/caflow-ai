"""
Whether a line is a supply of GOODS or of SERVICES, and the code usually says.

TWO SOURCES AND ONE RESOLVER, the `place_of_supply` shape. What somebody
RECORDED on the line wins, because it is a statement about the transaction;
otherwise the HSN or SAC itself answers, because the tariff separates them; and
where neither is available the answer is `None`, which is a real state and not a
default.

THE CODE IS THE SECOND SOURCE AND IT IS A REAL DERIVATION.
    Services are classified under the Service Accounting Code, which is Chapter
    **99** of the tariff — 9954 construction, 9983 professional and technical,
    9985 support services. The HSN of goods runs Chapters 1 to 98 and never
    begins 99. So a well-formed code answers the question by itself, and asking
    a CA to tick a box beside `998313` would be asking them to restate what they
    have already typed — which is how two fields come to disagree.

    `apps/web/lib/invoices/compliance.isServiceCode` has implemented exactly
    this since the e-way split was built, and had NO PYTHON TWIN — the same
    defect SALES-17 (the e-way threshold) and SALES-18 (the IRN scope test)
    were, a rule living only in the browser with nothing pinning it. It is the
    keystroke mirror now and `tests/fixtures/goods_or_services.json` holds the
    two together.

WHY THE COLUMN EXISTS AT ALL, GIVEN THAT.
    Migration 411's `client_sales_invoice_lines.is_service` records the answer
    where the CODE cannot give one — an absent HSN, a malformed one, or a line
    whose classification the CA disagrees with. It is nullable with no default
    precisely because it is an OVERRIDE rather than the source, the same
    relationship `account_group_mappings` should have had to
    `schedule_line_for_account` and did not.

WHAT TURNS ON IT.
    The e-invoice portal makes quantity and Unit Quantity Code **mandatory for
    goods and optional for services**, and CGST Rule 46(h) asks for the quantity
    and unit on a supply of goods. `domain/gst/irp_validations` reports against
    that. Nothing here moves a rupee: the tax on a line comes from its own rate,
    and the goods-or-services distinction changes the PLACE OF SUPPLY rules
    (IGST §§10-13), which is a question about the transaction that this module
    deliberately does not answer.
"""
from __future__ import annotations

import re
from typing import Optional

#: The tariff chapter services are classified under. A Service Accounting Code
#: begins 99 and the HSN of goods runs Chapters 1-98, so the first two digits
#: settle it for any well-formed code.
SERVICE_CHAPTER = "99"

#: Digits only, at least two — the same shape `irp_validations.HSN_CODE_RE`
#: requires, restated as a match rather than imported so this module answers
#: about a code the portal would reject too (a two-digit `99` is a real chapter
#: heading and is enough to tell goods from services, whatever its own length
#: problem is).
_NUMERIC = re.compile(r"^[0-9]{2,}$")

#: Where the answer came from. Returned beside it because "a service because the
#: CA said so" and "a service because the code is 9983" are different facts, and
#: only the first survives the CA changing the code.
SOURCE_RECORDED = "recorded"
SOURCE_CODE = "hsn_sac_code"
SOURCE_UNKNOWN = "unknown"


def is_service_code(code: Optional[str]) -> Optional[bool]:
    """True for a SAC, False for an HSN of goods, None where the code cannot say.

    `None` rather than False for a malformed or absent code: "this is not a
    service" and "nobody can tell" send a CA to different places, and the second
    is what an empty `hsn_sac` means.
    """
    clean = (code or "").strip()
    if not _NUMERIC.match(clean):
        return None
    return clean[:2] == SERVICE_CHAPTER


def resolve(*, recorded: Optional[bool],
            hsn_sac_code: Optional[str]) -> tuple[Optional[bool], str]:
    """Whether this line is a service, and which source answered.

    THE RECORDED VALUE WINS, and that ordering is the whole point of the
    column: a CA who has said so is stating a fact about the supply, while the
    code is an inference from a classification they may not have finished. The
    reverse order would make the column unwritable in practice — every line
    carrying an HSN would ignore it.
    """
    if recorded is not None:
        return bool(recorded), SOURCE_RECORDED
    from_code = is_service_code(hsn_sac_code)
    if from_code is not None:
        return from_code, SOURCE_CODE
    return None, SOURCE_UNKNOWN
