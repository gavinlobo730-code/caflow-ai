"""
How much of the practice rests on one client — the rule, and nothing else.

WHAT A PARTNER ASKS AND NOTHING HERE ANSWERED. `/api/analytics/profitability`
computes fee revenue, cost and margin per client and totals them, and the
Profitability screen renders the list. What it cannot say is the one thing that
keeps a sole practitioner or a three-partner firm awake: **if this client
leaves, what happens.** A book where one client is 40% of fees is a different
business from one where the largest is 6%, and the two look identical on a list
sorted by revenue.

IT ALSO ANSWERS THE OTHER HALF OF THE SAME READ. Once the per-client figures
are in hand, where a given client SITS in the firm's own distribution is free —
the median fee, the median margin, and this client's rank — which is the
question a partner asks before a fee review and currently answers by scrolling.
One module, because it is one fetch: two answers built from separate reads of
the same rows is how two screens come to disagree about the same client.

⚠️ **THE ICAI FEE-DEPENDENCE THRESHOLD IS NAMED AND DELIBERATELY NOT STATED.**
The ICAI Code of Ethics treats fees from one client forming a large proportion
of a practice's total fees as a **self-interest threat to independence**, with
safeguards required above a specified proportion — and `icai.org` is refused at
this environment's egress proxy, so the percentage, the population it is
measured over (audit clients only, or all), and whether it differs for a
listed entity could not be read. Stating a figure from memory on an
INDEPENDENCE question is worse than stating none: a firm told they are inside a
threshold that does not exist has been given a clean bill of health nobody
issued. So the shares are computed exactly, the concept is named on every
answer, and no line is drawn.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


#: The concept, on every answer. A percentage with no context invites the
#: reader to supply their own threshold from memory, which is the thing this
#: module refuses to do for them.
ICAI_FEE_DEPENDENCE = (
    "The ICAI Code of Ethics treats fees from one client forming a large "
    "proportion of a practice's total fees as a self-interest threat to "
    "independence, requiring safeguards above a specified proportion. The "
    "proportion, and whether it is measured over audit clients or all of "
    "them, are NOT held here — they could not be read from icai.org in this "
    "environment, and a figure written from memory on an independence "
    "question would give a firm a clean bill of health nobody issued. Read "
    "the Code and apply it to the shares below."
)

#: What the shares are and are not. Rendered beside them.
NOT_MEASURED: tuple[str, ...] = (
    "Fees INVOICED in the window, not fees earned or collected. A client "
    "billed annually in April and one billed monthly look very different "
    "over a quarter and identical over a year.",
    "Nothing about the engagement's nature. A statutory audit and a "
    "bookkeeping retainer of the same value count the same here, and the "
    "independence question does not treat them the same.",
    "Only clients with an invoice in the window. A client on the books who "
    "was not billed in it is absent rather than nil, because a nil share "
    "would dilute every other client's.",
)


@dataclass(frozen=True)
class ClientFees:
    client_id: str
    client_name: str
    revenue_paise: int
    cost_paise: int = 0


@dataclass(frozen=True)
class Share:
    client_id: str
    client_name: str
    revenue_paise: int
    #: Basis points of the firm's total fees — integer, so the arithmetic
    #: stays exact and the parts sum to 10,000 within rounding. The money rule
    #: applies to a proportion of money too: `40.0` hides which way it went.
    share_bps: int
    rank: int
    profit_paise: int
    #: None where no fee was billed, because a margin on nil revenue is not 0%,
    #: it is undefined — and reporting 0 would rank a client nobody billed
    #: below one billed at a loss.
    margin_bps: Optional[int]


@dataclass(frozen=True)
class Concentration:
    shares: tuple[Share, ...]
    total_revenue_paise: int
    clients_billed: int
    #: The largest single client's share, and the top three and five together.
    #: Three and five because a practice's dependency is rarely one client —
    #: it is one family group or one industry, and the top few is the honest
    #: proxy for a grouping no column holds.
    largest_share_bps: int
    top_3_share_bps: int
    top_5_share_bps: int
    #: The firm's own middle, so a partner can see where a client sits without
    #: scrolling. Median rather than mean: one large client drags a mean and
    #: makes every other client look small.
    median_revenue_paise: Optional[int]
    median_margin_bps: Optional[int]
    icai_fee_dependence: str = ICAI_FEE_DEPENDENCE
    not_measured: tuple[str, ...] = field(default=NOT_MEASURED)


def _median(values: list[int]) -> Optional[int]:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) // 2


def _bps(part: int, whole: int) -> int:
    """Basis points, floored. Integer throughout — `part * 10_000 // whole`
    rather than a float percentage, for `domain/gst/money`'s reason: a
    proportion of money is money arithmetic."""
    return (part * 10_000) // whole if whole > 0 else 0


def concentration(clients: Iterable[ClientFees]) -> Concentration:
    """The firm's fee concentration and each client's place in it.

    A CLIENT WITH NO FEE IN THE WINDOW IS NOT INCLUDED. A nil share would
    dilute every other client's — thirty unbilled clients would halve the
    largest client's reported dependence — and "we did not bill them this
    quarter" is not the same fact as "they are a small client".
    """
    billed = [c for c in clients if c.revenue_paise > 0]
    billed.sort(key=lambda c: (-c.revenue_paise, c.client_name, c.client_id))
    total = sum(c.revenue_paise for c in billed)

    shares: list[Share] = []
    for i, c in enumerate(billed):
        profit = c.revenue_paise - c.cost_paise
        shares.append(Share(
            client_id=c.client_id,
            client_name=c.client_name,
            revenue_paise=c.revenue_paise,
            share_bps=_bps(c.revenue_paise, total),
            rank=i + 1,
            profit_paise=profit,
            margin_bps=_bps(profit, c.revenue_paise) if c.revenue_paise > 0 else None,
        ))

    def top(n: int) -> int:
        return _bps(sum(c.revenue_paise for c in billed[:n]), total)

    return Concentration(
        shares=tuple(shares),
        total_revenue_paise=total,
        clients_billed=len(billed),
        largest_share_bps=top(1),
        top_3_share_bps=top(3),
        top_5_share_bps=top(5),
        median_revenue_paise=_median([c.revenue_paise for c in billed]),
        median_margin_bps=_median([s.margin_bps for s in shares
                                   if s.margin_bps is not None]),
    )
