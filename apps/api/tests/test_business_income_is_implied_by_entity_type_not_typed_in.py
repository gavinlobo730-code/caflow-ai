"""
Item 6 — the Form 10-IEA guidance on the Tax Computation screen ignored the
client's own entity type, so a Proprietorship (whose whole assessment IS a
business — see domain/income_tax/assessee.py's own docstring) showed
"no Form 10-IEA needed" until the CA had manually typed a nonzero business
income figure. §115BAC(6) has two clauses (Form 10-IEA where there is
business income, the return itself where there is not — see
domain/income_tax/regime_election.py), and the computation screen only
offers the right one where it can tell, before any figure is typed.

WHY THIS IS A BACKEND MODULE AND NOT A FRONTEND CONDITIONAL
    An entity-type -> tax-basis judgment is exactly what CLAUDE.md's "zero
    business logic in the frontend" rule exists to keep out of
    apps/web/app/clients/[id]/tax/computation/page.tsx — and
    apps/web/scripts/a-company-is-not-taxed-on-individual-slabs.test.ts
    already refuses that screen the literal "Proprietorship" for precisely
    this reason. A Proprietorship and a purely salaried Individual are BOTH
    the "individual" assessee kind (assessee_kind_for_entity_type), so that
    lookup alone cannot answer whether business income is implied — a second,
    equally statutory question needs its own answer, served alongside the
    first by the one /assessee-kind call the screen already makes.
"""
from __future__ import annotations

from domain.income_tax.assessee import implies_business_income


def test_a_proprietorship_carries_business_income_by_definition():
    assert implies_business_income("Proprietorship") is True


def test_a_partnership_and_an_llp_do_too():
    # isEntity already routes both to the flat-rate, no-election branch on the
    # computation screen, so this is the same table used consistently rather
    # than special-cased down to only the reachable case.
    assert implies_business_income("Partnership") is True
    assert implies_business_income("LLP") is True


def test_a_purely_salaried_individual_is_not_assumed_to_have_business_income():
    # THE NEGATIVE CONTROL for the defect this module fixes: before it
    # existed, the only signal available to the screen was the typed business
    # income figure, so an ordinary salaried Individual client correctly
    # showed no Form 10-IEA guidance — and that must keep being true. An
    # "individual" assessee kind on its own (which a Proprietorship also
    # gets) must NOT be read as implying business income.
    assert implies_business_income("Individual") is False


def test_a_company_is_not_asked_this_question_at_all():
    # isCompany routes a domestic company to its own s.115BAA/s.115BAB panel;
    # this flag only ever feeds the individual's s.115BAC(6) election.
    assert implies_business_income("Private Limited") is False
    assert implies_business_income("Public Limited") is False


def test_an_unclassified_or_absent_entity_type_is_not_assumed_either():
    # Same direction as assessee_kind_for_entity_type's own refusal-over-guess
    # rule: a fact nobody has recorded is not silently turned into "yes".
    assert implies_business_income("Trust") is False
    assert implies_business_income(None) is False
    assert implies_business_income("") is False
    assert implies_business_income("Something Nobody Has Seen") is False


def test_matched_case_and_spacing_insensitively_like_every_other_entity_type_lookup():
    # normalise_entity_type is the one fold every entity-type table in this
    # codebase uses (compliance_obligation_service, assessee_kind_for_entity_type)
    # — a second, stricter comparison here would silently miss
    # 'proprietorship' or 'PROPRIETORSHIP' recorded straight off an import.
    assert implies_business_income("proprietorship") is True
    assert implies_business_income("PROPRIETORSHIP") is True
    assert implies_business_income(" Proprietorship ") is True


def test_the_assessee_kind_endpoint_serves_it_alongside_the_kind():
    from routers.income_tax import resolve_assessee_kind

    result = resolve_assessee_kind(entity_type="Proprietorship", current_user={"id": "u1"})
    assert result["data"]["kind"] == "individual"
    assert result["data"]["implies_business_income"] is True

    result = resolve_assessee_kind(entity_type="Individual", current_user={"id": "u1"})
    assert result["data"]["kind"] == "individual"
    assert result["data"]["implies_business_income"] is False
