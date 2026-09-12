"""PUR-32: the exact-duplicate guard cannot see a mistyped invoice number.

`_duplicate_bill_id`, with migration 313's unique index behind it, refuses a
second live bill carrying the same vendor's same number. Both match the number
as TYPED, stripped and lower-cased. So `INV-2025-1043` and `INV-2025-l043` are
two different keys, the index is satisfied, and the same supplier invoice is
booked twice: the expenditure counted twice, the input tax credit claimed twice
under CGST s.16, and the deductee reported twice on the quarterly statement.

`domain/purchases/near_duplicate` is the rule that sees it. These tests hold
its two limbs, the four things it deliberately does NOT flag, and the wiring
that carries the answer to a screen.
"""
from datetime import date

import pytest

from domain.purchases.near_duplicate import (
    DEFAULT_WINDOW_DAYS,
    near_duplicates,
    normalise_number,
)


def _bill(bill_no, bill_date, total_paise, **kw):
    return {"id": kw.pop("id", "existing-1"), "bill_no": bill_no,
            "bill_date": bill_date, "total_paise": total_paise,
            "status": kw.pop("status", "draft"),
            "deleted_at": kw.pop("deleted_at", None), **kw}


# ── the normaliser ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("INV-2025/0043", "inv 2025-43"),      # separators AND a leading zero
    ("INV/1043", "INV-1043"),              # separator only
    ("INV-2025-l043", "INV-2025-1043"),    # a lower-case L read as a one
    ("SB/25/8", "5B-25-8"),                # S read as 5
    ("BILL 007", "bill/7"),                # case AND leading zeros at once
])
def test_two_spellings_of_one_number_normalise_the_same(a, b):
    assert normalise_number(a) == normalise_number(b), (a, b)


def test_the_leading_zero_strip_survives_the_separator_strip():
    """The order is load-bearing and getting it wrong is silent.

    Removing separators FIRST fuses "2025" and "0043" into "20250043", which
    has no leading zero left to strip — the two spellings stay different, the
    warning never fires, and every test above still passes if written only on
    single-group numbers.
    """
    assert normalise_number("INV-2025-0043") == normalise_number("INV-2025-43")


def test_the_confusion_map_is_applied_after_upper_casing():
    """A case-SENSITIVE confusion map folds "B" to "8" and leaves "b" alone,
    so "BILL" and "bill" stop matching — the one pair a comparison of invoice
    numbers must always match. The first draft did exactly that."""
    assert normalise_number("BILL") == normalise_number("bill")
    assert normalise_number("SB/1") == normalise_number("sb-1")


def test_a_zero_run_inside_an_alphanumeric_group_is_kept():
    """"A007B" is a code, not the number seven — trimming inside it would
    invent a different one and match bills that are genuinely unrelated."""
    assert normalise_number("A007B") != normalise_number("A7B")


# ── limb 1: same money, near date ────────────────────────────────────────────

def test_the_same_amount_days_apart_is_reported():
    found = near_duplicates(
        bill_no="INV-1044", bill_date="2026-04-10", total_paise=1_18_000,
        existing=[_bill("INV-1043", "2026-04-08", 1_18_000)])
    assert [f.reason for f in found] == ["same_amount_near_date"]
    assert "input tax credit" in found[0].detail


def test_the_same_amount_outside_the_window_is_not():
    """A monthly retainer of the same round figure is ordinary business."""
    assert near_duplicates(
        bill_no="RETAINER-MAY", bill_date="2026-05-10", total_paise=1_18_000,
        existing=[_bill("RETAINER-APR", "2026-04-08", 1_18_000)]) == []


def test_the_window_boundary_is_inclusive():
    on_the_edge = near_duplicates(
        bill_no="XX", bill_date="2026-04-15", total_paise=500,
        existing=[_bill("YY", "2026-04-08", 500)])
    assert len(on_the_edge) == 1 and DEFAULT_WINDOW_DAYS == 7
    assert near_duplicates(
        bill_no="XX", bill_date="2026-04-16", total_paise=500,
        existing=[_bill("YY", "2026-04-08", 500)]) == []


def test_an_amount_a_rupee_apart_is_not_reported():
    """The amount is matched EXACTLY and never within a tolerance — a
    tolerance on the amount is a tolerance on the credit claimed, which is
    why domain/gst/itc_matching refuses to fuzz the tax either."""
    assert near_duplicates(
        bill_no="XX", bill_date="2026-04-10", total_paise=1_18_000,
        existing=[_bill("YY", "2026-04-10", 1_18_100)]) == []


def test_two_zero_value_bills_are_not_a_duplicate_pair():
    assert near_duplicates(
        bill_no="XX", bill_date="2026-04-10", total_paise=0,
        existing=[_bill("YY", "2026-04-10", 0)]) == []


# ── limb 2: the same number, spelled differently ─────────────────────────────

def test_a_one_for_l_typo_is_reported_even_with_different_money():
    """The typo case is precisely where one of the two FIGURES is also wrong,
    so this limb must not require the amounts to agree."""
    found = near_duplicates(
        bill_no="INV-2025-l043", bill_date="2026-04-10", total_paise=900_00,
        existing=[_bill("INV-2025-1043", "2020-01-02", 5_000_00)])
    assert [f.reason for f in found] == ["same_number_different_spelling"]
    assert "written differently" in found[0].detail


def test_a_separator_or_leading_zero_difference_is_reported():
    found = near_duplicates(
        bill_no="INV/2025/043", bill_date="2026-04-10", total_paise=1,
        existing=[_bill("INV-2025-43", "2019-04-10", 9)])
    assert [f.reason for f in found] == ["same_number_different_spelling"]


def test_a_vendors_next_invoice_is_not_a_duplicate():
    """THE reason this limb is not an edit distance. A vendor's own invoices
    are sequential: INV-1043 and INV-1044 differ by exactly one character and
    are two entirely ordinary bills. A one-edit rule warns on very nearly
    every bill a practice enters, and a warning that always fires is a
    warning a CA turns off."""
    assert near_duplicates(
        bill_no="INV-1044", bill_date="2026-04-10", total_paise=1,
        existing=[_bill("INV-1043", "2019-04-10", 9)]) == []


def test_a_transposition_is_not_claimed_to_be_caught():
    """1034 against 1043 is a real typo this limb does NOT see, and that is
    the accepted cost of not warning on every sequential invoice. Limb 1
    catches it whenever the amount and date agree, which is the usual case."""
    assert near_duplicates(
        bill_no="INV-1034", bill_date="2026-04-10", total_paise=1,
        existing=[_bill("INV-1043", "2019-04-10", 9)]) == []


# ── what it must never report ────────────────────────────────────────────────

def test_an_exact_duplicate_is_left_to_the_409():
    """Saying it twice, in two voices, is worse than saying it once."""
    assert near_duplicates(
        bill_no=" INV-1043 ", bill_date="2026-04-10", total_paise=500,
        existing=[_bill("inv-1043", "2026-04-10", 500)]) == []


def test_a_cancelled_bill_is_not_a_duplicate():
    """Cancelling and re-entering IS the correction — reporting the cancelled
    row would make the fix look like the mistake."""
    assert near_duplicates(
        bill_no="XX", bill_date="2026-04-10", total_paise=500,
        existing=[_bill("YY", "2026-04-10", 500, status="cancelled")]) == []


def test_a_soft_deleted_bill_is_not_a_duplicate():
    assert near_duplicates(
        bill_no="INV-1044", bill_date="2026-04-10", total_paise=500,
        existing=[_bill("YY", "2026-04-10", 500,
                        deleted_at="2026-04-11T00:00:00Z")]) == []


def test_a_date_object_is_read_as_well_as_a_string():
    found = near_duplicates(
        bill_no="XX", bill_date=date(2026, 4, 10), total_paise=500,
        existing=[_bill("YY", date(2026, 4, 9), 500)])
    assert len(found) == 1


# ── the wiring, end to end ───────────────────────────────────────────────────

def _e2e(monkeypatch):
    from models.invoices import PurchaseBillIn, PurchaseBillLineIn   # noqa: F401
    import routers.vendors as ve
    import routers.purchase_bills as pb
    from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa
    db = FakeDB()
    wire_e2e(monkeypatch, db, [ve, pb])
    db.seed("firms", {"id": "FIRM-PUR32"})
    db.seed("clients", {"id": "CLI", "firm_id": "FIRM-PUR32", "gstin": "27ABCDE1234F1Z5"})
    seed_standard_coa(db, "FIRM-PUR32", "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": "FIRM-PUR32",
                                  "client_id": "CLI", "name": "Svc", "kind": "service"})
    return pb, db


CALLER = {"firm_id": "FIRM-PUR32", "id": "u1", "auth_user_id": "u1",
          "email": "ca@f.test", "role": "Partner"}


def _create(pb, bill_no, bill_date="2026-06-01", rate_paise=1_000_000):
    from models.invoices import PurchaseBillIn, PurchaseBillLineIn
    return pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND-1", bill_date=bill_date, bill_no=bill_no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc",
                                  rate_paise=rate_paise, quantity=1,
                                  gst_rate_percent=0.0)]), CALLER)


def test_the_created_bill_carries_the_warning_to_the_screen(monkeypatch):
    """NC-7: without this, the rule can be perfect and no CA ever sees it."""
    pb, db = _e2e(monkeypatch)
    db.seed("vendors", {"id": "VEND-1", "firm_id": "FIRM-PUR32", "client_id": "CLI",
                        "name": "Supplier", "gstin": "27AABCU9603R1ZX"})
    first = _create(pb, "INV-2025-1043")
    assert first["success"], first
    assert "near_duplicates" not in first["data"], (
        "the first bill has nothing to be a duplicate of")

    second = _create(pb, "INV-2025-l043")            # lower-case L for a one
    assert second["success"], second
    warned = second["data"].get("near_duplicates") or []
    assert [w["reason"] for w in warned] == ["same_number_different_spelling"], warned
    assert warned[0]["bill_no"] == "INV-2025-1043"


def test_a_genuinely_different_bill_carries_no_warning(monkeypatch):
    pb, db = _e2e(monkeypatch)
    db.seed("vendors", {"id": "VEND-1", "firm_id": "FIRM-PUR32", "client_id": "CLI",
                        "name": "Supplier", "gstin": "27AABCU9603R1ZX"})
    assert _create(pb, "INV-2025-1043")["success"]
    later = _create(pb, "INV-2025-1044", bill_date="2026-07-01", rate_paise=2_500_000)
    assert "near_duplicates" not in later["data"]


# ── the wiring ───────────────────────────────────────────────────────────────

def test_the_router_carries_the_rule_rather_than_a_second_copy():
    """One implementation. A duplicate check written again inside the router
    is how the exact guard and the index came to need a test holding them
    together in the first place."""
    import inspect
    from routers import purchase_bills as pb
    src = inspect.getsource(pb)
    assert "near_duplicate.near_duplicates(" in src
    assert "_CONFUSABLE" not in src, "the confusion set belongs in the domain module"


def test_the_bulk_path_does_not_pay_for_the_warning():
    """400 imported bills must not become 400 extra reads for a warning
    nobody is watching while a CSV uploads."""
    import inspect
    from routers import purchase_bills as pb
    src = inspect.getsource(pb._create_purchase_bill_core)
    assert "bulk_cache is not None else _near_duplicates(" in src


def test_the_preflight_endpoint_is_mounted_and_is_a_post():
    from main import app
    routes = {(m, r.path) for r in app.routes
              for m in (getattr(r, "methods", set()) or set())}
    assert ("POST", "/api/purchase-bills/near-duplicates") in routes
    assert not any(p == "/api/purchase-bills/near-duplicates" and m == "GET"
                   for m, p in routes), (
        "an invoice number has no business in a URL or an access log")
