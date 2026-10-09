"""The recurring lines of a seeded statement are covered by a rule, so some of the queue is `ready`.

WHAT WAS WRONG (PRE-A-004, found by driving the seeded firm)
    A statement line is graded `ready` when a rule the CA wrote covers it, or when the payee's history is unanimous
    (`domain/banking/entry`). The seeder wrote neither, so every line on all eight clients was `needs_you` (21 to 60
    each) or `proposed` (2 to 4): "Pass N ready", the verb the banking screen exists to show, had nothing to pass.

THE RULES
    * A client with an imported statement has a rule for each recurring outflow the statement carries, and a rule for
      nothing the statement does not carry: every operating outflow is covered by exactly one rule.
    * A rule names a ledger by NAME, and each name is one the standard chart seeds (`coa_seed_service.STANDARD_COA`),
      so the rule resolves on a real firm.
    * Only the bank's own charge carries a GST rate (BANK-24) -- a rate on rent would split tax that is not there.
"""
from __future__ import annotations

import pytest

from domain.demo import fixture
from services.coa_seed_service import STANDARD_COA

FIRM = fixture.build("2025-26")
WITH_STATEMENT = [c for c in FIRM.clients if c.banks and c.banks[0].import_statement and c.bank_lines]


def _outflows(client):
    return [ln for ln in client.bank_lines if not ln.is_credit]


@pytest.mark.parametrize("client", WITH_STATEMENT, ids=lambda c: c.name)
def test_every_operating_outflow_is_covered_by_exactly_one_rule(client):
    for line in _outflows(client):
        hits = [r for r in client.bank_rules
                if r.description_pattern.lower() in line.description.lower()]
        assert len(hits) == 1, f"{client.name}: {line.description!r} is covered by {len(hits)} rules"


@pytest.mark.parametrize("client", WITH_STATEMENT, ids=lambda c: c.name)
def test_a_rule_exists_only_for_a_line_the_statement_carries(client):
    narrations = [ln.description.lower() for ln in _outflows(client)]
    for r in client.bank_rules:
        assert any(r.description_pattern.lower() in n for n in narrations), (client.name, r.rule_name)


def test_a_client_with_no_statement_has_no_rules():
    for c in FIRM.clients:
        if not (c.banks and c.banks[0].import_statement and c.bank_lines):
            assert c.bank_rules == (), c.name


def test_every_rule_names_a_ledger_the_standard_chart_seeds():
    seeded = {name for _code, name, *_rest in STANDARD_COA}
    for c in FIRM.clients:
        for r in c.bank_rules:
            assert r.ledger in seeded, f"{c.name}: rule {r.rule_name!r} names {r.ledger!r}, which no firm is seeded with"


def test_only_the_banks_own_charge_carries_a_gst_rate():
    for c in FIRM.clients:
        for r in c.bank_rules:
            assert (r.gst_rate_bps is not None) == (r.ledger == "Bank Charges"), (c.name, r)
            if r.gst_rate_bps is not None:
                assert r.gst_rate_bps == 1_800


def test_the_rules_are_the_same_on_every_build():
    again = fixture.build("2025-26")
    assert [c.bank_rules for c in FIRM.clients] == [c.bank_rules for c in again.clients]
