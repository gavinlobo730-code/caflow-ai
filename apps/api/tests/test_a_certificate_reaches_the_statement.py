"""A §197 certificate is on the quarterly statement, not only on the bill (PUR-07).

WHAT WAS WRONG

`purchase_bills.tds_certificate_no` and `purchase_payments.tds_certificate_no`
have existed since migration 359, `services/vendor_tds.py` resolves the
certificate and stamps the number, and `services/tds_register_service.py` reads
it back. `services/tds_return_service.py` — the module that builds the 26Q and
27Q payloads a CA files from — never mentioned it. A grep for "certificate" in
that module returned nothing.

So a deductee withheld at 2% under an Assessing Officer's §197(1) certificate
went onto the statement at 2% with nothing saying why, next to rows at the
section's own 10%. `TDSDeducteeRecord` has carried `is_lower_deduction` and
`lower_deduction_cert` since migration 037 and nothing ever set either.

ONE STATEMENT REPORTS IT, AND THE OTHER TWO REFUSE TO — WHICH IS THE PART THE
FINDING GOT WRONG.

PUR-07's own suggested fix said to emit the pair on 26Q "and the 27Q twin".
Following that literally puts a permanently-False column on every foreign
remittance: `services/vendor_tds.resolve_withholding` DELIBERATELY does not
apply a §197 certificate to a §195 payee — §195 resolves by the nature of the
income under §115A and Part II's surcharge ladders with the DTAA under §90(2),
and a flat certified rate would be a fourth figure in a comparison the statute
already defines — so it withholds at the §195 rate, tells the CA the
certificate was not used, and leaves `tds_certificate_no` NULL. §192 is a
different reason for the same answer: it is absent from
`domain/tds/lower_deduction.SECTIONS_197`, so a certificate against it is
refused rather than applied.

A hard False on either would assert "no certificate" where the truth is "one
was refused, on purpose" and "nobody asked". Both refusals are pinned below, so
if either owner decision is ever reversed the test says to revisit this.
"""
import routers.purchase_bills as pb
import services.tds_return_service as trs
from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-C"
CALLER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth", "email": "ca@f.test",
          "role": "Partner"}
FY, Q = "2025-26", "Q1"
TAN = "MUMF12345G"
DEDUCTOR = dict(tan=TAN, deductor_name="Apex Trading Solutions",
                deductor_pan="AAACA1234B", deductor_address="Mumbai")


def _setup(monkeypatch, *, resident=True):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2",
                        "financial_year_start": "2025-04-01"})
    db.seed("vendors", {
        "id": "VEND1", "firm_id": FIRM, "client_id": "CLI", "name": "Sharma Consulting Pvt Ltd",
        "state_code": "27", "gstin": "27CCCCC2222C1Z5", "pan": "AAACS1234C",
        "tds_applicable": True, "tds_section": "194J" if resident else "195",
        "tds_rate_bps": 1000, "opening_balance_paise": 0,
        "residential_status": "resident" if resident else "non_resident",
        "country_of_residence": None if resident else "US",
        "section_195_nature_of_income": None if resident else "fees_for_technical_services",
    })
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Professional Services", "kind": "service"})
    return db


def _certificate(db, *, section, no="MUM/197/2025/00417", rate_bps=200):
    db.seed("tds_lower_deduction_certificates", {
        "id": f"CERT-{no}", "firm_id": FIRM, "client_id": "CLI", "vendor_id": "VEND1",
        "certificate_no": no, "section": section, "rate_bps": rate_bps,
        "valid_from": "2025-04-01", "valid_to": "2026-03-31",
        "ceiling_paise": 50_00_000_00,
    })


def _receive(db, no="BILL-1", rate=5_00_000_00, bill_date="2025-05-10"):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date=bill_date, bill_no=no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="consulting",
                                  rate_paise=rate, quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    assert res["success"] is True, res
    assert pb.receive_purchase_bill(res["data"]["id"], CALLER)["success"] is True
    return res["data"]


# ── 26Q ──────────────────────────────────────────────────────────────────────

def test_a_26q_row_carries_the_certificate_it_was_deducted_under(monkeypatch):
    db = _setup(monkeypatch)
    _certificate(db, section="194J")
    bill = _receive(db)
    assert bill["tds_certificate_no"], "the bill did not record the certificate"

    row = trs.tds_26q_from_books(db, FIRM, "CLI", FY, Q, **DEDUCTOR)["deductees"][0]
    assert row["is_lower_deduction"] is True
    assert row["lower_deduction_cert"] == "MUM/197/2025/00417"


def test_a_26q_row_with_no_certificate_says_so_rather_than_nothing(monkeypatch):
    db = _setup(monkeypatch)
    _receive(db)
    row = trs.tds_26q_from_books(db, FIRM, "CLI", FY, Q, **DEDUCTOR)["deductees"][0]
    # Present and false — the two keys exist on EVERY row, so a reader never has
    # to tell "not certified" from "this build does not report certificates".
    assert row["is_lower_deduction"] is False
    assert row["lower_deduction_cert"] is None


def test_the_certified_row_is_at_the_certificate_rate_and_the_pair_is_what_explains_it(monkeypatch):
    """The figures alone cannot distinguish a certificate from a short deduction.

    This is the whole finding in one assertion: without the pair, the row below
    is a 2% deduction on a §194J bill and nothing on the statement says why.
    """
    db = _setup(monkeypatch)
    _certificate(db, section="194J", rate_bps=200)
    _receive(db)
    row = trs.tds_26q_from_books(db, FIRM, "CLI", FY, Q, **DEDUCTOR)["deductees"][0]
    assert row["tds_rate_pct"] == 2.0
    assert row["lower_deduction_cert"]


# ── 27Q reports NOTHING, and that is the decision, not a gap ────────────────

def test_a_27q_row_has_no_certificate_columns_at_all(monkeypatch):
    """Not False — absent. A column that can only ever be False is a claim."""
    db = _setup(monkeypatch, resident=False)
    _certificate(db, section="195", no="MUM/197/2025/00902")
    _receive(db)

    out = trs.tds_27q_from_books(db, FIRM, "CLI", FY, Q, **DEDUCTOR)
    assert out["deductees"], "no 27Q row was built"
    row = out["deductees"][0]
    assert "is_lower_deduction" not in row
    assert "lower_deduction_cert" not in row


def test_the_195_engine_refuses_the_certificate_and_says_so(monkeypatch):
    """The premise the absence above rests on, asserted rather than assumed.

    If this ever starts APPLYING the certificate, `tds_certificate_no` stops
    being NULL on a §195 bill and the 27Q annexure has a real fact to report —
    so this failing is the signal to revisit, not a test to relax.
    """
    import services.vendor_tds as vt
    db = _setup(monkeypatch, resident=False)
    _certificate(db, section="195", no="MUM/197/2025/00902")
    bill = _receive(db)
    assert bill["tds_certificate_no"] is None, (
        "a §195 bill recorded a §197 certificate number — vendor_tds now "
        "applies one to a non-resident, so 27Q should report it")

    w = vt.resolve_withholding(
        {"id": "VEND1", "client_id": "CLI", "pan": "AAACS1234C",
         "residential_status": "non_resident", "tds_applicable": True,
         "tds_section": "195", "section_195_nature_of_income":
             "fees_for_technical_services", "country_of_residence": "US"},
        5_00_000_00, "2025-05-10", FIRM, db, client_id="CLI")
    assert w.certificate_no is None
    assert w.why and "NOT applied" in w.why, (
        "the refusal must reach the CA — a certificate silently ignored is "
        "worse than one refused out loud")


# ── the rule, not one spelling of it ────────────────────────────────────────

def test_both_deduction_event_kinds_carry_the_certificate():
    """A bill and an advance are ONE shape, and the pair must ride on both.

    §194 and §195 charge at credit or payment, whichever is EARLIER, so an
    advance is a charging event in its own right (migration 358) and carries
    `tds_certificate_no` on `purchase_payments` for exactly that reason. A fix
    applied to the bill branch alone would leave every advance uncertified.
    """
    bill = trs._as_deduction_event(
        {"id": "b", "tds_certificate_no": "MUM/197/2025/1", "bill_date": "2025-05-01"},
        kind="bill")
    adv = trs._as_deduction_event(
        {"id": "p", "tds_certificate_no": "MUM/197/2025/1", "payment_date": "2025-05-01"},
        kind="advance")
    assert bill["certificate_no"] == adv["certificate_no"] == "MUM/197/2025/1"

    # An empty string is a certificate number nobody holds, and
    # `is_lower_deduction` is exactly "a number is present" — the reading
    # services/tds_register_service.py has taken since migration 359.
    assert trs._as_deduction_event({"id": "b", "tds_certificate_no": ""}, kind="bill")[
        "certificate_no"] is None


def test_24q_deliberately_does_not_report_a_certificate(monkeypatch):
    """§192 is not in SECTIONS_197, so a hard False would assert a fact.

    Asserted on the PAYLOAD rather than on a comment: somebody adding the pair
    to the salary rows for symmetry fails here and has to read why first.
    """
    import services.tds_return_service as m
    src = open(m.__file__).read()
    start = src.index("def tds_24q_from_books(")
    body = src[start:]
    assert '"is_lower_deduction": d.is_lower_deduction' not in body, (
        "the 24Q payload now reports a §197 certificate. §192 is absent from "
        "domain/tds/lower_deduction.SECTIONS_197, so a certificate against it is "
        "refused rather than applied, and every salary row would carry a False "
        "that means 'nobody asked' rather than 'no certificate'.")


def test_exactly_one_payload_reports_the_certificate():
    """A floor in both directions.

    Zero means the fix was reverted. Two or three means somebody added it to a
    statement whose engine refuses to apply a certificate in the first place —
    the two tests above say why that is a claim rather than a column.
    """
    import services.tds_return_service as m
    src = open(m.__file__).read()
    assert src.count('"is_lower_deduction": d.is_lower_deduction') == 1, (
        "26Q is the one statement that reports a §197 certificate: §192 and "
        "§195 both have their certificates refused rather than applied.")
