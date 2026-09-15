"""
GSTR-3B Table 4(A)(2) is filled, and 4(A)(1)/(4) say why they cannot be. GST-24.

WHAT WAS WRONG
    `itc_avl_rows` emitted all five rows of Table 4(A) in the utility's order —
    that much was fixed earlier — but hardcoded IMPG, IMPS and ISD to zero and
    put the WHOLE of the reverse-charge credit on 4(A)(3), ISRC.

    ISRC is Inward Supplies liable to Reverse Charge: the domestic §9(3)/(4)
    line. An IMPORT OF SERVICES is also reverse-charged — Notification
    10/2017-Integrated Tax (Rate) entry 1 puts it on the recipient — so on the
    books it is indistinguishable from a goods-transport-agency or advocate
    bill, and it went out on the wrong line of a filed return. IGST Act §2(11)
    defines it: supplier outside India, recipient in India, place of supply in
    India.

WHY THIS IS SAFE, AND THE TESTS THAT SAY SO
    The split moves a figure BETWEEN TWO ROWS INSIDE 4(A). The total 4(A), the
    4(C) net, the Table 3.1(d) liability and the challan are all untouched, and
    each of those is asserted below against the same books computed with and
    without the flag. Nothing about what the client pays changes; what changes
    is which line of the return declares the credit.

WHAT SEPARATES THEM, AND WHAT DOES NOT
    `vendors.residential_status` (migration 308), read through
    `domain.tds.residency.is_non_resident` — the module that already decides
    what that column means. NULL is a real third state, "nobody has said", and
    a NULL vendor stays exactly where every vendor is today. An unstated
    residency therefore cannot move a figure, which is the only safe direction
    for a change that alters a filed return's face.

    IMPORT OF GOODS is not derivable and is not a gap in the arithmetic: IGST
    on goods is collected at customs against a Bill of Entry, never
    self-assessed on a purchase bill, so it is not a reverse-charge document at
    all. ISD is the same — an Input Service Distributor invoice is a document
    type this product does not model. Both are NAMED, because a nil that means
    "we cannot see it" is not the same as a nil that means "there was none".
"""
from __future__ import annotations

import pytest

from domain.gst.gstr3b_computer import (
    PurchaseTransaction, SalesTransaction, compute_gstr3b,
)

GSTIN = "27AAAAA0000A1Z2"
PERIOD = "042026"


def _sale(cgst, sgst):
    return SalesTransaction("invoice", (cgst + sgst) * 100 // 18, cgst, sgst, 0, 0,
                            "taxable", False)


def _purchase(cgst=0, sgst=0, igst=0, *, rcm=False, imps=False, cess=0):
    taxable = (cgst + sgst + igst) * 100 // 18 if (cgst or sgst or igst) else 0
    return PurchaseTransaction(
        taxable, cgst, sgst, igst, cess, rcm, is_import_of_services=imps)


def _rows(sales=(), purchases=(), reversals=()):
    r = compute_gstr3b(list(sales), list(purchases), [], list(reversals))
    return {ty: (i, c, s, x) for ty, i, c, s, x in r.itc_avl_rows()}


def _result(sales=(), purchases=(), reversals=()):
    return compute_gstr3b(list(sales), list(purchases), [], list(reversals))


DOMESTIC_RCM = _purchase(9000, 9000, rcm=True)              # a GTA bill, say
IMPORTED_SERVICE = _purchase(igst=18000, rcm=True, imps=True)
ORDINARY = _purchase(45000, 45000)


# ── The split itself ─────────────────────────────────────────────────────────

def test_an_imported_service_is_declared_on_4a2_not_4a3():
    rows = _rows([_sale(90000, 90000)], [IMPORTED_SERVICE])
    assert rows["IMPS"] == (18000, 0, 0, 0)
    assert rows["ISRC"] == (0, 0, 0, 0), (
        "an import of services was declared on the DOMESTIC reverse-charge "
        "line; IGST Act §2(11) gives it 4(A)(2) of its own")


def test_a_domestic_reverse_charge_supply_stays_on_4a3():
    rows = _rows([_sale(90000, 90000)], [DOMESTIC_RCM])
    assert rows["ISRC"] == (0, 9000, 9000, 0)
    assert rows["IMPS"] == (0, 0, 0, 0)


def test_the_two_are_separated_within_one_period():
    rows = _rows([_sale(90000, 90000)], [ORDINARY, DOMESTIC_RCM, IMPORTED_SERVICE])
    assert rows["IMPS"] == (18000, 0, 0, 0)
    assert rows["ISRC"] == (0, 9000, 9000, 0)
    assert rows["OTH"] == (0, 45000, 45000, 0)


def test_an_ordinary_purchase_reaches_neither():
    rows = _rows([_sale(90000, 90000)], [ORDINARY])
    assert rows["IMPS"] == (0, 0, 0, 0)
    assert rows["ISRC"] == (0, 0, 0, 0)


# ── Nothing that decides money may move ──────────────────────────────────────
#
# The whole safety argument for this change, asserted rather than reasoned:
# the same books with and without the flag differ ONLY in the 4(A) row split.

@pytest.mark.parametrize("figure", [
    "itc_avail_igst", "itc_avail_cgst", "itc_avail_sgst", "itc_avail_cess",
    "itc_net_igst", "itc_net_cgst", "itc_net_sgst", "itc_net_cess",
    "rcm_igst", "rcm_cgst", "rcm_sgst", "rcm_cess",
    "rcm_cash_paise", "cash_payable_paise",
    "net_igst", "net_cgst", "net_sgst",
])
def test_the_flag_changes_no_figure_that_decides_what_is_paid(figure):
    sales = [_sale(90000, 90000)]
    flagged = _result(sales, [ORDINARY, _purchase(igst=18000, rcm=True, imps=True)])
    plain = _result(sales, [ORDINARY, _purchase(igst=18000, rcm=True, imps=False)])
    assert getattr(flagged, figure) == getattr(plain, figure), (
        f"{figure} moved. Splitting 4(A)(2) out of 4(A)(3) must change the "
        "ROW a credit is declared on and nothing else — not the liability, "
        "not the credit, and not the challan")


def test_the_liability_is_the_same_because_imps_is_a_subset_of_rcm():
    """imps_* is carried alongside rcm_*, never added to it. If it were added,
    the 3.1(d) liability and the cash on the challan would both double."""
    r = _result([_sale(90000, 90000)], [IMPORTED_SERVICE])
    assert r.rcm_igst == 18000
    assert r.imps_igst == 18000
    assert r.rcm_cash_paise == 18000


# ── The five rows still sum to 4(A), including when the cap bites ────────────

def _sum_rows(rows: dict) -> tuple[int, int, int, int]:
    return tuple(sum(r[k] for r in rows.values()) for k in range(4))


def test_the_five_rows_sum_to_4a():
    sales = [_sale(90000, 90000)]
    purchases = [ORDINARY, DOMESTIC_RCM, IMPORTED_SERVICE]
    r = _result(sales, purchases)
    rows = {ty: (i, c, s, x) for ty, i, c, s, x in r.itc_avl_rows()}
    assert _sum_rows(rows) == (
        r.itc_avail_igst, r.itc_avail_cgst, r.itc_avail_sgst, r.itc_avail_cess)


@pytest.mark.parametrize("avail,imps,rcm,expect_imps,expect_isrc", [
    # Ceiling above both: neither is trimmed.
    (30000, 18000, 27000, 18000, 9000),
    # Ceiling between them: IMPS is whole, ISRC takes what is left.
    (20000, 18000, 27000, 18000, 2000),
    # Ceiling below IMPS alone: IMPS is trimmed and ISRC gets nothing.
    (10000, 18000, 27000, 10000, 0),
    # No credit at all: both rows are nil.
    (0, 18000, 27000, 0, 0),
])
def test_the_two_capped_rows_never_exceed_the_credit_between_them(
        avail, imps, rcm, expect_imps, expect_isrc):
    """THE CAP ORDER IS THE POINT, and this tests the arithmetic directly.

    Both reverse-charge rows are capped at the credit available so the five sum
    to exactly 4(A) — without it, a period where the Rule 36(4) cap trimmed
    credit below the reverse-charge tax files a 4(A) that does not reconcile
    with its own 4(C). Capping each row INDEPENDENTLY against the same ceiling
    lets the two together exceed it, so IMPS takes the ceiling first and ISRC
    takes what is left of it.

    Driven on the result object rather than through a books fixture because
    the ceiling is `itc_avail_igst`, which is GROSS 4(A) — blocked credit
    included, per Circular 170/02/2022-GST — so §17(5) cannot lower it and
    only the Rule 36(4) path can. The property under test is the arithmetic,
    and this states it without contriving that path.
    """
    from domain.gst.gstr3b_computer import GSTR3BResult

    r = GSTR3BResult()
    r.itc_igst = avail
    r.imps_igst = imps
    r.rcm_igst = rcm
    assert r.itc_avail_igst == avail, "fixture assumption about the ceiling"

    rows = {ty: (i, c, s, x) for ty, i, c, s, x in r.itc_avl_rows()}
    assert rows["IMPS"][0] == expect_imps
    assert rows["ISRC"][0] == expect_isrc
    assert rows["IMPS"][0] + rows["ISRC"][0] <= avail
    assert _sum_rows(rows)[0] == avail


def test_no_row_is_ever_negative():
    """`OTH` is the remainder after both capped rows. If the cap let them
    overshoot, the general bucket would go negative and the portal would
    reject the return."""
    r = _result([_sale(90000, 90000)], [DOMESTIC_RCM, IMPORTED_SERVICE])
    for ty, i, c, s, x in r.itc_avl_rows():
        assert min(i, c, s, x) >= 0, f"{ty} carries a negative figure"


# ── The payload still has the shape the GSTN utility writes ──────────────────

def test_the_payload_still_writes_five_rows_in_form_order():
    p = _result([_sale(90000, 90000)], [IMPORTED_SERVICE]).as_gstn_payload(GSTIN, PERIOD)
    assert [r["ty"] for r in p["itc_elg"]["itc_avl"]] == [
        "IMPG", "IMPS", "ISRC", "ISD", "OTH"]


def test_the_imported_service_reaches_the_payload_in_rupees():
    p = _result([_sale(90000, 90000)], [IMPORTED_SERVICE]).as_gstn_payload(GSTIN, PERIOD)
    imps = [r for r in p["itc_elg"]["itc_avl"] if r["ty"] == "IMPS"][0]
    assert imps["iamt"] == 180, "18000 paise is Rs 180, whole rupees for 3B"


# ── What the books cannot see is named, not silently nil ─────────────────────

def test_the_one_underivable_row_is_named_with_its_reason():
    """4(A)(1) LEFT THIS LIST ON 2026-09-14 (PUR-18). A Bill of Entry is a
    document now — migration 389 — so the row is derived like any other credit.
    ISD is still here: an Input Service Distributor invoice is a document type
    nothing models, and a nil meaning "we cannot see it" is not a nil meaning
    "there was none"."""
    from services.gst_return_service import _table_4a_gaps

    gaps = {g["row"]: g for g in _table_4a_gaps()}
    assert set(gaps) == {"4(A)(4)"}, (
        "4(A)(1) and 4(A)(2) are derived from the books now and must not be "
        "listed as gaps; 4(A)(3) and 4(A)(5) always were")
    assert "Input Service Distributor" in gaps["4(A)(4)"]["reason"]
    for g in gaps.values():
        assert g["label"] and g["reason"].endswith("Enter it on the portal.")


def test_the_gap_is_on_every_return_not_only_a_failing_one():
    """A structural gap does not depend on the period's data — it is a fact
    about what this product models. A CA reading a nil 4(A)(4) has to be told
    the same thing whether or not a head office distributed anything."""
    from services.gst_return_service import _table_4a_gaps

    assert len(_table_4a_gaps()) == 1


# ── The books-side resolver ──────────────────────────────────────────────────

def test_only_a_recorded_non_resident_is_an_import_of_services():
    """NULL is "nobody has said", and it must leave the row where it is. The
    resolver delegates to the module that owns that question rather than
    comparing the string itself."""
    from domain.tds.residency import is_non_resident

    assert is_non_resident("non_resident") is True
    assert is_non_resident("resident") is False
    assert is_non_resident(None) is False
    assert is_non_resident("") is False


def test_the_resolver_asks_the_residency_module_rather_than_matching_a_string():
    import inspect

    from services import gst_return_service

    fn = gst_return_service._import_of_services_vendors
    # The docstring quotes the spelling it bans, so strip it before scanning —
    # the same trap this repo has hit in three separate guards now.
    src = inspect.getsource(fn).replace(fn.__doc__ or "", "")
    assert "is_non_resident" in src
    assert '== "non_resident"' not in src, (
        "compare through domain.tds.residency, which is where NULL's meaning "
        "is decided; a bare string comparison here is a second answer")


# ── End to end, through the books ────────────────────────────────────────────
#
# THE TWO NEGATIVE CONTROLS THAT MISSED WITHOUT THIS. Everything above tests
# the domain function and the residency helper in isolation, so disconnecting
# them — setting `is_import_of_services=False` on every bill, or reading a NULL
# residency as non-resident — changed no assertion at all. The feature could
# have been entirely unwired and the file stayed green.

def _e2e_setup(monkeypatch):
    import routers.purchase_bills as pb
    import routers.sales_invoices as si
    from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, pb])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": "FIRM-A", "gstin": GSTIN,
                        "financial_year_start": "2025-04-01"})
    # One vendor of each kind, plus one nobody has classified.
    db.seed("vendors", {"id": "V-RES", "firm_id": "FIRM-A", "client_id": "CLI",
                        "name": "Domestic GTA", "state_code": "27",
                        "residential_status": "resident", "tds_applicable": False})
    db.seed("vendors", {"id": "V-NRI", "firm_id": "FIRM-A", "client_id": "CLI",
                        "name": "Foreign Consultant", "state_code": "27",
                        "residential_status": "non_resident", "tds_applicable": False})
    db.seed("vendors", {"id": "V-NULL", "firm_id": "FIRM-A", "client_id": "CLI",
                        "name": "Unclassified", "state_code": "27",
                        "tds_applicable": False})
    seed_standard_coa(db, "FIRM-A", "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": "FIRM-A", "client_id": "CLI",
                                  "name": "Consultancy", "kind": "service"})
    return db


def _e2e_bill(db, no, vendor, rate):
    import routers.purchase_bills as pb
    from models.invoices import PurchaseBillIn, PurchaseBillLineIn

    caller = {"firm_id": "FIRM-A", "id": "u-int", "auth_user_id": "auth",
              "email": "ca@f.test", "role": "Partner"}
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vendor, bill_date="2025-06-12", bill_no=no,
        is_reverse_charge=True,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc",
                                  rate_paise=rate, quantity=1, gst_rate_percent=18.0)],
    ), caller)
    assert res["success"] is True, res
    assert pb.receive_purchase_bill(res["data"]["id"], caller)["success"] is True
    return res["data"]


def _e2e_avl(db):
    import services.gst_return_service as grs

    out = grs.gstr3b_from_books(db, "FIRM-A", "CLI", "062025", GSTIN)
    return {r["ty"]: r for r in out["payload"]["itc_elg"]["itc_avl"]}, out


def test_a_bill_from_a_non_resident_vendor_reaches_4a2(monkeypatch):
    db = _e2e_setup(monkeypatch)
    _e2e_bill(db, "BILL-NRI", "V-NRI", 5_00000)      # Rs 5,000 @ 18% RCM
    avl, _ = _e2e_avl(db)
    assert avl["IMPS"]["camt"] + avl["IMPS"]["samt"] == 900, avl["IMPS"]
    assert avl["ISRC"]["camt"] + avl["ISRC"]["samt"] == 0, (
        "a reverse-charge bill from a vendor recorded as non-resident is an "
        "import of services and belongs on 4(A)(2)")


def test_a_bill_from_a_resident_vendor_stays_on_4a3(monkeypatch):
    db = _e2e_setup(monkeypatch)
    _e2e_bill(db, "BILL-RES", "V-RES", 5_00000)
    avl, _ = _e2e_avl(db)
    assert avl["ISRC"]["camt"] + avl["ISRC"]["samt"] == 900
    assert avl["IMPS"]["camt"] + avl["IMPS"]["samt"] == 0


def test_a_vendor_nobody_has_classified_stays_where_it_was(monkeypatch):
    """NULL residency is "nobody has said". Reading it as non-resident would
    move every unclassified vendor's reverse-charge credit onto the import
    line on the next return a CA files."""
    db = _e2e_setup(monkeypatch)
    _e2e_bill(db, "BILL-NULL", "V-NULL", 5_00000)
    avl, _ = _e2e_avl(db)
    assert avl["ISRC"]["camt"] + avl["ISRC"]["samt"] == 900
    assert avl["IMPS"]["camt"] + avl["IMPS"]["samt"] == 0


def test_the_three_kinds_are_separated_on_one_return(monkeypatch):
    db = _e2e_setup(monkeypatch)
    _e2e_bill(db, "B-NRI", "V-NRI", 5_00000)
    _e2e_bill(db, "B-RES", "V-RES", 3_00000)
    _e2e_bill(db, "B-NULL", "V-NULL", 2_00000)
    avl, out = _e2e_avl(db)
    assert avl["IMPS"]["camt"] + avl["IMPS"]["samt"] == 900       # 5,000 @ 18%
    assert avl["ISRC"]["camt"] + avl["ISRC"]["samt"] == 900       # (3,000 + 2,000) @ 18%
    # And the liability is unmoved: all three are still reverse-charge.
    assert out["rcm_cash_paise"] == 180000


def test_the_return_names_the_row_it_cannot_derive(monkeypatch):
    db = _e2e_setup(monkeypatch)
    _e2e_bill(db, "B-NRI", "V-NRI", 5_00000)
    _, out = _e2e_avl(db)
    assert [g["row"] for g in out["table_4a_gaps"]] == ["4(A)(4)"]
