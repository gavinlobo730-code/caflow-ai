"""PUR-18 — a Bill of Entry, and the split between credit and cost.

The test that matters most in this file is
`test_basic_customs_duty_is_never_input_tax`: it is the one that fails if the
assessment is ever treated as one figure, which is the natural thing to do and
is wrong. CGST Act s.2(62)(a) makes the integrated tax on an import input tax;
AS-2 paragraph 6 makes a duty recoverable from nobody part of the cost. Putting
customs duty into Table 4(A)(1) claims credit that does not exist.
"""
from __future__ import annotations

import inspect
import pathlib
import re

import pytest

from domain.gst import bill_of_entry as boe
from domain.gst.gstr3b_computer import (
    compute_gstr3b, ImportOfGoods, PurchaseTransaction, GSTR2ARecord,
)

API = pathlib.Path(__file__).resolve().parent.parent
MIGRATION = API / "migrations" / "389_a_bill_of_entry_is_where_import_igst_enters_the_books.sql"
ROLLBACK = API / "migrations" / "389_a_bill_of_entry_is_where_import_igst_enters_the_books_rollback.sql"


def _row(**over):
    base = {
        "id": "BOE1", "firm_id": "F1", "client_id": "C1",
        "be_number": "1234567", "be_date": "2026-06-10", "port_code": "INNSA1",
        "assessable_value_paise": 10_00_000_00,
        "basic_customs_duty_paise": 1_00_000_00,
        "social_welfare_surcharge_paise": 10_000_00,
        "other_duty_paise": 0,
        "igst_paise": 1_98_000_00, "cess_paise": 0,
        "ineligible_igst_paise": 0, "ineligible_cess_paise": 0,
        "is_sez": False,
        "payment_account_id": "ACC-BANK", "duty_expense_account_id": "ACC-DUTY",
        "status": "draft",
    }
    base.update(over)
    return base


# ── The split ────────────────────────────────────────────────────────────────

def test_basic_customs_duty_is_never_input_tax():
    """The whole point. Basic customs duty and the social welfare surcharge are
    recoverable from nobody, so AS-2 paragraph 6 puts them in the cost of
    purchase. `ImportOfGoods` has no field for either, which is how a caller
    cannot put one on the return by accident."""
    assert not hasattr(ImportOfGoods(), "basic_customs_duty_paise")
    assert not hasattr(ImportOfGoods(), "social_welfare_surcharge_paise")
    a = boe.assessment_of(_row())
    assert a.creditable_igst_paise == 1_98_000_00
    assert a.non_creditable_duty_paise == 1_00_000_00 + 10_000_00


def test_an_import_carries_no_central_or_state_tax():
    """IGST Act s.7(2) makes goods imported into India an inter-state supply
    until they cross the customs frontier, so integrated tax and cess are the
    only heads an assessment can charge. A CGST field here would be a place to
    put a figure that cannot exist."""
    assert not hasattr(ImportOfGoods(), "cgst_paise")
    assert not hasattr(ImportOfGoods(), "sgst_paise")


def test_the_blocked_part_of_the_tax_moves_to_cost():
    """CGST Act s.17(5) credit is recoverable from nobody either, which is the
    same test AS-2 paragraph 6 applies."""
    a = boe.assessment_of(_row(ineligible_igst_paise=50_000_00))
    assert a.creditable_igst_paise == 1_48_000_00
    assert a.non_creditable_duty_paise == 1_00_000_00 + 10_000_00 + 50_000_00


def test_the_total_is_everything_paid_to_customs():
    """It is the credit leg of the journal, so it has to be the whole
    assessment — credit plus cost, with nothing left over."""
    a = boe.assessment_of(_row(cess_paise=20_000_00, other_duty_paise=5_000_00))
    assert a.total_paise == a.creditable_igst_paise + a.creditable_cess_paise \
                          + a.non_creditable_duty_paise


@pytest.mark.parametrize("over", [
    {},
    {"ineligible_igst_paise": 1_98_000_00},
    {"cess_paise": 7_777_77, "ineligible_cess_paise": 1_111_11},
    {"basic_customs_duty_paise": 0, "social_welfare_surcharge_paise": 0},
])
def test_credit_plus_cost_is_always_the_total(over):
    """Stated as an identity rather than a range: the journal's credit leg is
    `total_paise` and its debits are the other two, so any gap is a posting
    that does not balance."""
    a = boe.assessment_of(_row(**over))
    assert (a.creditable_igst_paise + a.creditable_cess_paise
            + a.non_creditable_duty_paise) == a.total_paise


# ── Which 2B section ─────────────────────────────────────────────────────────

def test_an_sez_supply_is_its_own_section():
    """GSTR-2B carries `impg` and `impgsez` separately, so a reconciliation
    that collapses them cannot match either."""
    assert boe.section_for(_row()) == boe.SECTION_IMPG
    assert boe.section_for(_row(is_sez=True)) == boe.SECTION_IMPGSEZ


# ── Can it post? ─────────────────────────────────────────────────────────────

def test_a_document_with_no_duty_at_all_cannot_post():
    r = boe.readiness(_row(igst_paise=0, basic_customs_duty_paise=0,
                           social_welfare_surcharge_paise=0, cess_paise=0))
    assert not r.ok
    assert any("nothing to post" in x for x in r.refusals)


def test_the_payment_account_is_required():
    r = boe.readiness(_row(payment_account_id=None))
    assert not r.ok
    assert any("s.47" in x for x in r.refusals)


def test_the_duty_account_is_required_only_when_there_is_duty():
    """A consignment assessed to IGST alone owes no expense leg, so demanding
    an account for it would refuse a document that is complete."""
    assert not boe.readiness(_row(duty_expense_account_id=None)).ok
    ok = boe.readiness(_row(duty_expense_account_id=None,
                            basic_customs_duty_paise=0,
                            social_welfare_surcharge_paise=0))
    assert ok.ok


def test_a_missing_port_is_a_CAVEAT_and_not_a_refusal():
    """A CA entering last month's duty off a challan may not hold the document.
    The 2B match names it rather than the row being refused — the `reasons` and
    `gaps` distinction PUR-19 states, in this module's own vocabulary."""
    r = boe.readiness(_row(port_code=None))
    assert r.ok
    assert any("GSTR-2B" in x for x in r.caveats)


def test_the_duty_says_it_is_not_apportioned_into_stock():
    """AS-2 paragraph 6 would put it in the cost of the goods themselves. The
    basis for that split is an owner decision (INV-05), so the answer SAYS it
    was not made rather than making one."""
    r = boe.readiness(_row())
    assert any("apportioned" in x for x in r.caveats)


def test_blocked_credit_says_it_does_not_reach_the_return():
    r = boe.readiness(_row(ineligible_igst_paise=1_000_00))
    assert any("17(5)" in x for x in r.caveats)


# ── The return ───────────────────────────────────────────────────────────────

def _rows(result):
    return {ty: (i, c, s, x) for ty, i, c, s, x in result.itc_avl_rows()}


def test_the_import_reaches_table_4a_1_and_nowhere_else():
    r = compute_gstr3b([], [], [], imports_of_goods=[
        ImportOfGoods(igst_paise=1_98_000_00, cess_paise=20_000_00)])
    rows = _rows(r)
    assert rows["IMPG"] == (1_98_000_00, 0, 0, 20_000_00)
    assert rows["IMPS"] == (0, 0, 0, 0)
    assert rows["ISRC"] == (0, 0, 0, 0)
    assert rows["OTH"] == (0, 0, 0, 0)


def test_an_import_creates_no_reverse_charge_liability():
    """Table 3.1(d) is tax the RECIPIENT self-assesses. This tax was assessed
    and collected by customs, so declaring it there would pay it twice."""
    r = compute_gstr3b([], [], [], imports_of_goods=[
        ImportOfGoods(igst_paise=1_98_000_00)])
    assert r.rcm_igst == 0 and r.rcm_cgst == 0 and r.rcm_sgst == 0
    assert r.cash_payable_igst == 0


def test_the_import_credit_is_available_credit():
    r = compute_gstr3b([], [], [], imports_of_goods=[
        ImportOfGoods(igst_paise=1_98_000_00, cess_paise=5_000_00)])
    assert r.itc_igst == 1_98_000_00
    assert r.itc_cess == 5_000_00


def test_blocked_import_credit_is_excluded_and_reported():
    r = compute_gstr3b([], [], [], imports_of_goods=[
        ImportOfGoods(igst_paise=1_98_000_00, ineligible_igst_paise=48_000_00)])
    assert r.itc_igst == 1_50_000_00
    assert r.itc_ineligible_igst == 48_000_00
    assert _rows(r)["IMPG"][0] == 1_50_000_00


def test_the_five_rows_still_sum_to_4a():
    """The GSTN utility writes all five and they must reconcile with 4(C).
    Adding a sixth source of credit is exactly where that breaks."""
    r = compute_gstr3b(
        [],
        [PurchaseTransaction(taxable_amount_paise=1_00_000_00, cgst_paise=9_000_00,
                             sgst_paise=9_000_00, igst_paise=0, cess_paise=0,
                             is_reverse_charge=False),
         PurchaseTransaction(taxable_amount_paise=50_000_00, cgst_paise=0,
                             sgst_paise=0, igst_paise=9_000_00, cess_paise=0,
                             is_reverse_charge=True)],
        [],
        imports_of_goods=[ImportOfGoods(igst_paise=1_98_000_00)])
    rows = r.itc_avl_rows()
    assert sum(x[1] for x in rows) == r.itc_avail_igst
    assert sum(x[2] for x in rows) == r.itc_avail_cgst
    assert sum(x[3] for x in rows) == r.itc_avail_sgst
    assert sum(x[4] for x in rows) == r.itc_avail_cess


def test_the_rows_still_sum_when_rule_36_4_has_trimmed_the_ceiling():
    """The ceiling is what the cap left. Import credit gives way LAST, because
    the two reverse-charge rows carry tax already paid in cash that Rule 36(4)
    cannot reach at all."""
    r = compute_gstr3b(
        [],
        [PurchaseTransaction(taxable_amount_paise=10_00_000_00, cgst_paise=0,
                             sgst_paise=0, igst_paise=1_80_000_00, cess_paise=0,
                             is_reverse_charge=False)],
        [GSTR2ARecord(cgst_paise=0, sgst_paise=0, igst_paise=10_000_00)],
        have_2b=True,
        imports_of_goods=[ImportOfGoods(igst_paise=1_98_000_00)])
    rows = r.itc_avl_rows()
    assert sum(x[1] for x in rows) == r.itc_avail_igst
    assert all(x[1] >= 0 for x in rows)


def test_an_empty_import_list_leaves_every_figure_where_it_was():
    """Every existing caller passes nothing. The default must be inert."""
    args = ([], [PurchaseTransaction(taxable_amount_paise=1_00_000_00,
                                     cgst_paise=9_000_00, sgst_paise=9_000_00,
                                     igst_paise=0, cess_paise=0,
                                     is_reverse_charge=False)], [])
    a = compute_gstr3b(*args)
    b = compute_gstr3b(*args, imports_of_goods=[])
    assert a.itc_avl_rows() == b.itc_avl_rows()
    assert a.itc_igst == b.itc_igst and a.itc_cess == b.itc_cess


def test_4a_1_is_no_longer_a_named_gap():
    from services.gst_return_service import _table_4a_gaps
    assert [g["row"] for g in _table_4a_gaps()] == ["4(A)(4)"]


# ── The service ──────────────────────────────────────────────────────────────

def test_the_journal_touches_no_accounts_payable():
    """The supplier is not owed this money — customs is. Debiting Trade
    Payables is precisely what putting the assessment on the purchase bill
    gets wrong."""
    from services import bill_of_entry_service as svc
    src = inspect.getsource(svc.post)
    assert "payable" not in src.lower()
    assert "vendor" not in src.lower()


def test_the_posting_path_asks_both_period_questions():
    from services import bill_of_entry_service as svc
    src = inspect.getsource(svc.post)
    assert "validate_posting_date" in src
    assert "period_lock_service.assert_open" in src


def test_the_return_reads_POSTED_documents_only():
    """A draft has no journal behind it, so declaring its credit would create
    the books-vs-ledger difference the reconciliation exists to catch."""
    from services import bill_of_entry_service as svc
    assert '"posted"' in inspect.getsource(svc.for_period)


def test_the_service_posts_through_the_one_kernel():
    from services import bill_of_entry_service as svc
    src = inspect.getsource(svc.post)
    assert "_create_journal" in src
    assert "journal_source.BILL_OF_ENTRY" in src


def test_cess_credit_goes_to_its_own_ledger():
    """The proviso to s.11(2) of the Compensation Act lets cess credit pay only
    cess, so it must never resolve to the GST input account."""
    from services import bill_of_entry_service as svc
    src = inspect.getsource(svc.post)
    assert "gst_cess_input" in src


def test_the_router_decides_nothing_itself():
    """Scanned over the CODE, with docstrings and comments stripped.

    A citation in prose is the router saying why it keeps two fields apart,
    which is worth having; a citation beside arithmetic would be the rule
    living in a second place. The earlier version of this test read the raw
    file and failed on the docstring — a guard that names a spelling rather
    than the rule, which is the shape CLAUDE.md keeps warning about.
    """
    import ast

    tree = ast.parse((API / "routers" / "bills_of_entry.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            node.value.value = ""
    code = ast.unparse(tree)
    for word in ("creditable_igst", "non_creditable", "basic_customs_duty_paise +"):
        assert word not in code, f"{word!r} is the domain module's to compute"


def test_every_endpoint_checks_the_clients_scope():
    import ast
    src = (API / "routers" / "bills_of_entry.py").read_text()
    tree = ast.parse(src)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(isinstance(d, ast.Call)
                   and getattr(d.func, "attr", "") in ("get", "post", "patch", "delete")
                   for d in fn.decorator_list):
            continue
        body = ast.get_source_segment(src, fn) or ""
        if "client_id" not in body:
            # `/authorities` is reference data about the STATUTE.
            assert fn.name == "authorities", fn.name
            continue
        assert "assert_client_access" in body, fn.name


# ── The migration ────────────────────────────────────────────────────────────

def test_the_migration_exists_and_creates_the_table():
    text = MIGRATION.read_text()
    assert "CREATE TABLE IF NOT EXISTS public.bills_of_entry" in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "bills_of_entry_assignment_scope" in text


def test_the_registration_column_is_not_what_the_duty_account_is_named_by():
    """The duty account is the CA's own choice and is a FK, never resolved by
    name: 'Customs Duty' seeded for convenience is a default, not a rule."""
    text = MIGRATION.read_text()
    assert "duty_expense_account_id     UUID REFERENCES public.chart_of_accounts(id)" in text


def test_the_seeded_duty_account_lands_above_the_gross_margin():
    """`schedule_iii.pl_bucket` scans the SUBTYPE for keywords and has no entry
    for 'Direct Expense' — which is why migration 197 moved 5000 and 5001 off
    it. Asserted against the classifier rather than against a spelling."""
    from domain.reporting.schedule_iii import pl_bucket
    subtype = re.search(r"'Expense', '([^']+)', TRUE, 'customs_duty'",
                        MIGRATION.read_text())
    assert subtype, "the seed no longer names a subtype"
    assert pl_bucket("Expense", subtype.group(1)) == "Cost of Materials Consumed"


def test_the_account_code_does_not_collide_with_one_already_seeded():
    """ON CONFLICT DO NOTHING makes a collision SILENT — an account nobody can
    find rather than an error anybody sees."""
    mine = re.search(r"'(\d{4})', 'Customs Duty'", MIGRATION.read_text())
    assert mine
    taken = set()
    for f in sorted((API / "migrations").glob("*.sql")):
        if f == MIGRATION:
            continue
        taken.update(re.findall(r"'(5\d{3})',\s*'[A-Z]", f.read_text()))
    assert mine.group(1) not in taken


def test_the_rollback_refuses_while_documents_exist():
    text = ROLLBACK.read_text()
    assert "RAISE EXCEPTION" in text
    assert "Refusing to roll back 389" in text


def test_what_is_not_modelled_is_named_rather_than_assumed():
    joined = " ".join(boe.NOT_MODELLED)
    assert "s.47(2)" in joined          # deferred payment of duty
    assert "s.27" in joined             # refund of duty
    assert "INV-05" in joined           # the apportionment


# ── WHAT IS ACTUALLY POSTED ──────────────────────────────────────────────────
#
# The tests above read the SERVICE'S SOURCE, which cannot tell a balanced
# journal from an unbalanced one — a negative control proved it: replacing the
# payment leg's `total_paise` with `igst_paise`, so the credit side was short
# by the whole customs duty, left every test above green. The kernel's own
# balance assertion would have caught it at runtime, on a CA's screen. These
# build the lines and check them here.

class _CapturedJournal(Exception):
    """Carries the lines out of the fake kernel."""
    def __init__(self, lines, kwargs):
        self.lines = lines
        self.kwargs = kwargs


def _lines_for(monkeypatch, row: dict):
    from services import bill_of_entry_service as svc
    from services.phase2_journal_service import phase2_journal_service as pjs
    from services.period_validation_service import period_validation_service
    from services import period_lock_service

    monkeypatch.setattr(svc, "get", lambda db, firm_id, be_id: row)
    monkeypatch.setattr(period_validation_service, "validate_posting_date",
                        lambda *a, **k: None)
    monkeypatch.setattr(period_lock_service, "assert_open", lambda *a, **k: None)
    monkeypatch.setattr(pjs, "_find_account",
                        lambda db, f, c, pattern, system_key=None: f"ACC:{system_key}")

    def _fake(db, firm_id, client_id, entry_date, **kw):
        raise _CapturedJournal(kw["lines"], kw)

    monkeypatch.setattr(pjs, "_create_journal", _fake)
    with pytest.raises(_CapturedJournal) as e:
        svc.post(object(), "F1", "BOE1")
    return e.value


def test_the_posting_balances(monkeypatch):
    """The one invariant the whole journal rests on. The credit leg is
    everything paid to customs; the debits are the credit and the cost, which
    are defined to sum to it."""
    captured = _lines_for(monkeypatch, _row(cess_paise=20_000_00,
                                            other_duty_paise=5_000_00,
                                            ineligible_igst_paise=8_000_00))
    debit = sum(l["debit_paise"] for l in captured.lines)
    credit = sum(l["credit_paise"] for l in captured.lines)
    assert debit == credit, f"debits {debit} != credits {credit}"


def test_the_credit_leg_is_the_whole_assessment(monkeypatch):
    captured = _lines_for(monkeypatch, _row(cess_paise=20_000_00))
    credits = [l for l in captured.lines if l["credit_paise"]]
    assert len(credits) == 1, "customs is paid once"
    assert credits[0]["account_id"] == "ACC:bank" or credits[0]["account_id"] == "ACC-BANK"
    assert credits[0]["credit_paise"] == boe.assessment_of(
        _row(cess_paise=20_000_00)).total_paise


def test_each_debit_goes_where_the_statute_puts_it(monkeypatch):
    captured = _lines_for(monkeypatch, _row(cess_paise=20_000_00))
    by_account = {l["account_id"]: l["debit_paise"]
                  for l in captured.lines if l["debit_paise"]}
    a = boe.assessment_of(_row(cess_paise=20_000_00))
    # Input tax to the input ledger the rest of the product uses.
    assert by_account["ACC:gst_input"] == a.creditable_igst_paise
    # Cess to its OWN ledger — the proviso to s.11(2).
    assert by_account["ACC:gst_cess_input"] == a.creditable_cess_paise
    # Duty to the account the CA named, never one resolved by name.
    assert by_account["ACC-DUTY"] == a.non_creditable_duty_paise


def test_a_head_with_no_amount_gets_no_line(monkeypatch):
    """A zero-value line is noise on a voucher and the kernel would carry it."""
    captured = _lines_for(monkeypatch, _row(cess_paise=0))
    assert all(l["debit_paise"] or l["credit_paise"] for l in captured.lines)
    assert "ACC:gst_cess_input" not in {l["account_id"] for l in captured.lines}


def test_the_entry_names_the_document_it_came_from(monkeypatch):
    from domain.accounting import journal_source
    captured = _lines_for(monkeypatch, _row())
    assert captured.kwargs["source_type"] == journal_source.BILL_OF_ENTRY
    assert captured.kwargs["source_id"] == "BOE1"
