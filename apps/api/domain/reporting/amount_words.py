"""How an Indian document states an amount — in words, and in figures.

WHY THIS IS ITS OWN MODULE
    `amount_in_words` lived in services/invoice_pdf_service.py, where the tax
    invoice needs it (CGST Rule 46 does not in fact require it, but every
    Indian invoice carries it and a bank reads it). The payslip needs the same
    sentence for the same reason: a net pay in figures alone is the line an
    employee disputes, and a lender asked to accept a payslip as proof of
    income looks for the words.

    Copying it would have been two implementations of "one lakh eighteen
    thousand", and they would drift. So it MOVED here and the invoice service
    imports it — the same rule the cash-flow report follows for SQL.

THE CRORE GROUP RECURSES, AND THAT IS A FIX
    The version that moved read the crore group with a three-digit renderer,
    so ₹1,000 crore came out "Ten Hundred Crore" and ₹20,000 crore raised
    IndexError out of a PDF generator — a crash, not a typo. The Indian system
    reads large numbers by recursing on the crore group ("One Lakh Crore" is
    10^12), so that is what this does, and it is total for any int.
"""
from __future__ import annotations

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
         "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
         "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two_digits(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")).strip()


def _three_digits(n: int) -> str:
    s = ""
    if n >= 100:
        s = _ONES[n // 100] + " Hundred"
        if n % 100:
            s += " " + _two_digits(n % 100)
        return s
    return _two_digits(n)


def _indian(n: int) -> str:
    """A non-negative integer in the Indian system: crore, lakh, thousand, rest.

    The crore group is rendered by this same function, not by a three-digit
    one — that is what makes "One Lakh Crore" readable and what stops a big
    number indexing off the end of _ONES.
    """
    if n == 0:
        return "Zero"
    crore = n // 10_000_000
    lakh = (n // 100_000) % 100
    thousand = (n // 1000) % 100
    rest = n % 1000
    parts = []
    if crore:
        parts.append(_indian(crore) + " Crore")
    if lakh:
        parts.append(_two_digits(lakh) + " Lakh")
    if thousand:
        parts.append(_two_digits(thousand) + " Thousand")
    if rest:
        parts.append(_three_digits(rest))
    return " ".join(parts)


def amount_in_words(paise: int) -> str:
    """Indian-system amount in words (Crore/Lakh/Thousand).

    Integer paise in, sentence out. A negative amount is read as its magnitude
    prefixed "Minus" rather than refused: a settlement can be net negative when
    a recovery exceeds the month's pay, and a document that raises on the one
    month that is hard to explain is worse than one that says so.
    """
    paise = int(paise or 0)
    sign = "Minus " if paise < 0 else ""
    paise = abs(paise)
    rupees, p = paise // 100, paise % 100
    result = f"{sign}Rupees {_indian(rupees)}"
    if p:
        result += f" and {_two_digits(p)} Paise"
    return result + " Only"


# ── In figures ────────────────────────────────────────────────────────────────

def indian_digits(rupees: int) -> str:
    """1234567 -> "12,34,567". The Indian grouping, not the Western one.

    Python's own `f"{n:,}"` groups in threes and gives "1,234,567", which no
    Indian document uses — and `apps/web` formats the same figure with
    `Intl.NumberFormat("en-IN")` and gets it right, so the screen and the PDF
    of one amount disagree.

    That disagreement is tree-wide (roughly twenty sites across services/ and
    domain/) and is NOT fixed by this function existing. What this is for is
    that new code has somewhere correct to call, and the later sweep has one
    place to point every site at.
    """
    n = int(rupees)
    sign = "-" if n < 0 else ""
    text = str(abs(n))
    if len(text) <= 3:
        return sign + text
    # The last three digits, then pairs — 1,23,45,678.
    head, tail = text[:-3], text[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return sign + ",".join(groups + [tail])


def indian_rupees(paise: int) -> str:
    """Integer paise as an Indian-grouped rupee figure, e.g. "8,50,000".

    Whole rupees, because that is what a sentence about a return states. Never
    float: the paise are truncated by integer division, not rounded away by a
    division that went through a float first.
    """
    p = int(paise or 0)
    sign = "-" if p < 0 else ""
    return sign + indian_digits(abs(p) // 100)
