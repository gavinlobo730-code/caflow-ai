"""Form 3CD (IT-11): the clause vocabulary, the register builder, and that
every derived clause in the service reuses an existing module rather than
re-deriving it.
"""
import ast
import uuid

import pytest

from domain.income_tax import form_3cd as f3cd
from tests.e2e_harness import FakeDB


# ── The clause vocabulary itself ─────────────────────────────────────────────

def test_every_clause_has_a_unique_code():
    codes = [c.code for c in f3cd.CLAUSES]
    assert len(codes) == len(set(codes)), codes


def test_the_clause_order_matches_the_forms_own_numbering():
    """A CA reading this register against a printed 3CD must see the same
    order — a reshuffled vocabulary is worse than a missing one."""
    codes = [c.code for c in f3cd.CLAUSES]
    assert codes[:10] == ["1", "2", "3", "4", "5", "6", "7", "8", "8A", "9"]
    assert codes[-6:] == ["39", "40", "41", "42", "43", "44"]
    # 28 and 29 are omitted from the form but kept as placeholders so the
    # numbering is not silently missing a clause.
    assert "28" in codes and "29" in codes
    i28, i29 = codes.index("28"), codes.index("29")
    assert codes[i28 - 1] == "27" and codes[i29 + 1] == "30"


def test_a_derivable_clause_names_no_manual_reason():
    for c in f3cd.CLAUSES:
        if c.derivable:
            assert c.manual_reason is None, c.code
        else:
            assert c.manual_reason, f"clause {c.code} has no reason recorded"


def test_derivable_codes_matches_the_clauses_flag():
    assert f3cd.DERIVABLE_CODES == tuple(
        c.code for c in f3cd.CLAUSES if c.derivable)


def test_the_eight_clauses_this_product_answers():
    """Pinned so a change to which clauses are derivable is a deliberate
    edit, not a silent drift as modules are added or removed."""
    assert set(f3cd.DERIVABLE_CODES) == {
        "8", "14", "18", "22", "26", "32", "34", "44",
    }


# ── build_register ───────────────────────────────────────────────────────────

def test_build_register_covers_every_clause_exactly_once():
    reg = f3cd.build_register(client_id="c1", financial_year="2025-26", derived={})
    assert len(reg.clauses) == len(f3cd.CLAUSES)
    assert reg.manual_count == len(f3cd.CLAUSES)
    assert reg.derived_count == 0


def test_a_resolved_derived_clause_counts_as_derived():
    reg = f3cd.build_register(
        client_id="c1", financial_year="2025-26",
        derived={"22": ({"interest_paise": 500}, "test source")})
    by_code = {c.code: c for c in reg.clauses}
    assert by_code["22"].derived is True
    assert by_code["22"].value == {"interest_paise": 500}
    assert reg.derived_count == 1


def test_a_derivable_clause_with_no_value_is_not_counted_as_derived():
    """A derivable clause this call could not resolve reads as manual, not as
    a silently-zero derived answer."""
    reg = f3cd.build_register(
        client_id="c1", financial_year="2025-26",
        derived={"18": (None, "could not compute")})
    by_code = {c.code: c for c in reg.clauses}
    assert by_code["18"].derived is False
    assert by_code["18"].value is None
    assert reg.derived_count == 0


def test_a_non_derivable_clause_carries_its_own_reason_by_default():
    reg = f3cd.build_register(client_id="c1", financial_year="2025-26", derived={})
    by_code = {c.code: c for c in reg.clauses}
    definition = {c.code: c for c in f3cd.CLAUSES}
    assert by_code["31"].note == definition["31"].manual_reason


def test_a_manual_entry_from_the_ca_is_carried_through_but_never_marked_derived():
    """`manual` is a SEPARATE channel from `derived` precisely so a CA's own
    note can never come back looking like a computed figure — the exact bug
    that would make a saved textarea entry render read-only next time the
    register opens."""
    reg = f3cd.build_register(
        client_id="c1", financial_year="2025-26", derived={},
        manual={"31": "Recorded: no such loans this year."})
    by_code = {c.code: c for c in reg.clauses}
    assert by_code["31"].value == "Recorded: no such loans this year."
    assert by_code["31"].derived is False
    assert reg.derived_count == 0
    assert reg.manual_count == len(f3cd.CLAUSES)


def test_a_manual_entry_cannot_masquerade_as_derived_for_a_derivable_clause():
    """Even where the code IS one this product can derive, a value supplied
    only through `manual` (never `derived`) must not count as computed."""
    reg = f3cd.build_register(
        client_id="c1", financial_year="2025-26", derived={},
        manual={"14": "fifo, per the CA"})
    by_code = {c.code: c for c in reg.clauses}
    assert by_code["14"].derived is False
    assert by_code["14"].value == "fifo, per the CA"


# ── Reuse discipline: the service must not re-derive a rule it can call ─────

def _service_source() -> str:
    with open("services/form_3cd_service.py") as f:
        return f.read()


@pytest.mark.parametrize("must_import", [
    "from services.msme_43bh_service import for_financial_year",
    "from services.section_32_service import section_32_service",
    "from domain.income_tax.computation_workspace import list_bf_losses",
    "from domain.accounting.opening_documents import without_carried_over",
])
def test_the_service_reuses_the_existing_module_rather_than_reimplementing(must_import):
    assert must_import in _service_source()


def test_the_service_never_recomputes_msmed_interest_or_43bh_disallowance():
    """These two rules are elaborate (compound interest with monthly rests;
    fifteen/forty-five day agreements; goods-receipt acceptance dates) and
    this codebase has exactly one implementation of each. A second one here
    would be the defect CLAUDE.md's `domain/recurrence.py` bullet warns about."""
    tree = ast.parse(_service_source())
    names = {n.id for node in ast.walk(tree) for n in ast.walk(node)
             if isinstance(n, ast.Name)}
    # Neither module's own internal helpers should be reachable by name here —
    # only the public entry point each already exposes.
    assert "late_amounts" not in names
    assert "compound_interest_paise" not in names


# ── The service, against the shared in-memory double ────────────────────────

FIRM = str(uuid.uuid4())
CLIENT = str(uuid.uuid4())


def _seed_basics(db: FakeDB):
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM,
                        "inventory_costing_method": "fifo"})


def test_clause_14_reads_the_clients_own_costing_policy():
    from services.form_3cd_service import _clause_14
    db = FakeDB()
    _seed_basics(db)
    value, note = _clause_14(db, FIRM, CLIENT)
    assert value == "fifo"
    assert "inventory_costing_method" in note


def test_clause_14_defaults_to_weighted_average_when_unrecorded():
    from services.form_3cd_service import _clause_14
    db = FakeDB()
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM})
    value, note = _clause_14(db, FIRM, CLIENT)
    assert value == "weighted_average"
    assert "No policy is recorded" in note


def test_clause_8_names_the_gap_when_no_tax_audit_row_exists():
    from services.form_3cd_service import _clause_8
    db = FakeDB()
    value, note = _clause_8(db, FIRM, CLIENT, "2025-26", nature="business")
    assert value is None
    assert "No Tax Audit tracker entry" in note


def test_clause_8_names_the_gap_when_nature_is_not_supplied():
    from services.form_3cd_service import _clause_8
    db = FakeDB()
    db.seed("tax_audits", {"firm_id": FIRM, "client_id": CLIENT,
                           "financial_year": "2025-26",
                           "turnover_paise": 5_00_00_000_00,
                           "form_type": "3CB-3CD"})
    value, note = _clause_8(db, FIRM, CLIENT, "2025-26", nature=None)
    assert value is None
    assert "never inferred from the amount" in note


def test_clause_8_resolves_when_both_facts_are_present():
    from services.form_3cd_service import _clause_8
    db = FakeDB()
    db.seed("tax_audits", {"firm_id": FIRM, "client_id": CLIENT,
                           "financial_year": "2025-26",
                           "turnover_paise": 5_00_00_000_00,
                           "form_type": "3CB-3CD"})
    value, note = _clause_8(db, FIRM, CLIENT, "2025-26", nature="business")
    assert value is not None
    assert value["clause"] == "44AB(a)"


def test_clause_32_names_the_gap_and_the_untested_limbs_even_with_no_rows():
    from services.form_3cd_service import _clause_32
    db = FakeDB()
    value, note = _clause_32(db, FIRM, CLIENT)
    assert value == []
    assert "§79" in note and "§73" in note


def test_clause_32_reads_brought_forward_losses():
    """`domain.income_tax.computation_workspace.list_bf_losses` resolves its
    OWN store (the mock-mode dict in-process, or its own Supabase client
    against `brought_forward_losses` in production) rather than taking a
    `db` argument — so this seeds through the module's own writer,
    `create_bf_loss`, the way IT-10's own tests do, rather than through the
    unrelated FakeDB `_clause_32` is otherwise given."""
    from services.form_3cd_service import _clause_32
    from domain.income_tax.computation_workspace import create_bf_loss
    create_bf_loss(FIRM, CLIENT, "2024-25", "business", 10_00_000_00,
                   "2032-33", created_by="tester")
    db = FakeDB()
    value, _note = _clause_32(db, FIRM, CLIENT)
    assert len(value) == 1
    assert value[0]["loss_type"] == "business"
    assert value[0]["remaining_amount_paise"] == 10_00_000_00


def test_clause_44_splits_by_vendor_gst_registration_status():
    from services.form_3cd_service import _clause_44
    db = FakeDB()
    v_reg = db.seed("vendors", {"firm_id": FIRM, "gst_registration_status": "registered"})
    v_unreg = db.seed("vendors", {"firm_id": FIRM, "gst_registration_status": "unregistered"})
    v_unknown = db.seed("vendors", {"firm_id": FIRM})
    db.seed("purchase_bills", {
        "firm_id": FIRM, "client_id": CLIENT, "vendor_id": v_reg["id"],
        "total_paise": 1_00_000_00, "status": "received",
        "bill_date": "2025-06-15", "is_opening": False,
    })
    db.seed("purchase_bills", {
        "firm_id": FIRM, "client_id": CLIENT, "vendor_id": v_unreg["id"],
        "total_paise": 50_000_00, "status": "received",
        "bill_date": "2025-07-20", "is_opening": False,
    })
    db.seed("purchase_bills", {
        "firm_id": FIRM, "client_id": CLIENT, "vendor_id": v_unknown["id"],
        "total_paise": 20_000_00, "status": "received",
        "bill_date": "2025-08-01", "is_opening": False,
    })
    # Outside the financial year — must not be counted.
    db.seed("purchase_bills", {
        "firm_id": FIRM, "client_id": CLIENT, "vendor_id": v_reg["id"],
        "total_paise": 9_999_00, "status": "received",
        "bill_date": "2024-01-01", "is_opening": False,
    })
    # Cancelled — must not be counted.
    db.seed("purchase_bills", {
        "firm_id": FIRM, "client_id": CLIENT, "vendor_id": v_reg["id"],
        "total_paise": 9_999_00, "status": "cancelled",
        "bill_date": "2025-09-01", "is_opening": False,
    })
    # An opening/carried-over bill — must not be counted (ACC-14's rule).
    db.seed("purchase_bills", {
        "firm_id": FIRM, "client_id": CLIENT, "vendor_id": v_reg["id"],
        "total_paise": 9_999_00, "status": "received",
        "bill_date": "2025-09-02", "is_opening": True,
    })
    value, note = _clause_44(db, FIRM, CLIENT, "2025-26")
    assert value["registered_paise"] == 1_00_000_00
    assert value["unregistered_paise"] == 50_000_00
    assert value["unrecorded_paise"] == 20_000_00
    assert value["total_expenditure_paise"] == 1_70_000_00
    assert "opening" in note.lower() or "carried-over" in note.lower()


def test_clause_34_groups_tds_deductions_by_section():
    from services.form_3cd_service import _clause_34
    db = FakeDB()
    db.seed("client_statutory_identity", {"firm_id": FIRM, "client_id": CLIENT,
                                          "tan": "MUMB12345A"})
    db.seed("tds_deductions", {
        "firm_id": FIRM, "client_id": CLIENT, "section": "194C",
        "payment_amount_paise": 1_00_000_00, "tds_paise": 2_000_00,
        "status": "deposited", "transaction_date": "2025-05-10",
    })
    db.seed("tds_deductions", {
        "firm_id": FIRM, "client_id": CLIENT, "section": "194C",
        "payment_amount_paise": 50_000_00, "tds_paise": 1_000_00,
        "status": "deducted", "transaction_date": "2025-06-10",
    })
    db.seed("tds_deductions", {
        "firm_id": FIRM, "client_id": CLIENT, "section": "194J",
        "payment_amount_paise": 20_000_00, "tds_paise": 2_000_00,
        "status": "deposited", "transaction_date": "2025-07-10",
    })
    value, note = _clause_34(db, FIRM, CLIENT, "2025-26")
    assert value["tan"] == "MUMB12345A"
    by_section = {r["section"]: r for r in value["by_section"]}
    assert by_section["194C"]["total_amount_paise"] == 1_50_000_00
    assert by_section["194C"]["total_tds_deducted_paise"] == 3_000_00
    assert by_section["194C"]["total_tds_deposited_paise"] == 2_000_00
    assert by_section["194C"]["tax_deducted_not_deposited_paise"] == 1_000_00
    assert by_section["194J"]["total_tds_deposited_paise"] == 2_000_00
    assert "SIMPLIFIED" in note


# ── The build() entry point and the manual-clause store ─────────────────────

def test_build_returns_every_clause_and_reads_a_saved_manual_entry():
    from services.form_3cd_service import build, save_manual_clauses
    db = FakeDB()
    _seed_basics(db)
    save_manual_clauses(db, FIRM, CLIENT, "2025-26",
                        {"31": "No such loans this year."}, status="review")
    out = build(db, FIRM, CLIENT, "2025-26")
    assert len(out["clauses"]) == len(f3cd.CLAUSES)
    assert out["checklist_status"] == "review"
    by_code = {c["code"]: c for c in out["clauses"]}
    assert by_code["31"]["value"] == "No such loans this year."


def test_a_manual_entry_never_shadows_a_derived_clause():
    """A note saved against a clause the service CAN derive must not hide the
    live figure the next time the register is built."""
    from services.form_3cd_service import build, save_manual_clauses
    db = FakeDB()
    _seed_basics(db)
    save_manual_clauses(db, FIRM, CLIENT, "2025-26",
                        {"14": "the CA's own stale note"}, status="draft")
    out = build(db, FIRM, CLIENT, "2025-26")
    by_code = {c["code"]: c for c in out["clauses"]}
    # clause 14 is derivable and resolved (inventory_costing_method='fifo'
    # from _seed_basics), so it must show the LIVE figure, not the stale note.
    assert by_code["14"]["value"] == "fifo"


def test_save_manual_clauses_upserts_rather_than_duplicating():
    from services.form_3cd_service import save_manual_clauses
    db = FakeDB()
    save_manual_clauses(db, FIRM, CLIENT, "2025-26", {"31": "first"})
    save_manual_clauses(db, FIRM, CLIENT, "2025-26", {"31": "second"})
    rows = [r for r in db.rows("tax_audit_checklists")
            if r["firm_id"] == FIRM and r["client_id"] == CLIENT]
    assert len(rows) == 1
    assert rows[0]["clauses_json"]["31"] == "second"
