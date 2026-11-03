"""The sale and purchase ledger entries written before entries named their document name it now (migration 580, POST-A-372).

Entries from before the source stamp existed carry no `source_type` / `source_id`, so the customer-wise and vendor-wise breakdowns of the
control accounts cannot attribute them (`party_ledger_as_at` finds a party only through `source_id`) and the ledger cannot open their document.
The migration stamps an entry only where exactly one document of its own firm and client names it, gives the vendor-payment entry that names
its kind the payment that names it, and hands each reversal its original's source. Only a real database can show that nothing else moves,
that a posted entry is stamped through the audited allowance and the allowance is cleared again, and that the rollback undoes exactly what the
migration's own audit rows name. Real Postgres, throwaway database.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")
MIGRATION = next(API_ROOT.glob("migrations/580_a_sale_or_purchase_entry_from_before_entries_named_their_document_names_it_now.sql"))
ROLLBACK = next(API_ROOT.glob("migrations/580_*_rollback.sql"))

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="requires HARNESS_PG + psql",
)

FIRM, OTHER_FIRM = "f5800000-0000-0000-0000-000000000001", "f5800000-0000-0000-0000-0000000000ff"
CLIENT, OTHER_CLIENT, FOREIGN_CLIENT = (f"c5800000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3))
CUSTOMER, OTHER_CUSTOMER, FOREIGN_CUSTOMER = (f"e5800000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3))
VENDOR, OTHER_VENDOR, FOREIGN_VENDOR = (f"d5800000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3))
ACC_A, ACC_B, FOREIGN_ACC_A, FOREIGN_ACC_B = (f"a5800000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3, 4))


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> None:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr


def _val(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _run(dsn: str, path: Path) -> subprocess.CompletedProcess:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e580_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        seed = _psql(d, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
                ('{CLIENT}', '{FIRM}', 'A', 'Proprietorship'), ('{OTHER_CLIENT}', '{FIRM}', 'B', 'Proprietorship'),
                ('{FOREIGN_CLIENT}', '{OTHER_FIRM}', 'C', 'Proprietorship');
            INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Cust'),
                ('{OTHER_CUSTOMER}', '{FIRM}', '{OTHER_CLIENT}', 'Cust B'), ('{FOREIGN_CUSTOMER}', '{OTHER_FIRM}', '{FOREIGN_CLIENT}', 'Cust C');
            INSERT INTO vendors (id, firm_id, client_id, name) VALUES ('{VENDOR}', '{FIRM}', '{CLIENT}', 'Vend'),
                ('{OTHER_VENDOR}', '{FIRM}', '{OTHER_CLIENT}', 'Vend B'), ('{FOREIGN_VENDOR}', '{OTHER_FIRM}', '{FOREIGN_CLIENT}', 'Vend C');
            INSERT INTO chart_of_accounts (id, firm_id, account_code, account_name, account_type) VALUES
                ('{ACC_A}', '{FIRM}', '1100', 'Trade Receivables', 'Asset'), ('{ACC_B}', '{FIRM}', '4100', 'Sales', 'Revenue'),
                ('{FOREIGN_ACC_A}', '{OTHER_FIRM}', '1100', 'Trade Receivables', 'Asset'),
                ('{FOREIGN_ACC_B}', '{OTHER_FIRM}', '4100', 'Sales', 'Revenue');
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _id(prefix: str, n: int) -> str:
    return str(uuid.UUID(f"{prefix}5800000-0000-0000-0000-{n:012d}"))


def _lit(value) -> str:
    return "NULL" if value is None else f"'{value}'"


def _entry(dsn, n, entry_type, *, client=CLIENT, firm=FIRM, source_type=None, source_id=None, reversal_of=None, deleted=False,
           date="2025-06-10"):
    """A POSTED live entry with two balanced lines, made the way the database wants it made: a draft, its lines, then the posting."""
    eid = _id("b", n)
    a, b = (ACC_A, ACC_B) if firm == FIRM else (FOREIGN_ACC_A, FOREIGN_ACC_B)
    _ok(dsn, f"""
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no, narration, entry_type, source_type, source_id,
                                     reversal_of, deleted_at)
        VALUES ('{eid}', '{firm}', '{client}', '{date}', 'REF-{n}', 'entry {n}', '{entry_type}', {_lit(source_type)}, {_lit(source_id)},
                {_lit(reversal_of)}, {"now()" if deleted else "NULL"});
        INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
        VALUES ('{eid}', '{a}', 1000, 0), ('{eid}', '{b}', 0, 1000);
        UPDATE journal_entries SET is_posted = true, status = 'posted', posted_at = now() WHERE id = '{eid}';""")
    return eid


def _invoice(dsn, n, entry, *, client=CLIENT, firm=FIRM, customer=CUSTOMER):
    doc = _id("a", n)
    _ok(dsn, f"""INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, journal_entry_id)
                 VALUES ('{doc}', '{firm}', '{client}', '{customer}', 'INV-{n}', '2025-06-10', {_lit(entry)});""")
    return doc


def _bill(dsn, n, entry, *, client=CLIENT, firm=FIRM, vendor=VENDOR):
    doc = _id("a", n)
    _ok(dsn, f"""INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_no, bill_date, journal_entry_id)
                 VALUES ('{doc}', '{firm}', '{client}', '{vendor}', 'BILL-{n}', '2025-06-10', {_lit(entry)});""")
    return doc


def _payment(dsn, n, entry, *, client=CLIENT, firm=FIRM, vendor=VENDOR):
    doc = _id("a", n)
    _ok(dsn, f"""INSERT INTO purchase_payments (id, firm_id, client_id, vendor_id, payment_no, payment_date, journal_entry_id)
                 VALUES ('{doc}', '{firm}', '{client}', '{vendor}', 'PAY-{n}', '2025-06-10', {_lit(entry)});""")
    return doc


def _source(dsn, entry) -> tuple:
    row = _val(dsn, f"SELECT coalesce(source_type, ''), coalesce(source_id::text, '') FROM journal_entries WHERE id = '{entry}';")
    kind, doc = row.split("|")
    return (kind or None, doc or None)


def _everything_else(dsn) -> str:
    """A fingerprint of everything the migration must not move: every column of every entry except the two source columns and the
    row's own updated_at, every line, and the monthly balances the reports read."""
    return _val(dsn, """
        SELECT md5(coalesce((SELECT string_agg((to_jsonb(j) - 'source_type' - 'source_id' - 'updated_at')::text, '|' ORDER BY j.id)
                               FROM journal_entries j), '')
                 || coalesce((SELECT string_agg(to_jsonb(l)::text, '|' ORDER BY l.id) FROM journal_lines l), '')
                 || coalesce((SELECT string_agg(to_jsonb(b)::text, '|' ORDER BY b.id) FROM account_period_balances b), ''));""")


def _audit_rows(dsn, entry=None, source="migration 580") -> int:
    where = f"AND entity_id = '{entry}'" if entry else ""
    return int(_val(dsn, f"SELECT count(*) FROM audit_log WHERE entity_type = 'journal_entry' AND metadata->>'source' = '{source}' {where};"))


def test_an_entry_named_by_exactly_one_document_of_its_own_client_is_stamped(dsn):
    sale, purchase = _entry(dsn, 1, "Sales"), _entry(dsn, 2, "Purchase")
    invoice, bill = _invoice(dsn, 1, sale), _bill(dsn, 2, purchase)
    report = _run(dsn, MIGRATION)
    assert _source(dsn, sale) == ("sales_invoice", invoice)
    assert _source(dsn, purchase) == ("purchase_bill", bill)
    assert "1 sale, 1 purchase and 0 vendor-payment ledger entr(ies) now name their document and 0 reversal(s)" in report.stderr, report.stderr
    assert "0 sale, 0 purchase and 0 vendor-payment entr(ies) still name none" in report.stderr, report.stderr


def test_an_entry_the_rule_cannot_vouch_for_is_left_exactly_as_it_was(dsn):
    named_twice = _entry(dsn, 10, "Sales")
    _invoice(dsn, 10, named_twice)
    _invoice(dsn, 11, named_twice)                                       # two invoices claim it: which is its own would be a guess
    other_client = _entry(dsn, 12, "Sales", client=CLIENT)
    _invoice(dsn, 12, other_client, client=OTHER_CLIENT, customer=OTHER_CUSTOMER)  # a document of ANOTHER CLIENT of the firm
    other_firm = _entry(dsn, 13, "Sales")
    _invoice(dsn, 13, other_firm, client=FOREIGN_CLIENT, firm=OTHER_FIRM, customer=FOREIGN_CUSTOMER)  # a document of ANOTHER FIRM
    no_document = _entry(dsn, 14, "Sales")
    wrong_kind = _entry(dsn, 15, "Purchase")
    _invoice(dsn, 15, wrong_kind)                                        # a Purchase entry an INVOICE names: the type does not match
    deleted = _entry(dsn, 16, "Sales", deleted=True)
    _invoice(dsn, 16, deleted)                                           # a soft-deleted entry is not live
    other_type = _entry(dsn, 17, "Journal")
    _invoice(dsn, 17, other_type)                                        # a manual journal is not a sale
    already = _entry(dsn, 18, "Sales", source_type="sales_invoice", source_id=_id("a", 99))
    _invoice(dsn, 18, already)                                           # already stamped: never moved
    before = {e: _source(dsn, e) for e in (named_twice, other_client, other_firm, no_document, wrong_kind, deleted, other_type, already)}
    fingerprint = _everything_else(dsn)
    report = _run(dsn, MIGRATION)
    assert {e: _source(dsn, e) for e in before} == before
    assert _everything_else(dsn) == fingerprint
    assert _audit_rows(dsn) == 0
    assert "0 sale, 0 purchase and 0 vendor-payment ledger entr(ies) now name their document" in report.stderr, report.stderr


def test_a_documents_cost_journal_does_not_stop_its_sale_but_a_second_entry_of_the_same_type_does(dsn):
    sale = _entry(dsn, 20, "Sales")
    invoice = _invoice(dsn, 20, sale)
    cost = _entry(dsn, 21, "Journal", source_type="sales_invoice", source_id=invoice)     # the invoice's cost-of-goods entry
    duplicate_sale = _entry(dsn, 22, "Sales")
    duplicate_invoice = _invoice(dsn, 22, duplicate_sale)
    claimed = _entry(dsn, 23, "Sales", source_type="sales_invoice", source_id=duplicate_invoice)  # a live Sales entry already carries it
    _run(dsn, MIGRATION)
    assert _source(dsn, sale) == ("sales_invoice", invoice), "a cost journal sharing the invoice's source is the ordinary shape"
    assert _source(dsn, cost) == ("sales_invoice", invoice)
    assert _source(dsn, duplicate_sale) == (None, None), "which of two Sales entries is the invoice's would be a guess"
    assert _source(dsn, claimed) == ("sales_invoice", duplicate_invoice)


def test_only_the_two_source_columns_move_and_a_closed_year_is_no_obstacle(dsn):
    _ok(dsn, f"UPDATE firms SET locked_financial_years = ARRAY['2025-26'] WHERE id = '{FIRM}';")
    _ok(dsn, f"INSERT INTO client_year_locks (firm_id, client_id, financial_year) VALUES ('{FIRM}', '{CLIENT}', '2025-26');")
    sale = _entry(dsn, 30, "Sales", date="2025-06-10")
    purchase = _entry(dsn, 31, "Purchase", date="2025-09-02")
    reversal_target = _entry(dsn, 32, "Sales", date="2025-07-01")
    reversal = _entry(dsn, 33, "Sales", date="2025-07-02", reversal_of=reversal_target)
    invoice, bill, target_invoice = _invoice(dsn, 30, sale), _bill(dsn, 31, purchase), _invoice(dsn, 32, reversal_target)
    fingerprint = _everything_else(dsn)
    _run(dsn, MIGRATION)
    assert _everything_else(dsn) == fingerprint, "an amount, account, date, narration, reference, flag, line or monthly balance moved"
    assert _source(dsn, sale) == ("sales_invoice", invoice)
    assert _source(dsn, purchase) == ("purchase_bill", bill)
    assert _source(dsn, reversal_target) == ("sales_invoice", target_invoice)
    assert _source(dsn, reversal) == ("sales_invoice", target_invoice)
    assert int(_val(dsn, "SELECT count(*) FROM journal_entries WHERE is_posted AND status = 'posted';")) == 4


def test_the_vendor_payment_entry_that_names_its_kind_gets_the_payment_that_names_it(dsn):
    entry = _entry(dsn, 40, "Payment", source_type="purchase_payment")
    payment = _payment(dsn, 40, entry)
    ambiguous = _entry(dsn, 41, "Payment", source_type="purchase_payment")
    _payment(dsn, 41, ambiguous)
    _payment(dsn, 42, ambiguous)                                        # two payments claim it
    foreign = _entry(dsn, 43, "Payment", source_type="purchase_payment")
    _payment(dsn, 43, foreign, client=OTHER_CLIENT, vendor=OTHER_VENDOR)  # a payment of another client of the firm
    orphan = _entry(dsn, 44, "Payment", source_type="purchase_payment")   # no payment names it
    report = _run(dsn, MIGRATION)
    assert _source(dsn, entry) == ("purchase_payment", payment), "the kind it already had stays and the id arrives"
    for left in (ambiguous, foreign, orphan):
        assert _source(dsn, left) == ("purchase_payment", None)
    assert "0 sale, 0 purchase and 1 vendor-payment ledger entr(ies) now name their document" in report.stderr, report.stderr
    assert "0 sale, 0 purchase and 3 vendor-payment entr(ies) still name none" in report.stderr, report.stderr


def test_a_reversal_takes_its_originals_source_and_a_reversal_of_a_reversal_follows(dsn):
    original = _entry(dsn, 50, "Purchase")
    bill = _bill(dsn, 50, original)
    first = _entry(dsn, 51, "Purchase", reversal_of=original)
    second = _entry(dsn, 52, "Purchase", reversal_of=first)                # the reversal of the reversal
    unvouched = _entry(dsn, 53, "Purchase")                                # nothing names it, so its reversal has nothing to take
    its_reversal = _entry(dsn, 54, "Purchase", reversal_of=unvouched)
    pay_entry = _entry(dsn, 55, "Payment", source_type="purchase_payment")
    payment = _payment(dsn, 55, pay_entry)
    pay_reversal = _entry(dsn, 56, "Payment", source_type="purchase_payment", reversal_of=pay_entry)  # kind already set, id missing
    foreign_original = _entry(dsn, 57, "Sales", source_type="sales_invoice", source_id=_id("a", 98))
    cross_client = _entry(dsn, 58, "Sales", client=OTHER_CLIENT, reversal_of=foreign_original)  # a reversal naming another client's entry
    report = _run(dsn, MIGRATION)
    assert _source(dsn, first) == ("purchase_bill", bill)
    assert _source(dsn, second) == ("purchase_bill", bill)
    assert _source(dsn, unvouched) == (None, None) and _source(dsn, its_reversal) == (None, None)
    assert _source(dsn, pay_reversal) == ("purchase_payment", payment)
    assert _source(dsn, cross_client) == (None, None), "a reversal never takes a source across clients"
    assert "1 purchase and 1 vendor-payment ledger entr(ies) now name their document and 3 reversal(s)" in report.stderr, report.stderr


def test_every_stamped_entry_has_exactly_one_audit_row_that_says_what_changed(dsn):
    sale = _entry(dsn, 60, "Sales")
    invoice = _invoice(dsn, 60, sale)
    reversal = _entry(dsn, 61, "Sales", reversal_of=sale)
    pay_entry = _entry(dsn, 62, "Payment", source_type="purchase_payment")
    payment = _payment(dsn, 62, pay_entry)
    untouched = _entry(dsn, 63, "Sales")
    _run(dsn, MIGRATION)
    assert [_audit_rows(dsn, e) for e in (sale, reversal, pay_entry, untouched)] == [1, 1, 1, 0]
    row = _val(dsn, f"""SELECT firm_id::text || '|' || action || '|' || old_data::text || '|' || new_data::text || '|' || (metadata->>'step')
                          FROM audit_log WHERE entity_id = '{sale}' AND metadata->>'source' = 'migration 580';""")
    assert row == f'{FIRM}|update|{{"source_id": null, "source_type": null}}|{{"source_id": "{invoice}", "source_type": "sales_invoice"}}|document', row
    pay = _val(dsn, f"SELECT old_data::text || '|' || new_data::text FROM audit_log WHERE entity_id = '{pay_entry}' AND metadata->>'source' = 'migration 580';")
    assert pay == (f'{{"source_id": null, "source_type": "purchase_payment"}}|'
                   f'{{"source_id": "{payment}", "source_type": "purchase_payment"}}'), pay
    assert _val(dsn, f"SELECT metadata->>'step' FROM audit_log WHERE entity_id = '{reversal}' AND metadata->>'source' = 'migration 580';") == "reversal"


def test_a_second_run_changes_nothing_and_writes_nothing(dsn):
    sale = _entry(dsn, 70, "Sales")
    _invoice(dsn, 70, sale)
    _entry(dsn, 71, "Sales", reversal_of=sale)
    first = _run(dsn, MIGRATION)
    stamped, logged = _val(dsn, "SELECT string_agg(coalesce(source_id::text, '-'), ',' ORDER BY id) FROM journal_entries;"), _audit_rows(dsn)
    second = _run(dsn, MIGRATION)
    assert _val(dsn, "SELECT string_agg(coalesce(source_id::text, '-'), ',' ORDER BY id) FROM journal_entries;") == stamped
    assert _audit_rows(dsn) == logged == 2
    assert "1 sale, 0 purchase" in first.stderr and "0 sale, 0 purchase and 0 vendor-payment ledger entr(ies) now name their document and 0 reversal(s)" in second.stderr


def test_the_file_clears_the_edit_allowance_itself_before_it_ends_and_a_posted_entry_stays_closed_to_a_direct_edit(dsn, tmp_path):
    """The setting is transaction-local, so after COMMIT it is off whether or not the file cleared it. To prove the FILE clears it, the
    final COMMIT is swapped for a probe that runs while the transaction is still open: with the clear line deleted the probe reads true."""
    sale = _entry(dsn, 80, "Sales")
    _invoice(dsn, 80, sale)
    text = MIGRATION.read_text(encoding="utf-8")
    assert text.rstrip().endswith("COMMIT;")
    probe = tmp_path / "probe.sql"
    probe.write_text(text.rstrip()[: -len("COMMIT;")] + "SELECT 'allowance_on_before_commit=' || public.journal_edit_in_progress();\nROLLBACK;\n")
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", str(probe)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "allowance_on_before_commit=false" in r.stdout, r.stdout
    assert _source(dsn, sale) == (None, None), "the probe rolled back"
    # after the real run an ordinary edit of a posted entry is refused, exactly as before
    _run(dsn, MIGRATION)
    edit = _psql(dsn, f"UPDATE journal_entries SET narration = 'edited' WHERE id = '{sale}';")
    assert edit.returncode != 0 and "Cannot modify a posted journal entry" in edit.stderr, edit.stderr
    assert _val(dsn, f"SELECT narration FROM journal_entries WHERE id = '{sale}';") == "entry 80"


def test_the_customer_wise_breakdown_attributes_the_stamped_entries_to_their_customer(dsn):
    """The point of the whole file: party_ledger_as_at reads the party through source_id, and before the stamp the entry was unattributed."""
    sale = _entry(dsn, 90, "Sales")
    _invoice(dsn, 90, sale)

    def breakdown() -> str:
        return _val(dsn, f"SELECT public.party_ledger_as_at('{FIRM}', '{CLIENT}', '{ACC_A}', '2026-03-31')::text;")
    assert '"Cust"' not in breakdown()
    _run(dsn, MIGRATION)
    assert '"Cust"' in breakdown(), breakdown()


def test_the_rollback_undoes_exactly_the_entries_the_migration_named_and_only_while_they_are_unchanged(dsn):
    sale = _entry(dsn, 100, "Sales")
    invoice = _invoice(dsn, 100, sale)
    pay_entry = _entry(dsn, 101, "Payment", source_type="purchase_payment")
    _payment(dsn, 101, pay_entry)
    reversal = _entry(dsn, 102, "Sales", reversal_of=sale)
    by_the_kernel = _entry(dsn, 103, "Sales", source_type="sales_invoice", source_id=_id("a", 97))  # stamped before, not by the file
    moved_since = _entry(dsn, 104, "Sales")
    moved_invoice = _invoice(dsn, 104, moved_since)
    fingerprint = _everything_else(dsn)
    _run(dsn, MIGRATION)
    assert _source(dsn, sale) == ("sales_invoice", invoice)
    # an entry the file stamped that something else has since pointed elsewhere is not the rollback's to touch
    _ok(dsn, f"SELECT set_config('app.journal_edit', 'on', false); UPDATE journal_entries SET source_id = '{_id('a', 96)}' WHERE id = '{moved_since}';")
    report = _run(dsn, ROLLBACK)
    assert _source(dsn, sale) == (None, None)
    assert _source(dsn, reversal) == (None, None)
    assert _source(dsn, pay_entry) == ("purchase_payment", None), "the payment entry's kind was always there and stays"
    assert _source(dsn, by_the_kernel) == ("sales_invoice", _id("a", 97)), "an entry the file did not stamp is not touched"
    assert _source(dsn, moved_since) == ("sales_invoice", _id("a", 96)), "an entry changed since the file is left as it now is"
    assert "3 ledger entr(ies) are back" in report.stderr, report.stderr
    assert _everything_else(dsn) == fingerprint
    assert _audit_rows(dsn, sale, source="migration 580 rollback") == 1
    again = _run(dsn, ROLLBACK)
    assert "0 ledger entr(ies) are back" in again.stderr, again.stderr
    assert moved_invoice  # (kept for the reader: the invoice that named the moved entry)
    # and the file can be applied again after a rollback, with the same result
    _run(dsn, MIGRATION)
    assert _source(dsn, sale) == ("sales_invoice", invoice)
    assert _source(dsn, reversal) == ("sales_invoice", invoice)


def test_the_purchase_side_obeys_the_same_refusals_as_the_sales_side(dsn):
    named_twice = _entry(dsn, 110, "Purchase")
    _bill(dsn, 110, named_twice)
    _bill(dsn, 111, named_twice)                                          # two bills claim it
    other_client = _entry(dsn, 112, "Purchase")
    _bill(dsn, 112, other_client, client=OTHER_CLIENT, vendor=OTHER_VENDOR)  # a bill of another client of the firm
    other_firm = _entry(dsn, 113, "Purchase")
    _bill(dsn, 113, other_firm, client=FOREIGN_CLIENT, firm=OTHER_FIRM, vendor=FOREIGN_VENDOR)  # a bill of another firm
    deleted = _entry(dsn, 114, "Purchase", deleted=True)
    _bill(dsn, 114, deleted)
    sale_named_by_a_bill = _entry(dsn, 115, "Sales")
    _bill(dsn, 115, sale_named_by_a_bill)                                 # a Sales entry only a BILL names: the type does not match
    already = _entry(dsn, 116, "Purchase", source_type="purchase_bill", source_id=_id("a", 95))
    _bill(dsn, 116, already)
    second = _entry(dsn, 117, "Purchase")
    second_bill = _bill(dsn, 117, second)
    claimed = _entry(dsn, 118, "Purchase", source_type="purchase_bill", source_id=second_bill)  # a live Purchase entry already carries it
    own_plus_foreign = _entry(dsn, 119, "Purchase")
    own_bill = _bill(dsn, 119, own_plus_foreign)
    _bill(dsn, 120, own_plus_foreign, client=OTHER_CLIENT, vendor=OTHER_VENDOR)  # a foreign claim is ignored, never followed
    left = (named_twice, other_client, other_firm, deleted, sale_named_by_a_bill, second)
    before = {e: _source(dsn, e) for e in left}
    fingerprint = _everything_else(dsn)
    _run(dsn, MIGRATION)
    assert {e: _source(dsn, e) for e in left} == before and all(v == (None, None) for v in before.values())
    assert _source(dsn, already) == ("purchase_bill", _id("a", 95)) and _source(dsn, claimed) == ("purchase_bill", second_bill)
    assert _source(dsn, own_plus_foreign) == ("purchase_bill", own_bill), "exactly one document of its OWN firm and client names it"
    assert _everything_else(dsn) == fingerprint


def test_the_payment_step_leaves_an_entry_another_live_payment_entry_already_carries(dsn):
    entry = _entry(dsn, 130, "Payment", source_type="purchase_payment")
    payment = _payment(dsn, 130, entry)
    _entry(dsn, 131, "Payment", source_type="purchase_payment", source_id=payment)   # a second live Payment entry carries the payment
    _run(dsn, MIGRATION)
    assert _source(dsn, entry) == ("purchase_payment", None)


def test_step_three_leaves_a_reversal_it_cannot_vouch_for(dsn):
    original = _entry(dsn, 140, "Purchase")
    bill = _bill(dsn, 140, original)
    conflicting = _entry(dsn, 141, "Purchase", source_type="receipt", reversal_of=original)   # its own kind differs from its original's
    soft_deleted = _entry(dsn, 142, "Purchase", reversal_of=original, deleted=True)
    manual = _entry(dsn, 143, "Journal", source_type="manual")                          # an original with a kind and no id
    of_manual = _entry(dsn, 144, "Journal", source_type="manual", reversal_of=manual)
    unkinded = _entry(dsn, 145, "Journal")
    of_unkinded = _entry(dsn, 146, "Journal", reversal_of=unkinded)
    fine = _entry(dsn, 147, "Purchase", reversal_of=original)
    _run(dsn, MIGRATION)
    assert _source(dsn, conflicting) == ("receipt", None)
    assert _source(dsn, soft_deleted) == (None, None)
    assert _source(dsn, of_manual) == ("manual", None) and _source(dsn, of_unkinded) == (None, None)
    assert _source(dsn, fine) == ("purchase_bill", bill)


def test_the_files_say_what_they_do_not_do():
    text = MIGRATION.read_text(encoding="utf-8")
    assert "set_config('app.journal_edit', 'on', true)" in text and "set_config('app.journal_edit', '', true)" in text
    assert "audit_log" in text, "a migration has no signed-in person, so the file must write the edit-log rows itself"
    assert "RAISE WARNING" in text
    for forbidden in ("DELETE FROM", "DROP TABLE", "TRUNCATE", "ALTER TABLE", "debit_paise =", "credit_paise ="):
        assert forbidden not in text, forbidden
