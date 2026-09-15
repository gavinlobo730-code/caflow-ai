"""ACC-14 — an opening balance is made of documents, and they must not be
declared twice.

Two rules, and the second is the dangerous one.

    1. The documents behind a party's opening balance have to ADD UP to it, or
       the ageing schedule stops footing to its own control account. Where they
       do not, the difference is named.

    2. A carried-over document is not this client's supply, purchase, credit or
       withholding. Every reader that feeds a statutory return has to exclude it
       — and a reader that does NOT is silently wrong: it declares an outward
       supply twice, claims an input credit twice, or reverses credit the
       client's own ledger never took. `EXCLUDES` below is the rule, stated as
       a list a new reader has to join rather than as a spelling of one query.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import re

import pytest

from domain.accounting import opening_documents as od

API = pathlib.Path(__file__).resolve().parent.parent
MIGRATION = API / "migrations" / "391_an_opening_balance_is_made_of_documents.sql"
ROLLBACK = API / "migrations" / "391_an_opening_balance_is_made_of_documents_rollback.sql"


# ── The rule ────────────────────────────────────────────────────────────────

def test_a_document_needs_a_party_a_number_a_date_and_an_amount():
    r = od.problem_with(kind=od.RECEIVABLE, party_id="c1", document_no="INV/22",
                        document_date="2026-03-20", due_date="2026-04-19",
                        outstanding_paise=250000)
    assert r.ok


@pytest.mark.parametrize("field, value", [
    ("party_id", ""),
    ("document_no", "  "),
    ("document_date", None),
    ("outstanding_paise", 0),
])
def test_each_missing_particular_is_refused_with_its_own_reason(field, value):
    kw = dict(kind=od.RECEIVABLE, party_id="c1", document_no="INV/22",
              document_date="2026-03-20", due_date=None,
              outstanding_paise=250000)
    kw[field] = value
    r = od.problem_with(**kw)
    assert not r.ok
    assert len(r.reasons) == 1, r.reasons


def test_a_settled_document_is_not_part_of_an_opening_balance():
    r = od.problem_with(kind=od.PAYABLE, party_id="v1", document_no="B/9",
                        document_date="2026-03-20", due_date=None,
                        outstanding_paise=-1)
    assert not r.ok
    assert "STILL OWED" in " ".join(r.reasons)


def test_a_due_date_before_the_document_date_is_refused():
    r = od.problem_with(kind=od.RECEIVABLE, party_id="c1", document_no="INV/22",
                        document_date="2026-03-20", due_date="2026-03-01",
                        outstanding_paise=1)
    assert not r.ok
    assert any("before the document date" in x for x in r.reasons)


def test_the_OLD_systems_number_is_NOT_checked_against_rule_46b():
    """It is the number somebody else issued. Refusing a series this product
    never generated would make a migration impossible for the clients who most
    need one — the same reasoning `purchase_bills.bill_no` already carries."""
    src = inspect.getsource(od.problem_with)
    assert "invoice_series" not in src
    assert "46(b)" not in src or "NOT a Rule 46(b) check" in src
    # Sixteen characters, a slash, a hash — none of it is refused here.
    for no in ["A" * 40, "INV#2025/0001", "  2025-26/00042  "]:
        r = od.problem_with(kind=od.RECEIVABLE, party_id="c1", document_no=no,
                            document_date="2026-03-20", due_date=None,
                            outstanding_paise=1)
        assert r.ok, no


# ── The row it writes ───────────────────────────────────────────────────────

def _row(kind=od.RECEIVABLE, amount=250000):
    return od.row_for(kind=kind, firm_id="F1", client_id="C1", party_id="P1",
                      document_no="INV/22", document_date="2026-03-20",
                      due_date="2026-04-19", outstanding_paise=amount)


def test_an_opening_document_declares_NO_TAX():
    """The tax was charged, collected and declared where the document was
    issued. A figure here is one this client's returns must never repeat."""
    for kind in od.KINDS:
        row = _row(kind)
        for field in od.NO_TAX_FIELDS:
            assert row[field] == 0, (kind, field)


def test_an_opening_bill_withholds_NOTHING():
    """Any TDS on it was deducted, deposited and reported on a statement filed
    from the old system. This is also what keeps it out of the 26Q build, whose
    own read is `.gt("tds_paise", 0)`."""
    row = _row(od.PAYABLE)
    assert row["tds_paise"] == 0
    assert row["tds_rate_bps"] == 0
    assert "tds_section" not in row


def test_the_PAYABLE_side_writes_net_payable_paise_not_just_total():
    """Migration 278 generates `purchase_bills.outstanding_paise` from
    net_payable_paise, while the invoice's comes from total_paise. Writing only
    the total would leave every opening bill outstanding at ZERO — invisible to
    AP ageing and to the Schedule III payables note, which is the whole
    feature."""
    row = _row(od.PAYABLE, amount=777700)
    assert row["net_payable_paise"] == 777700
    assert row["total_paise"] == 777700


def test_both_kinds_are_written_OPEN_not_draft():
    """Every ageing reader filters the dead statuses out; a draft would be
    excluded from the very schedules this exists to populate."""
    assert _row(od.RECEIVABLE)["status"] == "issued"
    assert _row(od.PAYABLE)["status"] == "received"


def test_the_flag_is_on_both_kinds():
    for kind in od.KINDS:
        assert _row(kind)["is_opening"] is True


# ── The reconciliation ──────────────────────────────────────────────────────

def _party(pid, name, opening):
    return {"id": pid, "name": name, "opening_balance_paise": opening}


def _doc(pid, amount, kind=od.RECEIVABLE):
    return {od.PARTY_COLUMN[kind]: pid, "outstanding_paise": amount}


def test_a_party_whose_documents_add_up_is_not_complained_about():
    rows = od.reconcile([_party("p1", "Acme", 100000)],
                        [_doc("p1", 60000), _doc("p1", 40000)],
                        kind=od.RECEIVABLE)
    assert len(rows) == 1
    assert rows[0].agrees and rows[0].sentence is None
    assert rows[0].document_count == 2


def test_a_balance_with_no_documents_is_named_as_ageing_to_nothing():
    rows = od.reconcile([_party("p1", "Acme", 100000)], [], kind=od.RECEIVABLE)
    assert not rows[0].agrees
    assert rows[0].difference_paise == 100000
    assert "ageing bucket" in rows[0].sentence


def test_documents_EXCEEDING_the_balance_are_named_the_other_way_round():
    rows = od.reconcile([_party("p1", "Acme", 100000)],
                        [_doc("p1", 150000)], kind=od.RECEIVABLE)
    assert rows[0].difference_paise == -50000
    assert "MORE than" in rows[0].sentence


def test_a_party_with_neither_is_not_reported():
    assert od.reconcile([_party("p1", "Acme", 0)], [], kind=od.RECEIVABLE) == []


def test_a_document_against_an_unknown_party_is_reported_not_dropped():
    """The amount is in the ageing schedule either way."""
    rows = od.reconcile([], [_doc("ghost", 500, od.PAYABLE)], kind=od.PAYABLE)
    assert len(rows) == 1 and rows[0].documents_paise == 500


def test_the_disagreements_sort_FIRST():
    rows = od.reconcile(
        [_party("a", "Agrees", 100), _party("b", "Broken", 100)],
        [_doc("a", 100)], kind=od.RECEIVABLE)
    assert [r.party_id for r in rows] == ["b", "a"]


# ── The exclusion, stated as the rule ───────────────────────────────────────

#: Every module that reads `client_sales_invoices` or `purchase_bills` AND
#: feeds a statutory return, a statutory document or a statutory computation.
#: Each must exclude carried-over documents, and each is here with WHY — so a
#: reader added later has to decide rather than inherit.
EXCLUDES: dict[str, str] = {
    "services/gst_return_service.py":
        "GSTR-1 and GSTR-3B: declaring a carried-over supply again pays the tax "
        "twice, and claiming its credit again doubles Table 4(A)",
    "services/gst_2b_reconciliation_service.py":
        "an opening bill has no 2B counterpart and never will, so it would "
        "report as 'missing in 2B' every month",
    "services/itc_reversal_service.py":
        "Rule 37's 180 days never started here — the credit was availed in the "
        "old system",
    "services/msme_43bh_service.py":
        "s.43B(h) disallows a deduction claimed in THIS previous year",
    "services/invoice_pdf_service.py":
        "a tax invoice for a supply this client did not invoice",
    "services/sales_numbering_service.py":
        "Rule 46(b)'s consecutive series is the one kept HERE",
    "routers/credit_notes.py":
        "a s.34 note adjusts tax declared in the old system",
    "routers/sales_debit_notes.py": "the same, on the debit side",
    "routers/purchase_credit_notes.py": "the same, on the purchase side",
    "routers/debit_notes.py": "the same, on the purchase debit side",
}

#: Readers that are CORRECT to see a carried-over document, recorded so the
#: absence of the filter reads as a decision rather than an oversight.
INCLUDES_ON_PURPOSE: dict[str, str] = {
    "services/customer_statement_service.py": "AR ageing — the whole point",
    "services/vendor_statement_service.py": "AP ageing — the whole point",
    "services/ageing_schedule_service.py": "the Schedule III ageing note",
    "services/collections_service.py": "an opening invoice is still collectable",
    "services/receipt_service.py": "a receipt settles one, unchanged",
    "services/purchase_payment_service.py": "a payment settles one, unchanged",
    "domain/currency/fx_revaluation_service.py":
        "a foreign-currency opening document is revalued like any other",
}


@pytest.mark.parametrize("module", sorted(EXCLUDES))
def test_every_statutory_reader_excludes_a_carried_over_document(module):
    src = (API / module).read_text(encoding="utf-8")
    assert "opening_documents" in src, (
        f"{module} reads a document table and feeds a statutory output, so it "
        f"has to ask `domain/accounting/opening_documents` whether the document "
        f"was carried over. {EXCLUDES[module]}.")
    assert ("carried_over" in src), module


@pytest.mark.parametrize("module", sorted(EXCLUDES))
def test_a_narrow_projection_carries_the_key_it_filters_on(module):
    """`carried_over` reads `is_opening` OFF THE ROW, so a select that omits it
    reads every row as ordinary and the filter is a silent no-op.

    Only the narrow projections need the column named: a `select("*")` already
    carries it. So the check is — if this module filters at all, every
    `.select("…")` it makes on one of the two document tables either is `*` or
    names `is_opening`."""
    tree = ast.parse((API / module).read_text(encoding="utf-8"))
    tables = {"client_sales_invoices", "purchase_bills"}
    bad: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "select"):
            continue
        inner = node.func.value
        if not (isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "table"
                and inner.args and isinstance(inner.args[0], ast.Constant)
                and inner.args[0].value in tables):
            continue
        parts = [a.value for a in node.args
                 if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        # A JoinedStr or a name is unreadable here; only judge literal ones.
        if not parts:
            continue
        projection = " ".join(parts)
        if "*" in projection or "is_opening" in projection:
            continue
        bad.append(f"line {node.lineno}: {projection[:70]}")
    # Not every select in these modules is on the filtered path — the ones that
    # are not are listed with their line, so a real miss is visible rather than
    # buried in a count.
    assert not bad or module in _NARROW_SELECTS_THAT_ARE_NOT_ON_THE_FILTERED_PATH, (
        f"{module} selects from a document table without `is_opening`, and the "
        f"exclusion reads that key off the row:\n  " + "\n  ".join(bad))


#: Modules where SOME select on a document table legitimately omits the key —
#: a settlement update, a status read, a column-specific probe. Each is here so
#: the list above cannot be widened by accident.
_NARROW_SELECTS_THAT_ARE_NOT_ON_THE_FILTERED_PATH = {
    # The §34 note routers read the parent for its own particulars and DO carry
    # `is_opening` on the read that refuses; their other selects are the CAS
    # settlement loops and the issue-time re-reads.
    "routers/credit_notes.py",
    "routers/sales_debit_notes.py",
    "routers/purchase_credit_notes.py",
    "routers/debit_notes.py",
    # The PDF reads `select("*", customers(…))`, which carries it; this entry
    # covers the small status probes beside it.
    "services/invoice_pdf_service.py",
    # gst_return_service's own document fetches are `select("*")`; the entry
    # covers its s.34 note parent index, which reads four named columns and is
    # keyed on ids that came from an already-filtered set.
    "services/gst_return_service.py",
}


@pytest.mark.parametrize("module", sorted(INCLUDES_ON_PURPOSE))
def test_a_reader_that_SHOULD_see_one_is_recorded_rather_than_silent(module):
    """The list exists so the absence of a filter is a decision. The test is
    that the file is still there — a module renamed or deleted has to re-take
    the decision rather than drop off the record."""
    assert (API / module).exists(), (
        f"{module} was listed as deliberately seeing carried-over documents "
        f"({INCLUDES_ON_PURPOSE[module]}) and no longer exists. Re-take the "
        f"decision for whatever replaced it.")


def test_the_exclusion_reads_an_ABSENT_key_as_an_ORDINARY_document():
    """The safe direction. A row that predates migration 391, or an in-memory
    double that never carried the column, must NOT be dropped from a return:
    silently omitting a real supply is the worse of the two mistakes, and the
    other one needs the flag present and true."""
    assert od.without_carried_over([{"id": 1}]) == [{"id": 1}]
    assert od.without_carried_over([{"id": 1, "is_opening": None}]) == [{"id": 1, "is_opening": None}]
    assert od.without_carried_over([{"id": 1, "is_opening": True}]) == []


def test_the_section_34_refusal_is_one_sentence_said_once():
    for kind in od.KINDS:
        s = od.note_refusal(kind)
        assert "carried over" in s and "section 34" in s
    assert od.note_refusal(od.RECEIVABLE) != od.note_refusal(od.PAYABLE), (
        "the noun differs — a CA raising a note against a BILL should not be "
        "told about an invoice")


def test_the_section_194_aggregate_is_REFUSED_and_says_why():
    """An opening bill contributes nothing to the FY aggregate, and cannot: the
    aggregate is measured on what was CREDITED during the year, and a bill
    credited and settled before the migration counts toward it while not being
    carried over at all."""
    assert "credited or paid" in od.SECTION_194_AGGREGATE_IS_NOT_CARRIED
    assert _row(od.PAYABLE)["taxable_amount_paise"] == 0


# ── The migration ───────────────────────────────────────────────────────────

def _sql_only(text: str) -> str:
    return "\n".join(re.sub(r"--.*$", "", line) for line in text.splitlines())


def test_the_migration_adds_the_flag_to_both_tables_defaulting_to_false():
    sql = _sql_only(MIGRATION.read_text())
    for table in ("client_sales_invoices", "purchase_bills"):
        assert f"ALTER TABLE public.{table}" in sql
    assert sql.count("is_opening BOOLEAN NOT NULL DEFAULT FALSE") == 2, (
        "DEFAULT FALSE on both, so every existing document stays an ordinary "
        "one and nothing already filed changes")


def test_the_rollback_REFUSES_while_an_opening_document_exists():
    """Dropping the column would not delete those rows — it would turn each
    into an ORDINARY invoice or bill, whose supply the next GSTR-1 declares and
    whose credit Table 4(A) claims."""
    # The STATEMENTS, not the header: the header explains at length what a
    # silent rollback would cost, and a guard that greps the whole file passes
    # on a commit that keeps the paragraph and drops the refusal.
    sql = _sql_only(ROLLBACK.read_text())
    assert "RAISE EXCEPTION" in sql
    assert "Refusing to roll back 391" in sql
    assert "second time" in sql


# ── The service, run rather than read ───────────────────────────────────────

class _Q:
    def __init__(self, store, table):
        self._store = store
        self._table = table
        self._rows = list(store.get(table, []))

    def select(self, *a, **k): return self
    def insert(self, payload):
        rows = payload if isinstance(payload, list) else [payload]
        for r in rows:
            r.setdefault("id", f"{self._table}-{len(self._store.setdefault(self._table, [] )) + 1}")
            r.setdefault("paid_paise", 0)
            # Migration 278's generated column, transcribed: the invoice's is
            # from total_paise and the bill's from net_payable_paise.
            base = (int(r.get("net_payable_paise") or 0)
                    if self._table == "purchase_bills"
                    else int(r.get("total_paise") or 0))
            r["outstanding_paise"] = base - int(r.get("paid_paise") or 0)
            self._store.setdefault(self._table, []).append(r)
        self._rows = rows
        return self

    def update(self, patch):
        for r in self._rows:
            r.update(patch)
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def is_(self, col, _null):
        self._rows = [r for r in self._rows if r.get(col) is None]
        return self

    def gt(self, col, val):
        self._rows = [r for r in self._rows if str(r.get(col)) > str(val)]
        return self

    def in_(self, col, vals):
        self._rows = [r for r in self._rows if r.get(col) in list(vals)]
        return self

    def gte(self, col, val):
        self._rows = [r for r in self._rows if str(r.get(col) or "") >= str(val)]
        return self

    def lte(self, col, val):
        self._rows = [r for r in self._rows if str(r.get(col) or "") <= str(val)]
        return self

    def order(self, col, **k):
        self._rows.sort(key=lambda r: str(r.get(col)))
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _FakeDB:
    def __init__(self, **tables):
        self.store = tables

    def table(self, name):
        return _Q(self.store, name)


def _db():
    return _FakeDB(
        clients=[{"id": "C1", "firm_id": "F1"}],
        customers=[{"id": "P1", "firm_id": "F1", "client_id": "C1",
                    "name": "Acme", "opening_balance_paise": 100000}],
        vendors=[{"id": "V1", "firm_id": "F1", "client_id": "C1",
                  "name": "Bolt", "opening_balance_paise": 50000}],
        client_sales_invoices=[],
        purchase_bills=[],
    )


def test_the_service_records_a_document_and_it_is_OUTSTANDING_in_full():
    from services import opening_document_service as svc
    db = _db()
    out = svc.create(db, "F1", "C1", kind=od.RECEIVABLE, party_id="P1",
                     document_no="INV/22", document_date="2026-03-20",
                     due_date="2026-04-19", outstanding_paise=60000)
    assert out["outstanding_paise"] == 60000
    assert out["party_name"] == "Acme"
    row = db.store["client_sales_invoices"][0]
    assert row["is_opening"] is True and row["total_gst_paise"] == 0


def test_a_PAYABLE_is_outstanding_in_full_too_which_needs_net_payable_paise():
    from services import opening_document_service as svc
    db = _db()
    svc.create(db, "F1", "C1", kind=od.PAYABLE, party_id="V1",
               document_no="B/9", document_date="2026-03-20", due_date=None,
               outstanding_paise=50000)
    assert db.store["purchase_bills"][0]["outstanding_paise"] == 50000


def test_a_document_cannot_be_filed_against_ANOTHER_clients_party():
    """`client_sales_invoices.customer_id` is a bare FK to `customers(id)`, so
    without the scope check a document could be filed against a stranger's
    customer and then age on this client's schedule."""
    from fastapi import HTTPException
    from services import opening_document_service as svc
    db = _db()
    db.store["customers"].append({"id": "OTHER", "firm_id": "F1",
                                  "client_id": "C9", "name": "Not ours",
                                  "opening_balance_paise": 0})
    with pytest.raises(HTTPException) as e:
        svc.create(db, "F1", "C1", kind=od.RECEIVABLE, party_id="OTHER",
                   document_no="X", document_date="2026-03-20", due_date=None,
                   outstanding_paise=1)
    assert e.value.status_code == 404


def test_the_listing_carries_the_reconciliation_beside_the_documents():
    """A list of documents without the figure they are supposed to add up to is
    what lets an ageing schedule quietly stop footing to its control account."""
    from services import opening_document_service as svc
    db = _db()
    svc.create(db, "F1", "C1", kind=od.RECEIVABLE, party_id="P1",
               document_no="INV/22", document_date="2026-03-20",
               due_date=None, outstanding_paise=60000)
    out = svc.listing(db, "F1", "C1", od.RECEIVABLE)
    assert out["documents_paise"] == 60000
    assert out["opening_balance_paise"] == 100000
    assert out["unreconciled_parties"] == 1
    # 40,000 paise = ₹400.00 — the sentence spells rupees, which is the one
    # place a figure is formatted, because the sentence IS the answer.
    assert "₹400.00" in out["reconciliation"][0]["sentence"]

    svc.create(db, "F1", "C1", kind=od.RECEIVABLE, party_id="P1",
               document_no="INV/23", document_date="2026-03-25",
               due_date=None, outstanding_paise=40000)
    out = svc.listing(db, "F1", "C1", od.RECEIVABLE)
    assert out["unreconciled_parties"] == 0
    assert out["reconciliation"][0]["sentence"] is None


def test_a_document_SETTLED_AGAINST_cannot_be_removed():
    """The receipt that settled it has already relieved the control account;
    removing the document leaves that relief with nothing behind it."""
    from fastapi import HTTPException
    from services import opening_document_service as svc
    db = _db()
    svc.create(db, "F1", "C1", kind=od.RECEIVABLE, party_id="P1",
               document_no="INV/22", document_date="2026-03-20",
               due_date=None, outstanding_paise=60000)
    doc_id = db.store["client_sales_invoices"][0]["id"]
    db.store["client_sales_invoices"][0]["paid_paise"] = 1
    with pytest.raises(HTTPException) as e:
        svc.remove(db, "F1", "C1", kind=od.RECEIVABLE, document_id=doc_id)
    assert e.value.status_code == 409


def test_an_ORDINARY_invoice_can_never_be_removed_through_this_endpoint():
    """The check is on `is_opening`, so the delete cannot reach a real invoice
    however the id was obtained."""
    from fastapi import HTTPException
    from services import opening_document_service as svc
    db = _db()
    db.store["client_sales_invoices"].append({
        "id": "real", "firm_id": "F1", "client_id": "C1", "is_opening": False,
        "paid_paise": 0, "total_paise": 1000, "invoice_no": "INV/1",
        "deleted_at": None})
    with pytest.raises(HTTPException) as e:
        svc.remove(db, "F1", "C1", kind=od.RECEIVABLE, document_id="real")
    assert e.value.status_code == 404


# ── The exclusion, RUN rather than read ─────────────────────────────────────
#
# The source guard above says each module ASKS. These two run the ask. Both were
# added because a negative control passed: renaming the import in
# `gst_return_service`, and dropping the filter in `msme_43bh_service`, left
# every source assertion green while the return would have declared a
# carried-over supply and the s.43B(h) working would have added one back.


def _sales_db(**over):
    inv = {"id": "i1", "firm_id": "F1", "client_id": "C1", "status": "issued",
           "invoice_date": "2026-06-10", "total_paise": 118000,
           "taxable_amount_paise": 100000, "igst_paise": 18000,
           "is_opening": False}
    inv.update(over)
    return _FakeDB(client_sales_invoices=[inv])


def test_the_GST_RETURN_BUILD_drops_a_carried_over_invoice():
    from services import gst_return_service as svc
    ordinary = svc._posted_sales(_sales_db(), "F1", "C1", "2026-06-01", "2026-06-30")
    assert len(ordinary) == 1, "an ordinary invoice is still declared"
    carried = svc._posted_sales(_sales_db(is_opening=True), "F1", "C1",
                                "2026-06-01", "2026-06-30")
    assert carried == [], (
        "a carried-over invoice reached the outward supplies — its GST was "
        "declared in the system the client migrated from, so this return would "
        "pay the same tax a second time")


def test_the_GST_RETURN_BUILD_drops_a_carried_over_bill():
    from services import gst_return_service as svc
    bill = {"id": "b1", "firm_id": "F1", "client_id": "C1", "status": "received",
            "bill_date": "2026-06-10", "total_paise": 118000,
            "net_payable_paise": 118000, "igst_paise": 18000,
            "cancelled_at": None, "is_opening": False}
    db = _FakeDB(purchase_bills=[dict(bill)])
    assert len(svc._posted_bills(db, "F1", "C1", "2026-06-01", "2026-06-30")) == 1
    db = _FakeDB(purchase_bills=[dict(bill, is_opening=True)])
    assert svc._posted_bills(db, "F1", "C1", "2026-06-01", "2026-06-30") == [], (
        "a carried-over bill reached Table 4(A) — its credit was availed in the "
        "old system and GSTR-2B shows no such document")


def test_SECTION_43B_H_drops_a_carried_over_bill_and_NAMES_it():
    from services import msme_43bh_service as svc
    bill = {"id": "b1", "firm_id": "F1", "client_id": "C1", "status": "received",
            "bill_no": "OLD/9", "bill_date": "2025-06-10", "vendor_id": "V1",
            "total_paise": 118000, "taxable_amount_paise": 100000,
            "tds_paise": 0, "ineligible_itc_igst_paise": 0,
            "ineligible_itc_cgst_paise": 0, "ineligible_itc_sgst_paise": 0,
            "is_opening": True}
    db = _FakeDB(purchase_bills=[bill],
                 vendors=[{"id": "V1", "firm_id": "F1", "client_id": "C1",
                           "name": "Bolt", "msme_status": "micro",
                           "msmed_agreement_days": None}],
                 purchase_payment_allocations=[], purchase_payments=[],
                 fixed_assets=[])
    assert svc._bills(db, "F1", "C1") == [], (
        "the deduction was claimed in a year whose return was prepared "
        "elsewhere; adding it back here taxes the client on a deduction their "
        "own books never took")
    named = svc._carried_over_bills(db, "F1", "C1")
    assert [b["bill_no"] for b in named] == ["OLD/9"], (
        "and it has to be NAMED: an earlier year's disallowance actually PAID "
        "during this year comes back as a deduction, and nothing on the bill "
        "records whether it was disallowed")


# ── The OTHER double count ──────────────────────────────────────────────────

def test_an_account_opened_by_BOTH_mechanisms_is_reported():
    """The masters and the trial-balance import post into separate journal
    families that never reconcile against each other, so a bank balance entered
    on the bank master AND carried on an imported trial balance is posted twice
    — and the balance sheet is out by exactly it, silently."""
    out = od.double_openings({"bank": 500000}, {"bank": 500000},
                             {"bank": "HDFC Bank"})
    assert len(out) == 1
    assert "opened twice" in out[0].sentence
    assert "HDFC Bank" in out[0].sentence
    assert "₹5,000.00" in out[0].sentence


def test_an_account_in_only_ONE_family_is_not_reported():
    assert od.double_openings({"bank": 500000}, {"capital": 500000}) == []


def test_a_NET_ZERO_pair_is_not_cried_wolf_over():
    """The delta engine legitimately leaves a net-zero pair on an account whose
    master balance went to zero — the commonest correction there is."""
    assert od.double_openings({"ar": 0}, {"ar": 100}) == []
    assert od.double_openings({"ar": 100}, {"ar": 0}) == []


def test_NO_difference_is_offered_only_the_two_figures():
    """Which of the two is the mistake is the CA's answer. A single
    'difference' would read as a figure to post."""
    d = od.double_openings({"a": 100}, {"a": 300})[0]
    assert d.master_paise == 100 and d.trial_balance_paise == 300
    assert not hasattr(d, "difference_paise")


def test_the_service_reads_BOTH_journal_families_by_name():
    from services import opening_document_service as svc
    src = inspect.getsource(svc.double_openings)
    assert "MASTER_SOURCE" in src and "TRIAL_BALANCE_SOURCE" in src
    assert od.MASTER_SOURCE == "Opening"
    assert od.TRIAL_BALANCE_SOURCE == "TrialBalance", (
        "the trial-balance import posts under its own source_type on purpose — "
        "see its module header — and this comparison depends on that name")


def test_the_trial_balance_source_matches_what_the_importer_actually_posts():
    """Read off the importer rather than restated here: a guard that spells the
    string is a second copy of it."""
    from services import trial_balance_import_service as tbi
    assert od.TRIAL_BALANCE_SOURCE == tbi.TB_SOURCE
    from services import opening_balance_service as obs
    assert od.MASTER_SOURCE == obs.OPENING_SOURCE


def test_every_key_row_for_produces_IS_A_REAL_COLUMN():
    """The other end of the chain. Both inserts pass a row built by `row_for`,
    which the column scan cannot read (it resolves no variable names), so the
    budget in `test_backend_columns_exist_pg` carries two entries for them. This
    is what makes that safe: the keys are checked against production's own
    column list, which is the check the scan would have made."""
    from tests.production_types import _SCHEMA, known_table
    for kind in od.KINDS:
        table = od.TABLES[kind]
        if not known_table(table):
            pytest.skip(f"the production snapshot predates {table}")
        columns = set(_SCHEMA[table])
        extra = set(_row(kind)) - columns - {"is_opening"}
        assert not extra, (
            f"{table}: {sorted(extra)} are not columns in production. PostgREST "
            f"rejects the WHOLE insert with PGRST204, so nothing is written.")
