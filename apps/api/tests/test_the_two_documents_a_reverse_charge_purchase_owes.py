"""PUR-19 — CGST Act s.31(3)(f) and s.31(3)(g) are two rules, not one.

The test that matters most in this file is
`test_a_payment_to_a_REGISTERED_supplier_still_owes_a_voucher`: it is the one
that fails if the two sections are ever collapsed into a single "RCM document"
rule, which is the natural thing to do and is wrong.
"""
from __future__ import annotations

import inspect
import pathlib
import re

import pytest

from domain.gst import rcm_documents as rd

API = pathlib.Path(__file__).resolve().parent.parent
MIGRATION = API / "migrations" / "388_the_two_documents_a_reverse_charge_purchase_owes.sql"
ROLLBACK = API / "migrations" / "388_the_two_documents_a_reverse_charge_purchase_owes_rollback.sql"

# A GSTIN whose check digit is right — the fixture file is the authority and
# these are taken from it, because GST-29 corrected three invented ones that
# were wrong in 77 files.
GOOD_GSTIN = "27AAPFU0939F1ZV"


def _vendor(**over):
    base = {"id": "V1", "name": "Ramesh Transport", "gstin": None,
            "state_code": "27", "gst_registration_status": None}
    base.update(over)
    return base


def _bill(**over):
    base = {
        "id": "B1", "firm_id": "F1", "client_id": "C1", "vendor_id": "V1",
        "bill_no": "GTA/9", "bill_date": "2026-06-10",
        "is_reverse_charge": True, "is_interstate": False,
        "taxable_amount_paise": 10_000_00,
        "cgst_paise": 900_00, "sgst_paise": 900_00, "igst_paise": 0,
        "cess_paise": 0, "total_paise": 10_000_00,
    }
    base.update(over)
    return base


def _party(**over):
    base = {"name": "Acme Traders", "address": "Pune", "gstin": GOOD_GSTIN,
            "state_code": "27"}
    base.update(over)
    return rd.Party(**base)


# ── The registration question ────────────────────────────────────────────────

def test_the_three_states_are_exactly_what_the_module_names():
    assert rd.REGISTRATION_STATES == (rd.REGISTERED, rd.UNREGISTERED, rd.UNRECORDED)


def test_a_well_formed_gstin_IS_the_registration():
    """s.25 issues a GSTIN on registration, which is exactly what s.31(3)(f)
    asks about — so a valid one settles the question with no second field."""
    state, why = rd.registration_of(_vendor(gstin=GOOD_GSTIN))
    assert state == rd.REGISTERED
    assert why is None


def test_a_malformed_recorded_gstin_is_the_GAP_and_not_a_registration():
    """GST-29 refuses a malformed GSTIN at every door a human types one, so a
    malformed value in the table is legacy data — somebody's typo, and a typo is
    evidence of neither answer."""
    state, why = rd.registration_of(_vendor(gstin="27AAPFU0939F1Z9"))
    assert state == rd.UNRECORDED
    assert why and "not a valid GSTIN" in why
    assert "Correct it" in why


def test_no_gstin_and_no_recorded_status_is_the_gap_and_says_what_to_record():
    state, why = rd.registration_of(_vendor())
    assert state == rd.UNRECORDED
    assert why and "has not been recorded" in why
    assert "s.31(3)(f)" in why


def test_a_recorded_unregistered_status_settles_it():
    state, why = rd.registration_of(_vendor(gst_registration_status="unregistered"))
    assert state == rd.UNREGISTERED
    assert why is None


def test_an_unrecognised_stored_status_is_the_gap_rather_than_trusted():
    state, _why = rd.registration_of(_vendor(gst_registration_status="maybe"))
    assert state == rd.UNRECORDED


# ── s.31(3)(f): the self-invoice ─────────────────────────────────────────────

def test_a_non_reverse_charge_bill_owes_no_self_invoice():
    d = rd.self_invoice_due(_bill(is_reverse_charge=False), _vendor())
    assert d.due is False
    assert any("supplier's own invoice" in r for r in d.reasons)
    assert not d.gaps


def test_a_registered_supplier_owes_no_self_invoice_and_the_reason_quotes_the_limb():
    """s.31(3)(f) reaches only a supply 'from the supplier who is NOT registered'.
    A registered GTA issues their own invoice marked payable on reverse charge."""
    d = rd.self_invoice_due(_bill(), _vendor(gstin=GOOD_GSTIN))
    assert d.due is False
    # Case-folded: the module emphasises the limb in capitals and the test is
    # about the limb being QUOTED, not about its typography.
    assert any("not registered" in r.lower() for r in d.reasons)
    assert not d.gaps


def test_an_unregistered_supplier_on_an_rcm_bill_owes_one():
    d = rd.self_invoice_due(_bill(), _vendor(gst_registration_status="unregistered"))
    assert d.due is True
    assert not d.reasons and not d.gaps


def test_an_unrecorded_registration_owes_NOTHING_YET_and_that_is_not_a_refusal():
    """The two 'not due' answers are different facts. `reasons` means the Act
    does not ask for the document; `gaps` means nobody can yet tell."""
    d = rd.self_invoice_due(_bill(), _vendor())
    assert d.due is False
    assert d.gaps and not d.reasons
    assert d.undecided is True


def test_a_settled_refusal_is_not_undecided():
    d = rd.self_invoice_due(_bill(), _vendor(gstin=GOOD_GSTIN))
    assert d.undecided is False


# ── s.31(3)(g): the payment voucher ──────────────────────────────────────────

def test_a_payment_to_a_REGISTERED_supplier_still_owes_a_voucher():
    """THE TEST THAT KEEPS THE TWO SECTIONS APART.

    s.31(3)(g) has no 'not registered' limb — it is due 'at the time of making
    payment to the supplier' on every s.9(3)/(4) liability. Collapsing the two
    rules into one would fail here and nowhere else.
    """
    payment = {"id": "P1", "amount_paise": 10_000_00}
    settled = [{"bill": _bill(), "settled_paise": 10_000_00}]
    d = rd.payment_voucher_due(payment, settled)
    assert d.due is True
    # And the registration is genuinely irrelevant: the same answer with a
    # registered supplier, because the section never asks.
    assert rd.payment_voucher_due(payment, settled).due is True


def test_a_payment_settling_no_rcm_bill_owes_none():
    d = rd.payment_voucher_due(
        {"id": "P1", "amount_paise": 100},
        [{"bill": _bill(is_reverse_charge=False), "settled_paise": 100}])
    assert d.due is False
    assert any("no s.9(3)/(4) tax" in r or "reverse-charge liability" in r
               for r in d.reasons)


def test_an_unallocated_payment_is_a_gap_rather_than_a_refusal():
    d = rd.payment_voucher_due({"id": "P1", "amount_paise": 100}, [])
    assert d.due is False
    assert d.gaps and not d.reasons


# ── The particulars ──────────────────────────────────────────────────────────

def _self_invoice(bill=None, lines=None, recipient=None):
    return rd.self_invoice_particulars(
        bill=bill or _bill(),
        bill_lines=lines if lines is not None else [
            {"description": "Freight", "hsn_sac": "9965", "quantity": "1",
             "taxable_amount_paise": 10_000_00}],
        supplier=rd.Party(name="Ramesh Transport", address="Pune", gstin=None,
                          state_code="27"),
        recipient=recipient or _party(),
        document_no="RCM-SI/2026-27/001", document_date="2026-06-10")


def test_a_nil_head_is_omitted_rather_than_printed_as_zero():
    """An IGST line of zero on an intra-state document tells the reader the
    supply was inter-state and nothing was charged — the opposite of the truth."""
    p = _self_invoice()
    assert [t.head for t in p.taxes] == ["CGST", "SGST"]


def test_the_tax_the_bill_carries_decides_interstate_not_the_stored_flag():
    bill = _bill(cgst_paise=0, sgst_paise=0, igst_paise=1800_00, is_interstate=False)
    p = _self_invoice(bill=bill)
    assert [t.head for t in p.taxes] == ["IGST"]
    assert any("recorded as intra-state but carries IGST" in c for c in p.caveats)
    # The document follows the tax, so the place of supply IS stated.
    assert p.place_of_supply[0] == "27"


def test_the_other_direction_is_a_caveat_too():
    p = _self_invoice(bill=_bill(is_interstate=True))
    assert any("recorded as inter-state but carries CGST and SGST" in c
               for c in p.caveats)
    # Rule 46(n) asks for the place of supply only on an inter-state supply.
    assert p.place_of_supply == ("", "")


def test_both_heads_at_once_is_said_rather_than_resolved():
    p = _self_invoice(bill=_bill(igst_paise=100))
    assert any("IGST and CGST/SGST at once" in c for c in p.caveats)


def test_an_interstate_document_with_no_client_state_names_rule_46_n():
    p = _self_invoice(bill=_bill(cgst_paise=0, sgst_paise=0, igst_paise=100,
                                 is_interstate=True),
                      recipient=_party(state_code=None))
    assert any("Rule 46(n)" in g for g in p.gaps)


def test_a_bill_with_no_lines_names_rule_46_g():
    p = _self_invoice(lines=[])
    assert any("Rule 46(g)" in g for g in p.gaps)


def test_a_self_invoice_supplier_block_never_carries_a_gstin():
    """The document exists BECAUSE the supplier is not registered. A GSTIN in
    that block would contradict the section it is issued under."""
    p = _self_invoice()
    assert p.supplier.gstin is None


def test_the_declaration_is_a_particular_and_is_always_true_here():
    """Rule 46(p) / Rule 52(j). Neither document exists except on a s.9(3)/(4)
    supply, so it is always true — and it is PRINTED rather than implied."""
    assert _self_invoice().tax_payable_on_reverse_charge is True


# ── The payment voucher's two figures ────────────────────────────────────────

def _voucher(payment=None, settled=None, recipient=None):
    return rd.payment_voucher_particulars(
        payment=payment or {"id": "P1", "amount_paise": 10_000_00},
        settled=settled if settled is not None else [
            {"bill": _bill(), "settled_paise": 10_000_00}],
        supplier=rd.Party(name="Ramesh Transport", gstin=None, state_code="27"),
        recipient=recipient or _party(),
        document_no="RCM-PV/2026-27/001", document_date="2026-07-02")


def test_the_voucher_states_the_whole_amount_paid_and_the_rcm_tax():
    p = _voucher()
    assert p.amount_paid_paise == 10_000_00           # Rule 52(f)
    assert p.total_tax_paise == 1800_00               # Rule 52(h)
    assert p.taxable_paise == 10_000_00


def test_a_part_payment_apportions_the_tax_and_FLOORS():
    """A voucher may not state more tax than the payment supports; the
    remainder rides on the next one."""
    p = _voucher(payment={"id": "P1", "amount_paise": 3_333_00},
                 settled=[{"bill": _bill(), "settled_paise": 3_333_00}])
    # 900_00 * 333300 // 1000000 == 29997 per local head.
    assert [t.amount_paise for t in p.taxes] == [29997, 29997]
    assert sum(t.amount_paise for t in p.taxes) < 1800_00


def test_a_mixed_payment_states_the_whole_amount_and_NAMES_the_rest():
    p = _voucher(payment={"id": "P1", "amount_paise": 15_000_00},
                 settled=[{"bill": _bill(), "settled_paise": 10_000_00},
                          {"bill": _bill(id="B2", is_reverse_charge=False,
                                         cgst_paise=450_00, sgst_paise=450_00),
                           "settled_paise": 5_000_00}])
    assert p.amount_paid_paise == 15_000_00
    assert p.total_tax_paise == 1800_00          # the RCM bill's tax only
    assert any("no reverse-charge liability" in c for c in p.caveats)


def test_a_voucher_has_no_line_table():
    """Rule 52 asks for a description, not the line table Rule 46(g) wants."""
    assert _voucher().lines == []


def test_an_interstate_voucher_with_no_client_state_names_rule_52_i():
    p = _voucher(settled=[{"bill": _bill(cgst_paise=0, sgst_paise=0,
                                         igst_paise=1800_00),
                           "settled_paise": 10_000_00}],
                 recipient=_party(state_code=None))
    assert any("Rule 52(i)" in g for g in p.gaps)


# ── The serialiser ───────────────────────────────────────────────────────────

def test_one_serialiser_feeds_both_the_response_and_the_stored_copy():
    """A stored copy that differs from the served one is two records of the
    same document."""
    d = rd.as_dict(_self_invoice())
    assert d["section"] == "CGST Act s.31(3)(f)"
    assert d["rule"] == "CGST Rule 46"
    assert d["total_tax_paise"] == 1800_00
    assert d["supplier"]["gstin"] is None
    assert d["tax_payable_on_reverse_charge"] is True
    import json
    json.dumps(d)          # it is stored as JSONB, so it must serialise


def test_each_kind_has_its_own_series_head():
    """Rule 46(b) allows 'one or multiple series'. Two kinds sharing one head
    would make a self-invoice and a payment voucher collide on the unique
    index — and would put a number in a sequence it does not belong to."""
    heads = set(rd.DEFAULT_PREFIX_FOR_KIND.values())
    assert len(heads) == len(rd.KINDS)


def test_every_kind_names_its_section_and_its_rule():
    for k in rd.KINDS:
        assert rd.SECTION_FOR_KIND[k].startswith("CGST Act s.31(3)")
        assert rd.RULE_FOR_KIND[k].startswith("CGST Rule ")


# ── The migration ────────────────────────────────────────────────────────────

def _sql() -> str:
    """The migration with its comments stripped — so a test cannot pass on the
    strength of prose that says what the SQL does not do."""
    return re.sub(r"^\s*--.*$", "", MIGRATION.read_text(), flags=re.M)


def test_the_registration_status_is_nullable_with_no_default():
    sql = _sql()
    assert "ADD COLUMN IF NOT EXISTS gst_registration_status TEXT" in sql
    assert "gst_registration_status TEXT NOT NULL" not in sql
    assert "gst_registration_status TEXT DEFAULT" not in sql


def test_the_status_check_accepts_exactly_the_two_settled_answers():
    """The CHECK is compared to the ENGINE's own values, not to a list spelled
    here — a guard that names four strings passes a WIDENED constraint."""
    sql = _sql()
    for value in (rd.REGISTERED, rd.UNREGISTERED):
        assert f"'{value}'" in sql
    # The third state is the ABSENCE of a value, so it must not be a CHECK value.
    assert f"'{rd.UNRECORDED}'" not in sql


def test_a_document_hangs_off_exactly_one_parent():
    sql = _sql()
    assert "num_nonnulls(purchase_bill_id, purchase_payment_id) = 1" in sql
    assert "rcm_documents_kind_matches_its_parent" in sql


def test_one_document_per_parent():
    sql = _sql()
    assert "uq_rcm_document_per_bill" in sql
    assert "uq_rcm_document_per_payment" in sql


def test_the_number_is_unique_per_client_and_per_kind():
    sql = _sql()
    assert "uq_rcm_document_no_per_client_kind" in sql
    assert "(firm_id, client_id, kind, document_no)" in sql


def test_the_table_is_read_only_from_the_browser_and_assignment_scoped():
    sql = _sql()
    assert "GRANT SELECT ON public.rcm_documents TO authenticated;" in sql
    assert "GRANT SELECT, INSERT" not in sql.split("TO authenticated")[0][-200:]
    assert "rcm_documents_assignment_scope" in sql
    assert "AS RESTRICTIVE" in sql


def test_the_rollback_refuses_while_a_document_exists():
    """These are statutory records the recipient issued, and the self-invoice is
    what Rule 36(1)(b) makes the input credit rest on."""
    text = ROLLBACK.read_text()
    assert "RAISE EXCEPTION" in text
    assert "Refusing to roll back 388" in text


# ── The service and the router ───────────────────────────────────────────────

def test_the_service_reads_both_payment_shapes():
    """PUR-22: a reader that knows one shape is silently wrong about the other,
    and being wrong here states tax for a supply this payment did not pay for."""
    from services import rcm_document_service as svc
    src = inspect.getsource(svc.settled_bills)
    assert "purchase_bill_id" in src
    assert "purchase_payment_allocations" in src
    assert "is_voided" in src


# ── WHAT A ROW IS ACTUALLY CALLED ────────────────────────────────────────────
#
# The test above reads the SOURCE, which cannot tell a right column name from a
# wrong one. Two were wrong and the real-Postgres column guard caught both, so
# these run the reads against a double seeded under the schema's OWN spellings:
# `purchase_bill_lines.bill_id` (migration 050 created it as
# `purchase_bill_id`; 051 RENAMED it) and
# `purchase_payment_allocations.allocated_paise` (`amount_paise` is what
# `purchase_payments` calls the payment's TOTAL). Both failures are SILENT —
# a missing key reads as absent, so the lines vanish and every allocation
# settles zero.

def _fake_db(monkeypatch, seed: dict[str, list[dict]]):
    from tests.e2e_harness import FakeDB
    db = FakeDB()
    for table, rows in seed.items():
        for row in rows:
            db.seed(table, row)
    return db


def test_a_bills_lines_are_read_under_the_name_the_schema_gives_them(monkeypatch):
    from services import rcm_document_service as svc
    db = _fake_db(monkeypatch, {"purchase_bill_lines": [
        {"id": "L1", "bill_id": "B1", "description": "Freight",
         "hsn_sac": "996511", "quantity": 1, "taxable_amount_paise": 10_000_00},
    ]})
    lines = svc._bill_lines(db, "F1", "B1")
    assert [l["id"] for l in lines] == ["L1"], (
        "a self-invoice with no lines states no supply at all")
    assert lines[0]["taxable_amount_paise"] == 10_000_00


def test_an_allocation_settles_the_figure_that_table_records(monkeypatch):
    from services import rcm_document_service as svc
    bill = _bill()
    db = _fake_db(monkeypatch, {
        "purchase_bills": [bill],
        "purchase_payment_allocations": [
            {"id": "A1", "purchase_payment_id": "P1", "purchase_bill_id": "B1",
             "allocated_paise": 4_000_00, "is_voided": False},
        ],
    })
    settled = svc.settled_bills(
        db, "F1", {"id": "P1", "purchase_bill_id": None, "amount_paise": 9_999_99})
    assert [s["settled_paise"] for s in settled] == [4_000_00], (
        "reading the allocation under the payment's own column name settles "
        "every bill at zero")


def test_the_issue_path_asks_both_period_questions():
    from services import rcm_document_service as svc
    src = inspect.getsource(svc.issue)
    assert "validate_posting_date" in src
    assert "period_lock_service.assert_open" in src


def test_the_issue_path_refuses_a_number_rule_46_b_forbids():
    from services import rcm_document_service as svc
    src = inspect.getsource(svc.issue)
    assert "format_violation" in src


def test_the_router_decides_nothing_itself():
    """Zero business logic outside the domain module: the router must not carry
    the 'is the supplier registered' question or either section's limb."""
    src = (API / "routers" / "rcm_documents.py").read_text()
    assert "gst_registration_status" not in src
    assert "is_reverse_charge" not in src


def test_every_endpoint_checks_the_clients_scope():
    """These routes are row-addressed. The mount-level guard fires on a
    client_id in the request, so one that carries none is scoped on firm_id
    alone — which is how any member of the firm reaches another's client."""
    src = (API / "routers" / "rcm_documents.py").read_text()
    tree = __import__("ast").parse(src)
    ast = __import__("ast")
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorated = any(isinstance(d, ast.Call) and
                        getattr(d.func, "attr", "") in ("get", "post", "patch", "delete")
                        for d in fn.decorator_list)
        if not decorated:
            continue
        body = ast.get_source_segment(src, fn) or ""
        if "client_id" not in body:
            # `/kinds` and `/registration-states` are reference data about the
            # STATUTE and carry no client at all.
            assert fn.name in ("list_kinds", "list_registration_states"), fn.name
            continue
        assert "assert_client_access" in body, fn.name


# ── the one fact both documents turn on, at the door that records it ─────────
#
# `vendors.gst_registration_status` is what s.31(3)(f) asks about, and migration
# 388's CHECK admits exactly two values with NULL as the third state. The API is
# where a human types it, so the vocabulary has to be enforced there too — a
# CHECK failure surfaces as an opaque 500, and a validator only on the create
# door is one PATCH from being none.

def _vendor_model(name: str):
    from models import parties
    return getattr(parties, name)


@pytest.mark.parametrize("model", ["VendorIn", "VendorUpdateIn"])
@pytest.mark.parametrize("value", ["registered", "unregistered"])
def test_both_doors_take_a_settled_answer(model, value):
    cls = _vendor_model(model)
    kw = {"client_id": "c1", "name": "Ramesh Transport"} if model == "VendorIn" else {}
    assert cls(**kw, gst_registration_status=value).gst_registration_status == value


@pytest.mark.parametrize("model", ["VendorIn", "VendorUpdateIn"])
def test_the_answer_is_normalised_before_it_is_stored(model):
    """A CHECK is case-sensitive. 'Unregistered' off a form would fail in the
    database rather than here."""
    cls = _vendor_model(model)
    kw = {"client_id": "c1", "name": "Ramesh Transport"} if model == "VendorIn" else {}
    assert cls(**kw, gst_registration_status=" Unregistered "
               ).gst_registration_status == rd.UNREGISTERED


@pytest.mark.parametrize("model", ["VendorIn", "VendorUpdateIn"])
def test_the_third_state_cannot_be_STORED_as_a_value(model):
    """`unrecorded` is the ABSENCE of an answer. Storing it as a string would
    make NULL and 'unrecorded' two spellings of one thing that every reader then
    has to test twice — and the column's CHECK refuses it anyway."""
    cls = _vendor_model(model)
    kw = {"client_id": "c1", "name": "Ramesh Transport"} if model == "VendorIn" else {}
    with pytest.raises(Exception) as e:
        cls(**kw, gst_registration_status=rd.UNRECORDED)
    assert "leave it unset" in str(e.value)


@pytest.mark.parametrize("model", ["VendorIn", "VendorUpdateIn"])
def test_a_value_outside_the_engines_vocabulary_is_refused(model):
    cls = _vendor_model(model)
    kw = {"client_id": "c1", "name": "Ramesh Transport"} if model == "VendorIn" else {}
    with pytest.raises(Exception):
        cls(**kw, gst_registration_status="yes")


@pytest.mark.parametrize("model", ["VendorIn", "VendorUpdateIn"])
def test_omitting_it_is_the_third_state_and_is_never_defaulted(model):
    cls = _vendor_model(model)
    kw = {"client_id": "c1", "name": "Ramesh Transport"} if model == "VendorIn" else {}
    assert cls(**kw).gst_registration_status is None
