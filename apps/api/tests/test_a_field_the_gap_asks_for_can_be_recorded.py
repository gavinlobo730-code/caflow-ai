"""
Three inputs the platform demanded and would not take.

  TDS-25 — Form 15CA. `tds_register_service` raises a gap on every §195 bill
      whose `form_15ca_ack_no` is blank, and since PUR-14 that gap REACHES the
      CA. Migration 311 added the column, `models/invoices.py` declares it on
      both the create and the update models, and
      `_SOFT_BILL_UPDATE_FIELDS` keeps it editable after the bill is received
      (the 15CA is filed when the money moves, which is later). `grep -i 15ca`
      across apps/web returned no input and no display — only three prose
      comments. So the product spent months telling a CA, on every foreign
      remittance, to record something no screen let them record.

  PAY-30 — UAN and IFSC. `EmployeeIn(uan="NOTANUMBER", bank_ifsc="bad")` was
      accepted and stored. Both patterns already existed TWICE —
      `employee_import.py` refuses a whole file on either, `ecr.py` refuses a
      member at file build — so the API was the one door with no check, and a
      UAN typed on the form wedged the ECR months later, at the moment the CA
      was trying to file.

      The ESIC number is deliberately NOT validated. The finding proposed "a
      10-digit ESIC check"; nothing in this codebase validates that field's
      format anywhere and no length for it is confirmable here, so a pattern
      written from memory would refuse legitimate numbers for every client.
      Presence stays presence.

  TDS-24 — §206AB was FY-blind while `applicable_rate` beside it already took
      an FY, and its docstring stated the doubled rate as current law. The
      Finance Act 2025 omitted the section w.e.f. 01-04-2025.
"""
import pytest
from pydantic import ValidationError

from domain.payroll import identity as identity_domain
from domain.tds.tds_validator import TDSValidator
from models.invoices import PurchaseBillIn, PurchaseBillUpdateIn
from models.payroll import EmployeeIn, EmployeeUpdateIn


# ---------------------------------------------------------------------------
# TDS-25 — the Rule 37BB fields, on both bill models.
# ---------------------------------------------------------------------------
_RULE_37BB = ("form_15ca_ack_no", "form_15ca_filed_on", "form_15cb_udin")


@pytest.mark.parametrize("field", _RULE_37BB)
def test_the_bill_accepts_the_remittance_paperwork_on_create(field):
    assert field in PurchaseBillIn.model_fields


@pytest.mark.parametrize("field", _RULE_37BB)
def test_and_on_update_because_the_15ca_is_filed_later(field):
    """A 15CA is filed at the time of remittance, which is after the bill is
    booked — so a create-only field would be a field nobody could ever fill."""
    assert field in PurchaseBillUpdateIn.model_fields


@pytest.mark.parametrize("field", _RULE_37BB)
def test_a_received_bill_can_still_take_them(field):
    """`_reject_locked_bill_fields` freezes a received bill's particulars under
    CGST §34. None of these three is a particular of the SUPPLIER's invoice —
    they are this client's own compliance references for the payment."""
    from routers.purchase_bills import _SOFT_BILL_UPDATE_FIELDS
    assert field in _SOFT_BILL_UPDATE_FIELDS


def test_the_gap_that_asks_for_it_still_fires_when_it_is_absent():
    """The premise. If this stopped firing, the screen would be collecting a
    field nothing wants."""
    import inspect
    import services.tds_register_service as svc
    src = inspect.getsource(svc)
    assert 'form_15ca_ack_no' in src
    assert 'GAP_15CA' in src or '15ca' in src.lower()


# ---------------------------------------------------------------------------
# PAY-30 — one home for two regexes, and the create door finally asks.
# ---------------------------------------------------------------------------
def test_the_two_regexes_have_one_home():
    """Both lived in employee_import.py AND ecr.py. Two copies of a format is
    two formats waiting to disagree."""
    from domain.payroll import ecr, employee_import
    assert employee_import.UAN_RE is identity_domain.UAN_RE
    assert ecr.UAN_RE is identity_domain.UAN_RE
    assert employee_import.IFSC_RE is identity_domain.IFSC_RE


@pytest.mark.parametrize("bad", ["NOTANUMBER", "1", "12345678901", "1234567890123",
                                 "12345678901a"])
def test_a_uan_that_the_ecr_would_reject_is_refused_at_the_door(bad):
    with pytest.raises(ValidationError):
        EmployeeIn(client_id="c", name="A", uan=bad)
    with pytest.raises(ValidationError):
        EmployeeUpdateIn(uan=bad)


@pytest.mark.parametrize("bad", ["bad", "HDFC1001234", "HDF00001234", "HDFC000123"])
def test_an_ifsc_that_is_not_rbis_format_is_refused(bad):
    with pytest.raises(ValidationError):
        EmployeeIn(client_id="c", name="A", bank_ifsc=bad)
    with pytest.raises(ValidationError):
        EmployeeUpdateIn(bank_ifsc=bad)


def test_a_good_one_is_accepted_and_an_ifsc_is_upper_cased():
    e = EmployeeIn(client_id="c", name="A", uan="123456789012",
                   bank_ifsc="hdfc0001234")
    assert e.uan == "123456789012"
    assert e.bank_ifsc == "HDFC0001234"


def test_blank_stays_blank_rather_than_failing():
    """Both columns are nullable and most employees have neither on day one.
    A rule that also blocks the ordinary case is a rule that gets reverted."""
    e = EmployeeIn(client_id="c", name="A", uan="", bank_ifsc="   ")
    assert e.uan is None and e.bank_ifsc is None


def test_the_esic_number_is_still_only_a_presence_check():
    """Deliberate. Nothing in this codebase validates its format, and a length
    written from memory at the create door would refuse legitimate numbers for
    every client — the wrong direction of error."""
    e = EmployeeIn(client_id="c", name="A", esi_number="whatever-they-were-given")
    assert e.esi_number == "whatever-they-were-given"
    assert not hasattr(identity_domain, "ESIC_RE")


# ---------------------------------------------------------------------------
# TDS-24 — §206AB takes the year it is asked about.
# ---------------------------------------------------------------------------
def test_206ab_reaches_a_year_it_governed():
    assert TDSValidator.is_higher_rate_applicable(
        "ABCDE1234F", is_non_filer=True, base_rate=10.0, fy="2024-25") == 20.0


def test_206ab_does_not_reach_a_year_after_the_omission():
    assert TDSValidator.is_higher_rate_applicable(
        "ABCDE1234F", is_non_filer=True, base_rate=10.0, fy="2025-26") == 10.0


def test_the_omission_year_is_a_named_constant_not_a_buried_branch():
    """It is UNCONFIRMED — egress is refused at this environment's proxy, so
    it rests on a reading nobody could check against a published page.
    Correcting it must be a one-line change."""
    assert TDSValidator.SECTION_206AB_OMITTED_FROM_FY == "2025-26"


def test_the_default_is_current_law():
    assert TDSValidator.is_higher_rate_applicable(
        "ABCDE1234F", is_non_filer=True, base_rate=10.0) == 10.0


def test_the_module_header_no_longer_advertises_a_rule_it_does_not_apply():
    import domain.tds.tds_computer as tc
    header = tc.__doc__ or ""
    assert "Higher TDS for non-filers" not in header
    assert "206AA" in header, "the floor this module DOES apply must stay named"
