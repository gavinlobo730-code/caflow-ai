"""The supplier's account reaches a screen, and its balance names the right party.

`GET /api/vendors/{id}/statement` was built, tested and REACHED BY NOBODY while
the Sales screen carried a whole Statements tab — the AP mirror of a live AR
feature. Wiring it up is half the fix; the other half is that the two
statements are not the same document with a different noun.

⚠️ THE SIGN IS THE PART THAT MATTERS. `customer_statement_service` runs the
running balance DEBIT-positive (the customer owes) and
`vendor_statement_service` runs it CREDIT-positive (a bill increases what the
CLIENT owes). Printing the customer's convention on a vendor statement states
the debt against the wrong party, on a document somebody reconciles a
supplier's own statement against — and it would look entirely plausible.
"""
import ast
import inspect
from pathlib import Path

import pytest

from services import statement_pdf_service as sps
from services import vendor_statement_service as vss
from services import customer_statement_service as css


# ── the two kinds differ, and differ in the way that matters ────────────────

def test_a_payable_and_a_receivable_take_opposite_sides():
    assert sps.CUSTOMER.positive_side == "Dr"
    assert sps.VENDOR.positive_side == "Cr"
    assert sps.CUSTOMER.positive_side != sps.VENDOR.positive_side


@pytest.mark.parametrize(
    "paise,side,expected_tail",
    [(1000, "Dr", "Dr"), (-1000, "Dr", "Cr"), (1000, "Cr", "Cr"), (-1000, "Cr", "Dr"), (0, "Cr", "Cr")],
)
def test_the_balance_takes_the_side_it_is_given(paise, side, expected_tail):
    assert sps._bal(paise, side).endswith(expected_tail)


def test_the_default_side_is_the_customers_so_existing_callers_are_unchanged():
    """`_bal` gained a parameter. Its default must be what every caller before
    the vendor statement relied on, or the customer PDF silently flips."""
    assert sps._bal(1000).endswith("Dr")
    assert sps._bal(-1000).endswith("Cr")


def test_each_kind_reads_its_own_party_key():
    assert sps.CUSTOMER.party_key == "customer"
    assert sps.VENDOR.party_key == "vendor"


# ── the totals keys are real, which is the silent one ───────────────────────

def _emitted_totals(module, builder_args) -> set:
    return set(module.build_statement(*builder_args)["totals"])


def test_the_vendor_totals_name_keys_the_vendor_service_actually_emits():
    """A mistyped key prints Rs.0.00 and looks like a supplier with no activity.

    Asserted against what `build_statement` PRODUCES rather than against a
    second list, so a service that renames a total fails here instead of
    quietly zeroing a line on the PDF.
    """
    emitted = _emitted_totals(vss, ({"id": "v1", "name": "V"}, "2026-04-01", "2027-03-31", [], [], []))
    for _label, key in sps.VENDOR.totals:
        assert key in emitted, f"{key} is not a key vendor_statement_service emits"


def test_the_customer_totals_name_keys_the_customer_service_actually_emits():
    emitted = _emitted_totals(css, ({"id": "c1", "name": "C"}, "2026-04-01", "2027-03-31", [], [], []))
    for _label, key in sps.CUSTOMER.totals:
        assert key in emitted, f"{key} is not a key customer_statement_service emits"


def test_the_two_kinds_do_not_share_a_totals_key_set():
    """The premise of the two tests above. If both services emitted the same
    keys, either kind would satisfy either assertion and neither would mean
    anything."""
    assert {k for _, k in sps.CUSTOMER.totals} != {k for _, k in sps.VENDOR.totals}


# ── one builder, not two ────────────────────────────────────────────────────

def test_there_is_exactly_one_statement_pdf_builder():
    """Two builders are two documents that look like two products after the
    first formatting change. The vendor wrapper must CALL the shared one."""
    src = Path(inspect.getfile(sps)).read_text()
    tree = ast.parse(src)
    builders = [n.name for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and "build" in n.name and "pdf" in n.name]
    assert builders == ["build_statement_pdf"], builders

    wrapper = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "get_vendor_statement_pdf")
    called = {c.func.id for c in ast.walk(wrapper)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "build_statement_pdf" in called


def test_the_vendor_wrapper_passes_the_vendor_kind():
    """A wrapper that shares the builder and forgets the kind is WORSE than a
    copy: it renders a vendor statement with the customer's sign, headings and
    totals, and nothing about it looks wrong."""
    src = Path(inspect.getfile(sps)).read_text()
    wrapper = next(n for n in ast.walk(ast.parse(src))
                   if isinstance(n, ast.FunctionDef) and n.name == "get_vendor_statement_pdf")
    names = {n.id for n in ast.walk(wrapper) if isinstance(n, ast.Name)}
    assert "VENDOR" in names


# ── the account holder is the client, on both ───────────────────────────────

def test_the_vendor_statement_is_headed_by_the_client_not_the_practice():
    """`load_account_holder` refuses rather than defaulting to the firm — the
    same fix the customer statement needed, and for a sharper reason here: a
    statement of a supplier's account headed with the CA practice's name states
    that the PRACTICE owes the money."""
    src = Path(inspect.getfile(sps)).read_text()
    wrapper = next(n for n in ast.walk(ast.parse(src))
                   if isinstance(n, ast.FunctionDef) and n.name == "get_vendor_statement_pdf")
    called = {c.func.id for c in ast.walk(wrapper)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "load_account_holder" in called


# ── it is a reconciliation, so nothing is sent ──────────────────────────────

def test_nothing_emails_a_vendor_statement():
    """Recorded rather than assumed. A customer statement chases money and logs
    every delivery; a vendor statement is what the CA compares the supplier's
    own against. Adding an email path means a deliveries table and a migration,
    which is a feature rather than the unwiring this fixed — so if one appears,
    it should be a deliberate change to this test."""
    src = Path(__file__).parent.parent / "routers" / "vendors.py"
    body = src.read_text()
    assert "statement/pdf" in body
    assert "statement/email" not in body


def test_the_pdf_route_is_mounted_and_scoped():
    from routers import vendors as r
    # The router carries its own prefix, so the mounted path is the full one —
    # asserting the bare suffix passed against nothing and reported a missing
    # route that was there.
    want = "/api/vendors/{vendor_id}/statement/pdf"
    paths = {getattr(rt, "path", "") for rt in r.router.routes}
    assert want in paths, sorted(p for p in paths if "statement" in p)
    # Every read on this router is client-scoped; the PDF is not an exception.
    fn = next(rt.endpoint for rt in r.router.routes if getattr(rt, "path", "") == want)
    assert "client_id" in inspect.signature(fn).parameters
