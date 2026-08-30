"""The GSTR-3B filing demo — the one statutory walk-through that PAYS.

WHAT IS SPECIFIC TO GSTR-3B AND PINNED HERE
    - THE PAYMENT STAGE. GSTR-1 declares outward supplies and pays nothing;
      GSTR-3B discharges the liability (CGST Act §39 with §49), and Table 6.1
      is the screen the CA actually makes a decision on. The stage sequence
      below is asserted in full so it cannot be flattened back into a "net
      tax" figure.
    - TABLE 6 SETS OFF 4(C), NEVER 4(A). §49(4) permits payment only out of
      credit available in the electronic credit ledger, and credit reversed in
      this same return is not available. The fixture deliberately makes 4(A)
      and 4(C) differ per head, so a flow that reached for the gross figure
      fails test_table_6_sets_off_4c_and_never_4a rather than passing quietly.
    - TABLE 4's post-01-09-2022 layout (Notification 14/2022-Central Tax with
      Circular 170/02/2022-GST): 4(A) GROSS, 4(B)(1) absolute reversals,
      4(B)(2) reclaimable ones, 4(C) = 4(A) − 4(B), and §17(5) in 4(B)(1) and
      not repeated in 4(D).
    - The demo is gated on the SAME status the screen gates its button on:
      ca_approved. A submitted return already carries its real ARN.
    - Every figure is integer paise read off the saved gstr3b_returns record —
      the module computes nothing.

The framework rules (writes nothing, honest envelope, labelled realism) are
held for this module automatically by tests/test_filing_demo_framework.py,
whose scans walk the whole services/filing_demo package. Run the two together.
"""
from __future__ import annotations

import pytest

from services.filing_demo import gstr3b
from tests.e2e_harness import FakeDB

FIRM = "FIRM-A"
CLIENT = "CLI"
PERIOD = "042026"          # April 2026 → FY 2026-27
GSTIN = "27ABCDE1234F1Z5"

# ── The fixture's arithmetic, stated once ───────────────────────────────────
#
# Table 3.1(a) output tax     IGST 90,000  CGST 45,000  SGST 45,000
# Table 3.1(d) reverse charge IGST  5,000  CGST  2,500  SGST  2,500
# Table 4(A) gross credit     IGST 60,000  CGST 60,000  SGST 60,000
# Table 4(B)(1) permanent     IGST 10,000  CGST  5,000  SGST  5,000
# Table 4(B)(2) reclaimable   IGST  5,000  CGST  2,000  SGST  2,000
# Table 4(C) = 4(A) − 4(B)    IGST 45,000  CGST 53,000  SGST 53,000
# Table 6 after §49(5)        IGST 45,000  CGST      0  SGST      0
#
# 4(A) and 4(C) differ on every head, and on CGST/SGST the gross figure would
# leave a DIFFERENT cash number — which is the whole point of the fixture.
OUT_IGST, OUT_CGST, OUT_SGST = 90_000_00, 45_000_00, 45_000_00
RCM_IGST, RCM_CGST, RCM_SGST = 5_000_00, 2_500_00, 2_500_00
AVAIL_IGST, AVAIL_CGST, AVAIL_SGST = 60_000_00, 60_000_00, 60_000_00
PERM_IGST, PERM_CGST, PERM_SGST = 10_000_00, 5_000_00, 5_000_00
RECL_IGST, RECL_CGST, RECL_SGST = 5_000_00, 2_000_00, 2_000_00
NET_IGST, NET_CGST, NET_SGST = 45_000_00, 53_000_00, 53_000_00      # 4(C)
CASH_IGST, CASH_CGST, CASH_SGST = 45_000_00, 0, 0                   # Table 6

TAXABLE_VALUE = 10_00_000_00
ZERO_RATED = 2_00_000_00
NIL_EXEMPT = 50_000_00

LIABILITY = (OUT_IGST + OUT_CGST + OUT_SGST) + (RCM_IGST + RCM_CGST + RCM_SGST)
ITC_CLAIMED = NET_IGST + NET_CGST + NET_SGST          # 4(C) across the heads
NET_TAX = CASH_IGST + CASH_CGST + CASH_SGST
CONSUMED = (OUT_IGST + OUT_CGST + OUT_SGST) - NET_TAX
CARRIED_FORWARD = ITC_CLAIMED - CONSUMED


def _working() -> dict:
    """summary_json exactly as gst_return_service.gstr3b_from_books saves it
    (its `working` block), integer paise throughout."""
    return {
        "outward": {"taxable_value_paise": TAXABLE_VALUE,
                    "taxable_igst_paise": OUT_IGST,
                    "taxable_cgst_paise": OUT_CGST,
                    "taxable_sgst_paise": OUT_SGST,
                    "zero_rated_paise": ZERO_RATED,
                    "nil_exempt_paise": NIL_EXEMPT},
        "rcm_inward": {"igst_paise": RCM_IGST, "cgst_paise": RCM_CGST,
                       "sgst_paise": RCM_SGST},
        "itc": {"avail_igst_paise": AVAIL_IGST, "avail_cgst_paise": AVAIL_CGST,
                "avail_sgst_paise": AVAIL_SGST,
                "net_igst_paise": NET_IGST, "net_cgst_paise": NET_CGST,
                "net_sgst_paise": NET_SGST},
        "itc_reversal": {
            "permanent_paise": {"igst_paise": PERM_IGST,
                                "cgst_paise": PERM_CGST,
                                "sgst_paise": PERM_SGST},
            "reclaimable_paise": {"igst_paise": RECL_IGST,
                                  "cgst_paise": RECL_CGST,
                                  "sgst_paise": RECL_SGST},
        },
        "net_payable": {"igst_paise": CASH_IGST, "cgst_paise": CASH_CGST,
                        "sgst_paise": CASH_SGST, "total_paise": NET_TAX},
        "itc_utilisation": {"available_paise": ITC_CLAIMED,
                            "consumed_paise": CONSUMED,
                            "carried_forward_paise": CARRIED_FORWARD},
    }


def _db(**overrides) -> FakeDB:
    db = FakeDB()
    row = {
        "id": "R3B", "firm_id": FIRM, "client_id": CLIENT,
        "period": PERIOD, "gstin": GSTIN, "status": "ca_approved",
        "tax_liability_paise": LIABILITY,
        "itc_claimed_paise": ITC_CLAIMED,
        "net_tax_paise": NET_TAX,
        "summary_json": _working(),
    }
    row.update(overrides)
    db.seed("gstr3b_returns", row)
    return db


def _build(db=None, ref=None) -> dict:
    return gstr3b.build(db or _db(), FIRM, CLIENT,
                        {"return_id": "R3B"} if ref is None else ref)


def _stage(out: dict, title_starts: str) -> dict:
    return next(s for s in out["stages"]
                if str(s.get("title") or "").startswith(title_starts))


def _cells(row: list) -> list:
    """A table row's money cells, paise or the literal dash."""
    return [c.get("paise", c.get("text")) for c in row]


# ── Rule 2: the envelope is honest ──────────────────────────────────────────

def test_envelope_is_honest():
    out = _build()
    assert out["simulated"] is True
    assert out["filed"] is False
    assert out["acknowledgement"].startswith("SIM-NOT-FILED-GSTR3B-")
    assert "nothing has been filed" in out["disclaimer"]
    assert out["flow"] == "gstr3b"
    assert out["title"] == "File GSTR-3B"
    assert out["subtitle"] == f"{GSTIN} · {PERIOD}"
    assert out["real_channel"]["software_permitted"] is False, (
        "GSTN filing needs a GSP; claiming software may file GST today would "
        "teach a CA something false")
    assert "GST Suvidha Provider" in out["real_channel"]["how"]
    assert "PMT-06" in out["real_channel"]["how"], (
        "the cash leg is part of the real channel, not an afterthought")


# ── The portal's sequence, payment stage included ───────────────────────────

def test_follows_the_portal_sequence_including_the_payment_stage():
    """summary → 3.1 → 4 → 5.1 → 6.1 → freeze warning → declaration →
    signature → otp → transmit → result.

    The four tables are the form's own order, and the fourth of them is the
    payment step. GSTR-1's flow has no equivalent: it declares supplies and
    pays nothing. Losing this stage would turn the walk-through into GSTR-1
    with a different title."""
    out = _build()
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds == ["summary", "table", "table", "table", "table", "warning",
                     "declaration", "signature", "otp", "transmit", "result"]
    titles = [s["title"] for s in out["stages"] if s.get("title")]
    assert titles == [
        f"GSTR-3B · {PERIOD}",
        "Table 3.1 — Outward supplies and inward supplies liable to reverse charge",
        "Table 4 — Eligible ITC",
        "Table 5.1 — Interest and late fee",
        "Table 6.1 — Payment of tax",
    ]


def test_the_payment_stage_is_the_last_step_before_the_ceremony():
    """On the portal, PROCEED TO PAYMENT comes before PROCEED TO FILE — the
    liability is settled and only then is the return signed. A payment stage
    after the declaration would teach the sequence backwards."""
    out = _build()
    kinds = [s["kind"] for s in out["stages"]]
    payment = out["stages"].index(_stage(out, "Table 6.1"))
    assert payment < kinds.index("declaration")
    assert out["stages"][payment]["cta"] == "Proceed to file"


# ── Table 6.1: the rule that is easiest to get backwards ────────────────────

def test_table_6_sets_off_4c_and_never_4a():
    """CGST Act §49(4): payment may be made only out of credit AVAILABLE in
    the electronic credit ledger, and credit reversed in this same return is
    not available.

    The fixture reverses ₹15,000 of IGST and ₹7,000 each of CGST/SGST, so 4(A)
    and 4(C) differ on every head. Reaching for the gross figure here would
    tell the client their credit covers more than it does — the classic error,
    and the one that surfaces later as interest under §50."""
    out = _build()
    rows = {r[0]["text"]: r for r in _stage(out, "Table 6.1")["rows"]}
    credit = {head: rows[head][2]["paise"] for head in ("IGST", "CGST", "SGST")}

    assert credit == {"IGST": NET_IGST, "CGST": NET_CGST, "SGST": NET_SGST}, (
        "Table 6.1's credit column must be Table 4(C)")
    assert credit["IGST"] != AVAIL_IGST
    assert credit["CGST"] != AVAIL_CGST
    assert credit["SGST"] != AVAIL_SGST, (
        "the credit shown as paying the tax is 4(A), the GROSS figure — "
        "§49(4) does not allow credit reversed in this return to pay it")

    # And the column is labelled as 4(C), so nobody reading the screen has to
    # infer which figure it is.
    assert _stage(out, "Table 6.1")["columns"] == [
        "Head", "Liability (3.1(a))", "Credit available (4C)",
        "Paid through ITC", "Paid in cash"]


def test_the_payment_note_states_the_rule_and_cites_the_section():
    out = _build()
    note = _stage(out, "Table 6.1")["note"]
    assert "Table 4(C)" in note and "never 4(A)" in note
    assert "§49(4)" in note
    assert "§49(5)" in note, "the cross-utilisation order is part of the screen"
    assert "PMT-06" in note, "cash is paid by challan before the return can be filed"


def test_table_6_rows_are_paise_exact_and_reconcile_per_head():
    """Liability = what the credit paid + what cash paid, per head. A split
    that does not add up is worse than no split."""
    out = _build()
    rows = {r[0]["text"]: r for r in _stage(out, "Table 6.1")["rows"]}
    expected = {
        "IGST": (OUT_IGST, NET_IGST, OUT_IGST - CASH_IGST, CASH_IGST),
        "CGST": (OUT_CGST, NET_CGST, OUT_CGST - CASH_CGST, CASH_CGST),
        "SGST": (OUT_SGST, NET_SGST, OUT_SGST - CASH_SGST, CASH_SGST),
    }
    for head, (liab, credit, by_itc, cash) in expected.items():
        cells = [c["paise"] for c in rows[head][1:]]
        assert cells == [liab, credit, by_itc, cash], head
        assert cells[2] + cells[3] == cells[0], f"{head} does not add up"


def test_table_6_footer_totals_tie_to_the_saved_header_figures():
    out = _build()
    footer = _stage(out, "Table 6.1")["footer"]
    assert footer[0]["text"] == "Total"
    assert footer[1]["paise"] == OUT_IGST + OUT_CGST + OUT_SGST
    assert footer[2]["paise"] == ITC_CLAIMED, (
        "the credit column's total is the return's own ITC claimed — 4(C)")
    assert footer[3]["paise"] == CONSUMED
    assert footer[4]["paise"] == NET_TAX


def test_credit_is_never_shown_paying_more_than_the_liability():
    """max(liability − cash, 0). If Table 6 ever exceeded 3.1(a) — a bug
    elsewhere — this must not render a negative contribution from the
    ledger."""
    working = _working()
    working["outward"]["taxable_igst_paise"] = 1_000_00
    working["net_payable"]["igst_paise"] = 5_000_00
    out = _build(_db(summary_json=working))
    igst = next(r for r in _stage(out, "Table 6.1")["rows"]
                if r[0]["text"] == "IGST")
    assert igst[3]["paise"] == 0


# ── Table 4: the layout Notification 14/2022 put on the portal ──────────────

def test_table_4_reports_4a_gross_and_4c_as_the_total_line():
    """4(A) is auto-populated from GSTR-2B, so blocked credit stays in it —
    netting §17(5) out breaks the tie-up with the portal's own figure. 4(C) is
    the footer because it is what the rows above add up to."""
    out = _build()
    table = _stage(out, "Table 4")
    assert table["columns"] == ["", "IGST", "CGST", "SGST"]
    labels = [r[0]["text"] for r in table["rows"]]
    assert labels[0].startswith("4(A)") and "gross" in labels[0]
    assert labels[1].startswith("4(B)(1)")
    assert labels[2].startswith("4(B)(2)")

    assert _cells(table["rows"][0])[1:] == [AVAIL_IGST, AVAIL_CGST, AVAIL_SGST]
    assert _cells(table["rows"][1])[1:] == [PERM_IGST, PERM_CGST, PERM_SGST]
    assert _cells(table["rows"][2])[1:] == [RECL_IGST, RECL_CGST, RECL_SGST]

    assert table["footer"][0]["text"] == "4(C) Net ITC available (4A − 4B)"
    assert [c["paise"] for c in table["footer"][1:]] == [
        NET_IGST, NET_CGST, NET_SGST]


def test_table_4_rows_arithmetically_agree_with_the_circular():
    """4(C) = 4(A) − 4(B)(1) − 4(B)(2), on every head, in paise."""
    out = _build()
    table = _stage(out, "Table 4")
    gross = _cells(table["rows"][0])[1:]
    perm = _cells(table["rows"][1])[1:]
    recl = _cells(table["rows"][2])[1:]
    net = [c["paise"] for c in table["footer"][1:]]
    assert [g - p - r for g, p, r in zip(gross, perm, recl)] == net


def test_table_4_names_the_notification_the_circular_and_where_17_5_sits():
    out = _build()
    note = _stage(out, "Table 4")["note"]
    assert "Notification 14/2022-Central Tax" in note
    assert "170/02/2022-GST" in note
    assert "01-09-2022" in note
    assert "GROSS" in note and "GSTR-2B" in note
    assert "§17(5)" in note and "4(B)(1)" in note
    assert "NOT repeated in 4(D)" in note, (
        "reporting §17(5) again in 4(D) double-counts the reversal")
    labels = [r[0]["text"] for r in _stage(out, "Table 4")["rows"]]
    assert "Rules 38/42/43, §17(5)" in labels[1], (
        "4(B)(1) takes the reversals that are absolute and not reclaimable")
    assert "Rule 37/37A, §16(2)(b)/(c)" in labels[2], (
        "4(B)(2) takes the ones that come back")


# ── Table 3.1 and Table 5.1 ─────────────────────────────────────────────────

def test_table_31_carries_the_four_lines_the_working_supports():
    out = _build()
    table = _stage(out, "Table 3.1")
    assert table["columns"] == ["", "Taxable value", "IGST", "CGST", "SGST"]
    rows = table["rows"]
    assert [r[0]["text"][:3] for r in rows] == ["(a)", "(b)", "(c)", "(d)"]
    assert _cells(rows[0]) == [rows[0][0]["text"], TAXABLE_VALUE,
                               OUT_IGST, OUT_CGST, OUT_SGST]
    assert _cells(rows[1])[1:] == [ZERO_RATED, "—", "—", "—"], (
        "a zero-rated supply bears no output tax; a nil would read as a figure")
    assert _cells(rows[2])[1:] == [NIL_EXEMPT, "—", "—", "—"]
    assert _cells(rows[3])[1:] == ["—", RCM_IGST, RCM_CGST, RCM_SGST]
    assert "§9(3)/(4)" in table["note"] and "§49(4)" in table["note"], (
        "3.1(d) is self-assessed by the recipient and paid in cash")


def test_table_51_is_nil_and_says_why_rather_than_inventing_a_figure():
    """PracticeSync computes neither §50 interest nor §47 late fee. Showing a
    number it did not compute would be worse than showing the nil."""
    out = _build()
    table = _stage(out, "Table 5.1")
    labels = [r[0]["text"] for r in table["rows"]]
    assert labels == ["Interest (CGST Act §50)", "Late fee (CGST Act §47)"]
    assert [r[1]["paise"] for r in table["rows"]] == [0, 0]
    note = table["note"]
    assert "does not compute" in note
    assert "payable in CASH" in note and "§49(4)" in note, (
        "the credit ledger may pay output tax only — never interest or fee")
    assert "2026-05-20" in note, (
        "late fee runs from the due date, which comes from "
        "compliance_engine.gstr3b_due_date and is never restated here")


# ── The figures are the record's own ────────────────────────────────────────

def test_summary_figures_are_the_saved_returns_own_paise():
    out = _build()
    figures = {f["label"]: f for f in out["stages"][0]["figures"]}
    assert figures["Tax liability (Table 3.1)"]["paise"] == LIABILITY
    assert figures["ITC claimed (Table 4(C))"]["paise"] == ITC_CLAIMED
    assert figures["Net tax payable in cash (Table 6)"]["paise"] == NET_TAX
    assert figures["Credit carried forward"]["paise"] == CARRIED_FORWARD
    assert all(isinstance(f.get("paise"), int)
               for f in out["stages"][0]["figures"] if "paise" in f), (
        "money crosses the API as integer paise, never a float")


def test_the_due_date_comes_from_the_compliance_engine():
    """CGST Act §39 — the 20th of the following month for a monthly filer.
    services/compliance_engine.py::gstr3b_due_date is the single authority and
    the demo never restates a date of its own."""
    from services.compliance_engine import gstr3b_due_date
    out = _build()
    figures = {f["label"]: f for f in out["stages"][0]["figures"]}
    assert (figures["Due date (CGST Act §39)"]["text"]
            == gstr3b_due_date(2026, 4).isoformat() == "2026-05-20")


def test_the_freeze_warning_names_the_correction_route_and_its_early_close():
    """CGST §39(9) is the route, and §37(3)/§39(9)/§16(4) close it at 30
    November following the FY OR the date GSTR-9 is furnished, whichever is
    EARLIER — compliance_engine.correction_window_closes, never the outer
    limit on its own."""
    out = _build()
    warning = next(s for s in out["stages"] if s["kind"] == "warning")
    assert "cannot be revised" in warning["text"]
    assert "§39(9)" in warning["text"]
    assert "2027-11-30" in warning["text"], (
        "April 2026 falls in FY 2026-27, which ends 31 Mar 2027")
    assert "whichever is EARLIER" in warning["text"]


def test_a_return_saved_without_its_working_still_walks_through():
    """A return created by hand from + New GSTR-3B has no summary_json. The
    demo must open, show nil tables, and SAY that is what it is doing."""
    out = _build(_db(summary_json=None, tax_liability_paise=0,
                     itc_claimed_paise=0, net_tax_paise=0))
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds[0] == "summary" and kinds[-1] == "result"
    assert kinds.count("table") == 4, "the payment stage survives an empty working"
    assert "nothing is invented" in out["stages"][0]["note"]
    footer = _stage(out, "Table 6.1")["footer"]
    assert [c.get("paise") for c in footer[1:]] == [0, 0, 0, 0]


# ── Declaration, signature, and the specimen ────────────────────────────────

def test_the_declaration_is_the_forms_own_wording():
    """FORM GSTR-3B's verification, verbatim. Paraphrasing a statutory
    declaration misrepresents what the signatory affirms."""
    out = _build()
    decl = next(s for s in out["stages"] if s["kind"] == "declaration")
    assert decl["text"] == (
        "I/We hereby solemnly affirm and declare that the information given "
        "herein above is true and correct to the best of my/our knowledge and "
        "belief and nothing has been concealed therefrom.")
    assert decl["signatory_label"] == "Authorised signatory"
    assert decl["signatory_options"] == [
        "Authorised signatory on the GST registration"]
    assert "taxpayer's signatory, not the firm's" in decl["note"], (
        "whose signature this is — the one thing every demo must teach")


def test_signature_methods_evc_takes_otp_dsc_does_not():
    out = _build()
    methods = {m["key"]: m for s in out["stages"] if s["kind"] == "signature"
               for m in s["methods"]}
    assert methods["evc"]["otp"] is True
    assert "registered mobile" in methods["evc"]["note"]
    assert methods["dsc"]["otp"] is False
    assert "emSigner" in methods["dsc"]["note"]
    assert [s["kind"] for s in out["stages"]].count("otp") == 1, (
        "one otp stage for the EVC route; the wizard skips it for DSC")


def test_the_transmit_steps_describe_a_filing_without_claiming_one():
    out = _build()
    transmit = next(s for s in out["stages"] if s["kind"] == "transmit")
    assert [s["key"] for s in transmit["steps"]] == [
        "validate", "authenticate", "upload", "process", "acknowledge"]
    joined = " ".join(s["label"] for s in transmit["steps"]).lower()
    assert "gstn" in joined or "gst portal" in joined


def test_the_result_specimen_never_travels_without_its_note():
    out = _build()
    result = next(s for s in out["stages"] if s["kind"] == "result")
    assert result["authority"] == "GSTN"
    assert result["reference_label"] == "Acknowledgement Reference Number (ARN)"
    specimen = result["specimen"]
    assert len(specimen) == 15, specimen
    assert specimen.startswith("AA27"), "two letters then the GSTIN's state code"
    assert specimen[4:8] == "0426", "MMYY of the period"
    assert specimen[8:14].isdigit() and specimen[14].isalpha()
    assert "SPECIMEN" in result["specimen_note"]
    assert "not issued" in result["specimen_note"]
    assert any("Nothing was filed" in t for t in result["truth"])
    assert any("no ledger moved" in t for t in result["truth"]), (
        "a return that pays must say no money moved either")
    assert any("PMT-06" in t for t in result["truth"]), (
        "filing for real starts with paying the cash balance")


def test_the_specimen_is_deterministic_and_period_sensitive():
    """Two runs of the same demo must show the same reference; two periods
    must not, or anyone comparing screenshots reads it as a bug."""
    assert _build()["stages"][-1]["specimen"] == _build()["stages"][-1]["specimen"]
    other = _build(_db(period="052026"))["stages"][-1]["specimen"]
    assert other != _build()["stages"][-1]["specimen"]
    assert other[4:8] == "0526"


# ── Refusals: answers, not incidents ────────────────────────────────────────

def test_a_missing_ref_is_an_answer():
    with pytest.raises(ValueError, match="return_id"):
        _build(ref={})


def test_an_unknown_return_is_an_answer():
    with pytest.raises(ValueError, match="not found"):
        _build(ref={"return_id": "NOPE"})


def test_a_wrong_firm_or_client_sees_nothing():
    db = _db()
    with pytest.raises(ValueError, match="not found"):
        gstr3b.build(db, "FIRM-B", CLIENT, {"return_id": "R3B"})
    with pytest.raises(ValueError, match="not found"):
        gstr3b.build(db, FIRM, "OTHER-CLIENT", {"return_id": "R3B"})


@pytest.mark.parametrize("status", ["draft", "validated", ""])
def test_an_unapproved_return_is_refused_in_words_a_ca_understands(status):
    """The same gate the screen puts on its button: filing starts from a
    CA-approved return, and the demo starts where filing does."""
    with pytest.raises(ValueError, match="starts where filing does"):
        _build(_db(status=status))


def test_an_already_filed_return_is_refused():
    """A submitted return carries its real ARN and the filing record the
    period lock reads. Ending a walk-through for it on a specimen ARN would
    put two references against one return."""
    with pytest.raises(ValueError, match="already recorded as filed"):
        _build(_db(status="submitted"))


# ── The flow is registered, and gated like the GST module ───────────────────

def test_the_flow_is_registered_under_gst():
    import services.filing_demo as fd
    builder, resource = fd.FLOWS["gstr3b"]
    assert builder is gstr3b.build
    assert resource == "gst", (
        "the demo shows the client's real GST figures, so it gates like the "
        "GST module")


def test_the_setoff_note_states_the_rule_that_actually_governs():
    """Rule 88A, not a sequential §49(5) order.

    The note sits directly above the numbers it describes, so it is the one
    sentence in this flow a CA is most likely to take as law. Two things were
    wrong with the earlier wording, and each is pinned here.

    First the law: §49(5)(a) fixes only that IGST credit goes against IGST
    first. Rule 88A (Notification 16/2019-Central Tax under §49B, w.e.f.
    29-03-2019) then allows the balance against CGST and SGST in any order and
    any proportion — which is exactly why the portal asks the taxpayer for a
    set-off preference. "Then CGST, then SGST" was the pre-2019 rule.

    Second the honesty: the figures beside the note come from the saved
    working, and domain/gst/gstr3b_computer.py splits excess IGST credit
    FIFTY-FIFTY between CGST and SGST (`half_excess = excess_igst_itc // 2`),
    which is a permissible split under Rule 88A but not the only one and not a
    sequential one. The note must therefore not describe the split as a rule
    it re-derives.
    """
    note = _stage(_build(), "Table 6.1")["note"]

    assert "Rule 88A" in note
    assert "any order" in note.lower() and "any proportion" in note.lower()
    assert "then CGST, then SGST" not in note, (
        "the strict sequential order was superseded by Rule 88A in 2019; "
        "stating it teaches a CA a rule neither the portal nor this engine "
        "applies"
    )
    assert "gstr3b_computer" in note, (
        "the note must attribute the split to the saved working rather than "
        "present it as derived law"
    )


def test_the_engine_really_does_split_excess_igst_credit_in_half():
    """The negative control for the test above, pointed at the engine itself.

    If gstr3b_computer ever switches to a sequential set-off, the note's
    attribution stops being merely cautious and starts being wrong in the
    other direction — so pin the behaviour the note is written against, at
    the source, rather than trusting a comment to stay true.
    """
    import inspect
    from domain.gst import gstr3b_computer
    src = inspect.getsource(gstr3b_computer)
    assert "half_excess = excess_igst_itc // 2" in src, (
        "the engine no longer halves excess IGST credit — revisit the Table "
        "6.1 note in services/filing_demo/gstr3b.py, which is written against "
        "this behaviour"
    )
