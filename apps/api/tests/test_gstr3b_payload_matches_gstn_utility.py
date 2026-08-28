"""The GSTR-3B payload must match the shape GSTN's own generator produces.

WHERE THE REFERENCE COMES FROM
    Every expectation in this file was read out of the VBA inside
    GSTR3B_Excel_Utility_V5.8.xlsm — the offline utility GSTN publishes at
    gst.gov.in (Downloads > Offline Tools). That macro is the authority on the
    JSON the portal accepts: it is what a taxpayer filing by hand actually
    uploads. Sheet row numbers below are the rows on its "GSTR-3B" sheet, so
    each claim can be traced back.

    It matters that this is not a reading of Circular 170/02/2022-GST. The
    circular says which figure belongs in which BOX. It says nothing about
    what the boxes are called in JSON, and getting the law right while getting
    the codes wrong produces a return that is correct and unfilable.

WHAT WAS WRONG — three faults, none of which any amount of reasoning found

    1. itc_avl was ONE object typed "ISRC" carrying the whole credit. The
       utility writes FIVE (rows 31-35), and "ISRC" is row 4(A)(3), Inward
       Supplies Reverse Charge. So every rupee of a client's input tax credit
       was declared on the reverse-charge line of a filed return. The general
       bucket, 4(A)(5) "All other ITC", is "OTH".

    2. itc_inelg was one "OTH" object. The utility writes two (rows 41-42):
       "RUL" is 4(D)(1), credit reclaimed after an earlier 4(B)(2) reversal,
       and "OTH" is 4(D)(2).

    3. inward_sup.isup_details carried {"ty": "RCM", "inter", "intra_cgst",
       "intra_sgst"} — a code and two field names that do not exist. That block
       is section 5 of the form, exempt / nil-rated / non-GST INWARD supplies,
       written as "GST" and "NONGST" with "inter" and "intra" (rows 48-49). The
       reverse-charge liability belongs in sup_details.isup_rev, and was
       already there.

    A fourth gap: eco_dtls (Table 3.1.1, CGST Act §9(5) e-commerce) was never
    emitted. The utility writes it for every period from July 2022.
"""
import pytest

from domain.gst.gstr3b_computer import (
    ITCReversal, PurchaseTransaction, SalesTransaction, compute_gstr3b,
)

GSTIN = "27AAAAA0000A1Z5"
PERIOD = "042026"


def _payload(sales=(), purchases=(), reversals=(), period=PERIOD):
    return compute_gstr3b(list(sales), list(purchases), [], list(reversals)) \
        .as_gstn_payload(GSTIN, period)


def _sale(cgst, sgst):
    return SalesTransaction("invoice", (cgst + sgst) * 100 // 18, cgst, sgst, 0, 0,
                            "taxable", False)


def _purchase(cgst, sgst, *, rcm=False, blocked_cgst=0, blocked_sgst=0):
    return PurchaseTransaction(
        (cgst + sgst) * 100 // 18, cgst, sgst, 0, 0, rcm,
        ineligible_cgst_paise=blocked_cgst, ineligible_sgst_paise=blocked_sgst)


ORDINARY = _purchase(45000, 45000)          # Rs 5,000 @ 18%
REVERSE_CHARGE = _purchase(9000, 9000, rcm=True)   # Rs 1,000 @ 18%, RCM


def _t4(p):
    return p["itc_elg"]


def _row(rows, ty):
    matches = [r for r in rows if r["ty"] == ty]
    assert len(matches) == 1, f"expected exactly one {ty!r} row, got {len(matches)}"
    return matches[0]


# ── Table 4(A): five rows, in order ──────────────────────────────────────────

def test_itc_avl_has_the_five_rows_the_form_has_in_the_utilitys_order():
    """VBA: `For i = 31 To 35`, one object per sheet row, unconditionally."""
    assert [r["ty"] for r in _t4(_payload())["itc_avl"]] == [
        "IMPG", "IMPS", "ISRC", "ISD", "OTH"]


def test_ordinary_credit_is_declared_as_all_other_itc_not_reverse_charge():
    """THE BUG. A client with no reverse-charge purchases at all had their
    entire credit filed on the reverse-charge line."""
    avl = _t4(_payload([_sale(90000, 90000)], [ORDINARY]))["itc_avl"]
    assert _row(avl, "OTH")["camt"] == 450
    assert _row(avl, "ISRC")["camt"] == 0, (
        "credit on an ordinary purchase was declared under ISRC — Inward "
        "Supplies Reverse Charge — on a return the CA signs")


def test_reverse_charge_credit_is_declared_under_isrc():
    avl = _t4(_payload([_sale(90000, 90000)], [ORDINARY, REVERSE_CHARGE]))["itc_avl"]
    assert _row(avl, "ISRC")["camt"] == 90
    assert _row(avl, "OTH")["camt"] == 450, (
        "the reverse-charge credit was counted in both rows, or in neither")


def test_the_five_rows_sum_to_table_4c_plus_4b():
    """4(C) = 4(A) - 4(B) is an identity on the FACE of the return. If the five
    4(A) rows do not add up to it, the portal's own arithmetic disagrees with
    the file, whatever the individual figures are."""
    p = _payload([_sale(90000, 90000)], [ORDINARY, REVERSE_CHARGE],
                 [ITCReversal(cgst_paise=2000, sgst_paise=2000, reclaimable=False,
                              reason="bill cancelled")])
    t4 = _t4(p)
    for head in ("iamt", "camt", "samt", "csamt"):
        avl = sum(r[head] for r in t4["itc_avl"])
        rev = sum(r[head] for r in t4["itc_rev"])
        assert avl - rev == t4["itc_net"][head], head


@pytest.mark.parametrize("interstate", [False, True])
def test_the_rule_36_4_cap_cannot_break_that_identity(interstate):
    """If the cap trims credit below the reverse-charge tax, ISRC is capped so
    the rows still sum. Otherwise 4(A) would exceed the credit that exists."""
    from domain.gst.gstr3b_computer import GSTR2ARecord
    # Both directions: an inter-state reverse charge lands on IGST, an
    # intra-state one splits CGST/SGST. Each head caps independently, so a cap
    # applied to only some of them would pass a single-direction test.
    if interstate:
        purchase = PurchaseTransaction(1_00000, 0, 0, 18000, 0, True)
        two_a = GSTR2ARecord(cgst_paise=0, sgst_paise=0, igst_paise=2000)
    else:
        purchase = REVERSE_CHARGE
        two_a = GSTR2ARecord(cgst_paise=1000, sgst_paise=1000, igst_paise=0)
    r = compute_gstr3b([_sale(90000, 90000)], [purchase], [two_a], [])
    assert r.itc_capped_by_2a is True, "the fixture did not trigger the cap"
    t4 = r.as_gstn_payload(GSTIN, PERIOD)["itc_elg"]
    for head in ("iamt", "camt", "samt", "csamt"):
        assert sum(x[head] for x in t4["itc_avl"]) - \
               sum(x[head] for x in t4["itc_rev"]) == t4["itc_net"][head], head
    assert all(x[head] >= 0 for x in t4["itc_avl"]
               for head in ("iamt", "camt", "samt", "csamt"))


# ── Table 4(B) and 4(D) ──────────────────────────────────────────────────────

def test_itc_rev_is_rul_then_oth():
    """VBA rows 37 and 38: 4(B)(1) then 4(B)(2)."""
    assert [r["ty"] for r in _t4(_payload())["itc_rev"]] == ["RUL", "OTH"]


def test_itc_inelg_has_both_rows_and_rul_is_the_reclaim_row():
    """VBA rows 41 and 42. "RUL" here is 4(D)(1) — credit reclaimed after an
    earlier 4(B)(2) reversal — NOT a rule-based reversal. Same code, different
    table, different meaning."""
    inelg = _t4(_payload())["itc_inelg"]
    assert [r["ty"] for r in inelg] == ["RUL", "OTH"]
    assert all(r[h] == 0 for r in inelg for h in ("iamt", "camt", "samt", "csamt"))


# ── section 5: inward supplies ───────────────────────────────────────────────

def test_inward_sup_is_the_exempt_and_non_gst_block_not_reverse_charge():
    rows = _payload([], [REVERSE_CHARGE])["inward_sup"]["isup_details"]
    assert [r["ty"] for r in rows] == ["GST", "NONGST"]
    for r in rows:
        assert set(r) == {"ty", "inter", "intra"}, (
            f"invented field names in inward_sup: {sorted(set(r))}")


def test_the_reverse_charge_liability_is_in_table_3_1_d_where_it_belongs():
    """Removing it from inward_sup must not lose it. Table 3.1(d) is isup_rev."""
    p = _payload([_sale(90000, 90000)], [REVERSE_CHARGE])
    assert p["sup_details"]["isup_rev"]["camt"] == 90
    assert p["sup_details"]["isup_rev"]["samt"] == 90
    assert p["inward_sup"]["isup_details"][0]["inter"] == 0


# ── Table 3.1.1, section 9(5) ────────────────────────────────────────────────

def test_eco_dtls_is_emitted_for_periods_from_july_2022():
    eco = _payload(period="072022")["eco_dtls"]
    assert set(eco) == {"eco_sup", "eco_reg_sup"}
    for block in eco.values():
        assert set(block) == {"txval", "iamt", "camt", "samt", "csamt"}


def test_eco_dtls_is_absent_before_the_row_existed():
    assert "eco_dtls" not in _payload(period="062022")
    assert "eco_dtls" not in _payload(period="122021"), (
        "a December 2021 return must not carry a block the form did not have")


def test_a_period_that_cannot_be_parsed_keeps_the_block():
    """Dropping a whole section of a live return is the worse failure."""
    assert "eco_dtls" in _payload(period="")
    assert "eco_dtls" in _payload(period="notaperiod")


# ── the top-level shape ──────────────────────────────────────────────────────

def test_the_payload_carries_exactly_the_blocks_the_utility_writes():
    p = _payload()
    assert set(p) == {"gstin", "ret_period", "inward_sup", "sup_details",
                      "eco_dtls", "itc_elg", "intr_ltfee"}, sorted(p)
    assert set(p["sup_details"]) == {"osup_det", "osup_zero", "osup_nil_exmp",
                                     "isup_rev", "osup_nongst"}
    assert set(p["itc_elg"]) == {"itc_avl", "itc_rev", "itc_net", "itc_inelg"}


def test_every_amount_in_the_payload_is_a_whole_rupee_integer():
    """CGST Act §170. A float here is a file the portal rejects on parse."""
    p = _payload([_sale(90067, 90049)], [ORDINARY, REVERSE_CHARGE])
    bad = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, bool) or (not isinstance(node, (int, str))):
            bad.append((path, type(node).__name__))

    walk(p, "payload")
    assert not bad, bad
