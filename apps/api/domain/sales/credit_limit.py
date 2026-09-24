"""
A customer's credit limit — SALES-25 (b), migration 414.

WHAT IT IS, AND WHAT IT IS NOT

    What a client will let one of their customers owe at any moment. A
    COMMERCIAL term between those two, agreed in a conversation, and nothing
    else: no Act, no rule, no return, no journal. It changes no figure — the
    invoice, its tax and its posting are identical whether the limit is
    breached or not — and this module exists so that a CA raising the eleventh
    invoice to a customer who has not paid for the first ten is TOLD.

    It lives in `domain/sales/` beside `line_tax` and `order_cycle`, which ARE
    statutory, so this says so out loud: NOTHING HERE IS A STATUTORY RULE. A
    later reader looking for the section number will not find one because there
    is not one.

THREE STATES, AND `None` IS NOT ZERO

    NOT SET (`limit_paise is None`) — nobody has recorded a limit, which is
    true of every customer in the database today. No opinion is offered and
    nothing is warned about. The obvious wrong turn is reading it as zero with
    an `or 0`, which would put every existing customer on the strictest
    possible terms overnight and look like a product-wide refusal.

    ZERO is a REAL limit and means cash only. It is why the column is nullable
    with no default: a default of 0 and an unrecorded 0 would be
    indistinguishable, and one of them is a decision somebody made.

    WITHIN / WOULD EXCEED are the two answers when a limit is recorded.

WARN BY DEFAULT; BLOCK ONLY WHERE THE FIRM ASKED

    A block stops a CA recording a supply THAT HAS ALREADY HAPPENED. The goods
    went out, the customer has them, and CGST §31 makes the invoice due — a
    product that refuses to record it does not stop the supply, it moves the
    record somewhere this product cannot see. So `blocks` is false unless
    `invoice_settings.credit_limit_blocks` is on, which is off by default and
    is a firm's own deliberate choice.

    AN OPENING DOCUMENT IS NEVER BLOCKED, whatever the switch says. ACC-14's
    reasoning exactly: an opening invoice records a balance the client arrived
    with, refusing it would make a migration impossible for the clients who
    most need one, and the balance it carries is precisely what pushes a
    customer over a limit somebody has just typed in.

THE EXPOSURE IS THE OPEN FIGURE, NOT `total - paid`

    Migration 278 made `client_sales_invoices.outstanding_paise` GENERATED so
    the formula lives once, in the schema — it carries the CGST §34 note terms
    that `total - paid` omits. The caller sums THAT column; this module takes
    the sum and never re-derives it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: Nobody has recorded a limit for this customer.
NOT_SET = "not_set"
#: A limit is recorded and this invoice keeps the customer inside it.
WITHIN = "within"
#: A limit is recorded and this invoice would take the customer past it.
WOULD_EXCEED = "would_exceed"

#: Said on every answer that carries a limit, because the module sits among
#: statutory ones and somebody will eventually look for the section.
NOT_A_STATUTORY_RULE = (
    "A credit limit is a commercial term between this client and their "
    "customer. No Act or rule sets it, and it changes no figure on the "
    "invoice, its tax or its journal."
)


@dataclass(frozen=True)
class Assessment:
    """What this invoice does to the customer's credit position."""
    state: str
    limit_paise: Optional[int]
    outstanding_paise: int
    invoice_paise: int
    #: What the customer would owe once this invoice is issued.
    exposure_paise: int
    #: How far past the limit that is. 0 unless `state` is WOULD_EXCEED.
    excess_paise: int
    #: Whether the caller must REFUSE. False on every `not_set` and `within`
    #: answer, false on an opening document, and false unless the firm
    #: switched blocking on.
    blocks: bool
    message: Optional[str]

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "limit_paise": self.limit_paise,
            "outstanding_paise": self.outstanding_paise,
            "invoice_paise": self.invoice_paise,
            "exposure_paise": self.exposure_paise,
            "excess_paise": self.excess_paise,
            "blocks": self.blocks,
            "message": self.message,
        }


def assess(
    *,
    limit_paise: Optional[int],
    outstanding_paise: int,
    invoice_paise: int,
    firm_blocks: bool = False,
    is_opening: bool = False,
) -> Assessment:
    """Where this invoice leaves the customer against their recorded limit.

    Every argument is keyword-only. Three of them are integer paise and two of
    those are `outstanding` and `invoice`, which are the same shape and mean
    opposite things — a positional call would put them the wrong way round and
    the answer would still look plausible.
    """
    outstanding = int(outstanding_paise or 0)
    invoice = int(invoice_paise or 0)
    exposure = outstanding + invoice

    if limit_paise is None:
        return Assessment(
            state=NOT_SET, limit_paise=None, outstanding_paise=outstanding,
            invoice_paise=invoice, exposure_paise=exposure, excess_paise=0,
            blocks=False, message=None)

    limit = int(limit_paise)
    if exposure <= limit:
        return Assessment(
            state=WITHIN, limit_paise=limit, outstanding_paise=outstanding,
            invoice_paise=invoice, exposure_paise=exposure, excess_paise=0,
            blocks=False, message=None)

    excess = exposure - limit
    # The sentence names all four figures. "Over the credit limit" alone sends
    # the CA to look them up, and the one they most need — what is ALREADY
    # open — is the one no screen on this page shows.
    message = (
        f"This invoice would take the customer to {_rupees(exposure)} owing, "
        f"against a recorded credit limit of {_rupees(limit)} — "
        f"{_rupees(excess)} over. {_rupees(outstanding)} is already open. "
        + NOT_A_STATUTORY_RULE
    )
    if is_opening:
        # Never blocked, and the answer SAYS it was not, rather than quietly
        # coming back as a warning the firm believes it had switched off.
        message += (
            " This is an opening document — a balance carried over from the "
            "client's previous system — so it is recorded whatever the limit "
            "says.")
    return Assessment(
        state=WOULD_EXCEED, limit_paise=limit, outstanding_paise=outstanding,
        invoice_paise=invoice, exposure_paise=exposure, excess_paise=excess,
        blocks=bool(firm_blocks) and not is_opening, message=message)


def _rupees(paise: int) -> str:
    """Indian grouping, through the one formatter — `domain/money_text`."""
    from domain.money_text import rupees_paise
    return "Rs. " + rupees_paise(paise)
