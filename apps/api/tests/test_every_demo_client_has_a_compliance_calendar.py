"""Every seeded client has the obligations its books imply, and only those.

WHAT WAS WRONG (PRE-A-004, found by driving the seeded firm)
    Compliance obligations are not created with a client. They come from the 06:00 IST sweep for the current year,
    lazily when somebody opens a client's overview (GST only), and for the return, TDS, payroll, advance tax and the
    company's filings from a fee engagement's service type. The seeder created no engagement, so the compliance
    calendar of a practice with eight clients was empty -- and a client with no GSTIN (Priya Sharma) had no obligation
    of any kind, however it was reached.

THE RULES
    * A client has an engagement for each thing it files (`fixture.engagements_for`): GST only with a GSTIN, TDS
      only if it deducts, payroll only if it runs it, the MCA filings only for a company, advance tax for anyone but
      an individual. Asked of the PURE generator (`obligations_for_service`) so the fixture and the generator cannot
      disagree about what a service type implies.
    * Every engagement implies at least one obligation, and every client at least one in total.
    * A client with no GSTIN is given no GST obligation: only a registered person owes GSTR-1/3B/9 (CGST ss.25, 37,
      39, 44).
"""
from __future__ import annotations

import pytest

from domain.demo import fixture
from services import compliance_obligation_service as ob

FY = "2025-26"
FIRM = fixture.build(FY)
GST_TYPES = {"GSTR1", "GSTR3B", "PMT06", "GSTR9"}


def _specs(client, engagement):
    return ob.obligations_for_service(
        engagement.service_type, FY,
        gst_frequency=client.gst_filing_frequency,
        entity_type=client.entity_type,
        client_has_gstin=bool(client.gstin),
    )


@pytest.mark.parametrize("client", FIRM.clients, ids=lambda c: c.name)
def test_every_client_has_obligations(client):
    assert client.engagements, f"{client.name} has no engagement, so no deadline"
    types = {s["obligation_type"] for e in client.engagements for s in _specs(client, e)}
    assert types, f"{client.name}: no engagement implies any obligation"


@pytest.mark.parametrize("client", FIRM.clients, ids=lambda c: c.name)
def test_every_engagement_implies_something(client):
    for e in client.engagements:
        assert _specs(client, e), f"{client.name}: {e.service_type!r} implies no obligation"


def test_gst_is_owed_only_by_a_registered_client():
    for c in FIRM.clients:
        types = {s["obligation_type"] for e in c.engagements for s in _specs(c, e)}
        if c.gstin:
            assert GST_TYPES & types, f"{c.name} has a GSTIN and no GST obligation"
        else:
            assert not (GST_TYPES & types), f"{c.name} has no GSTIN and was given a GST obligation"


def test_each_service_is_there_for_the_reason_the_client_files_it():
    for c in FIRM.clients:
        names = {e.service_type for e in c.engagements}
        assert ("GST Returns" in names) == bool(c.gstin), c.name
        assert ("TDS Returns" in names) == c.deducts_tax, c.name
        assert ("Payroll Processing" in names) == bool(c.employees), c.name
        assert ("ROC and MCA Annual Filings" in names) == (c.entity_type == "Private Limited"), c.name
        assert ("Advance Tax" in names) == (c.entity_type != "Individual"), c.name
        assert "Income Tax Return" in names, c.name


def test_the_quarterly_filer_is_engaged_quarterly_and_the_rest_monthly():
    for c in FIRM.clients:
        gst = [e for e in c.engagements if e.service_type == "GST Returns"]
        if gst:
            assert gst[0].billing_cycle == ("Quarterly" if c.gst_filing_frequency == "quarterly" else "Monthly")


def test_the_fees_are_whole_rupees_in_paise_and_the_cycles_are_ones_the_table_allows():
    allowed = {"Monthly", "Quarterly", "Half-Yearly", "Annually", "One-time"}
    for c in FIRM.clients:
        for e in c.engagements:
            assert e.fee_paise > 0 and e.fee_paise % 100 == 0, (c.name, e)
            assert e.billing_cycle in allowed, (c.name, e)


def test_two_services_never_share_a_string_the_generator_would_read_as_one():
    """`obligations_for_service` takes ONE branch of "advance tax" / "income tax": a combined service type would
    silently generate only the first, which is why they are two engagements."""
    for c in FIRM.clients:
        for e in c.engagements:
            s = e.service_type.lower()
            assert not ("advance tax" in s and "income tax" in s), e
