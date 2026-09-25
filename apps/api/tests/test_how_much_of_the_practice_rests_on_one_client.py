"""
`domain/practice/concentration` — the firm's fee dependence, and where a client sits.

THE ONE THING IT MUST NOT DO IS DRAW A LINE. The ICAI Code of Ethics treats
fees from one client forming a large proportion of a practice's total as a
self-interest threat to independence, with safeguards above a specified
proportion — and icai.org is refused at this environment's proxy, so the
proportion could not be read. A percentage written from memory on an
independence question would hand a firm a clean bill of health nobody issued.
The concept is named on every answer and no threshold is stated; a test below
asserts the module contains no percentage that could be read as one.
"""
from __future__ import annotations

import re

import pytest

from domain.practice import concentration as cn


def fees(*pairs) -> list[cn.ClientFees]:
    return [cn.ClientFees(client_id=str(i + 1), client_name=name,
                          revenue_paise=rev, cost_paise=cost)
            for i, (name, rev, cost) in enumerate(pairs)]


# ── The shares ───────────────────────────────────────────────────────────────

def test_the_largest_client_share_is_the_headline():
    out = cn.concentration(fees(("Acme", 40_00_000, 0), ("Bee", 30_00_000, 0),
                                ("Cee", 20_00_000, 0), ("Dee", 10_00_000, 0)))
    assert out.largest_share_bps == 4000          # 40.00%
    assert out.top_3_share_bps == 9000            # 90.00%
    assert out.top_5_share_bps == 10000           # every client there is
    assert out.total_revenue_paise == 100_00_000


def test_shares_are_basis_points_and_not_a_float_percentage():
    """A proportion of money is money arithmetic — `domain/gst/money`'s rule.
    A float `40.0` hides which way the rounding went, and these figures are
    read against an independence threshold."""
    out = cn.concentration(fees(("A", 1, 0), ("B", 2, 0)))
    for sh in out.shares:
        assert isinstance(sh.share_bps, int)
    assert isinstance(out.largest_share_bps, int)


def test_a_share_floors_rather_than_rounding_up():
    """One third of the fees is 33.33%, never 33.34% — overstating a
    dependence share is the direction that invents a threat."""
    out = cn.concentration(fees(("A", 1_00_000, 0), ("B", 1_00_000, 0),
                                ("C", 1_00_000, 0)))
    assert out.largest_share_bps == 3333


def test_clients_are_ranked_largest_first():
    out = cn.concentration(fees(("Small", 10, 0), ("Big", 100, 0), ("Mid", 50, 0)))
    assert [s.client_name for s in out.shares] == ["Big", "Mid", "Small"]
    assert [s.rank for s in out.shares] == [1, 2, 3]


def test_a_tie_is_broken_by_name_so_the_order_is_stable():
    """Two clients billed the same amount must not swap places between reads —
    a rank that moves on refresh reads as a change in the business."""
    a = cn.concentration(fees(("Zed", 100, 0), ("Ay", 100, 0)))
    b = cn.concentration(fees(("Ay", 100, 0), ("Zed", 100, 0)))
    assert [s.client_name for s in a.shares] == [s.client_name for s in b.shares]
    assert a.shares[0].client_name == "Ay"


# ── Who is in the population ─────────────────────────────────────────────────

def test_a_client_with_no_fee_in_the_window_is_absent_not_nil():
    """A nil share would dilute every other client's — thirty unbilled clients
    would halve the largest client's reported dependence — and "we did not
    bill them this quarter" is not "they are a small client"."""
    out = cn.concentration(fees(("Billed", 100, 0), ("Not billed", 0, 500)))
    assert out.clients_billed == 1
    assert [s.client_name for s in out.shares] == ["Billed"]
    assert out.largest_share_bps == 10000


def test_a_firm_that_billed_nobody_answers_rather_than_dividing_by_zero():
    out = cn.concentration(fees(("A", 0, 0)))
    assert out.clients_billed == 0
    assert out.total_revenue_paise == 0
    assert out.largest_share_bps == 0
    assert out.median_revenue_paise is None
    assert out.median_margin_bps is None


def test_an_empty_firm_answers():
    out = cn.concentration([])
    assert out.shares == ()
    assert out.clients_billed == 0


# ── The firm's own middle ────────────────────────────────────────────────────

def test_the_middle_is_a_median_because_one_large_client_drags_a_mean():
    """A partner asking "is this client small for us?" against a mean that one
    40% client has lifted gets the wrong answer about everybody else."""
    rows = fees(("Whale", 900, 0), ("A", 10, 0), ("B", 20, 0),
                ("C", 30, 0), ("D", 40, 0))
    out = cn.concentration(rows)
    assert out.median_revenue_paise == 30
    mean = sum(r.revenue_paise for r in rows) // len(rows)
    assert mean == 200, "premise: a mean would say the middle client bills 200"


def test_the_median_margin_skips_a_client_with_no_revenue():
    out = cn.concentration(fees(("A", 100, 50), ("B", 200, 50)))
    assert out.median_margin_bps == 6250       # (5000 + 7500) // 2


def test_a_margin_on_nil_revenue_is_undefined_and_not_zero():
    """Reporting 0% would rank a client nobody billed below one billed at a
    loss. Such a client is out of the population entirely, so the field can
    only be None through the dataclass — asserted so it stays nullable."""
    import typing
    hints = typing.get_type_hints(cn.Share)
    assert hints["margin_bps"] == typing.Optional[int]


# ── The refusal ──────────────────────────────────────────────────────────────

def test_the_icai_threat_is_named_on_every_answer():
    out = cn.concentration(fees(("A", 100, 0)))
    assert "ICAI" in out.icai_fee_dependence
    assert "independence" in out.icai_fee_dependence
    assert "NOT held here" in out.icai_fee_dependence


def test_no_percentage_is_stated_near_the_independence_concept():
    """The load-bearing one. icai.org is refused at this environment's proxy,
    so the proportion, the population it is measured over, and whether a listed
    entity differs are all unread. A figure from memory would give a firm a
    clean bill of health nobody issued.

    ⚠️ THE RULE, NOT A SPELLING OF IT — and the first draft was the spelling.
    It banned every percentage in the module and fired on "a margin on nil
    revenue is not 0%, it is undefined", which is a remark about a dataclass
    field and could not be read as a threshold by anybody. A percentage is a
    threshold when it sits NEXT TO the independence concept, so that is what
    is checked: no sentence may carry both a percentage and one of the words
    that would make it one.
    """
    import pathlib

    src = pathlib.Path(cn.__file__).read_text()
    # Sentences, roughly — a full stop followed by whitespace, which is good
    # enough over prose that is deliberately written in sentences.
    trigger = re.compile(r"\b(icai|independence|safeguard|threshold|threat)\b", re.I)
    pct = re.compile(r"\b\d{1,2}(?:\.\d+)?\s*(?:%|per cent|percent)")
    offenders = [sen.strip() for sen in re.split(r"(?<=\.)\s", src)
                 if trigger.search(sen) and pct.search(sen)]
    assert not offenders, (
        "a percentage stated beside the independence concept reads as the ICAI "
        f"threshold, which is not held here: {offenders}")


def test_the_independence_wording_says_the_figure_is_not_held():
    """A named concept with no stated refusal invites the reader to supply a
    threshold from memory, which is the thing this module refuses to do for
    them."""
    body = cn.ICAI_FEE_DEPENDENCE
    assert "NOT held here" in body
    assert "could not be read" in body
    assert "Read the Code" in body


def test_the_module_says_what_the_shares_are_not():
    out = cn.concentration(fees(("A", 100, 0)))
    assert len(out.not_measured) >= 3
    assert all(s.endswith(".") and len(s) >= 60 for s in out.not_measured)
    joined = " ".join(out.not_measured).lower()
    assert "invoiced" in joined, "fees billed is not fees earned or collected"
    assert "audit" in joined, "an audit and a retainer are not the same here"


# ── Profit travels with the share ────────────────────────────────────────────

@pytest.mark.parametrize("revenue,cost,margin_bps", [
    (100, 0, 10000),
    (100, 50, 5000),
    (100, 100, 0),
    (100, 150, -5000),      # billed at a loss, and it says so
])
def test_a_clients_margin_is_reported_beside_its_share(revenue, cost, margin_bps):
    out = cn.concentration(fees(("A", revenue, cost)))
    assert out.shares[0].margin_bps == margin_bps
    assert out.shares[0].profit_paise == revenue - cost
