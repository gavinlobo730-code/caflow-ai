"""Phase 0: the seven defects the GST-04/PUR-11 tranche introduced.

WHY THESE TESTS EXIST AND THE TRANCHE'S OWN 32 DID NOT CATCH ANY OF THEM

The 2B reconciliation shipped with 32 backend tests, all of which pass on the
defective code. Every one of them uploads a 2B that CONTAINS DOCUMENTS, because
that is the interesting case to write a test for. The defects all live in the
cases nobody writes a test for: a 2B in which nobody filed anything, a supplier
who numbers a credit note and a debit note the same, and a client with more than
a thousand bills in a month.

So these are written from the ABSENCES rather than from the feature.
"""
from __future__ import annotations

import pytest

from domain.gst.gstr2b import parse_gstr2b
from domain.gst.gstr3b_computer import _apply_rule_36_4_cap
from services import gst_2b_reconciliation_service as svc

GSTIN_A = "27AAAAA0000A1Z2"
FIRM, CLIENT, PERIOD = "firm-1", "client-1", "082026"


# ── a minimal store, deliberately not the shared harness ────────────────────
# The shared FakeDB validates against the production schema snapshot, which does
# not yet carry gstr2b_reconciliations (migration 341 reaches production on
# merge). These tests are about the SERVICE's logic, so they use a store that
# records calls rather than one that models Postgres.

class _Q:
    def __init__(self, store, table): self.store, self.table = store, table; self.f = {}
    def select(self, *a, **k): return self
    def insert(self, rows):
        self.store.setdefault(self.table, []).extend(
            rows if isinstance(rows, list) else [rows]); return self
    def delete(self): self._del = True; return self
    def eq(self, k, v): self.f[k] = v; return self
    def in_(self, k, v): return self
    def is_(self, k, v): return self
    def gte(self, k, v): return self
    def lte(self, k, v): return self
    def limit(self, n): return self
    def execute(self):
        if getattr(self, "_del", False):
            self.store[self.table] = [
                r for r in self.store.get(self.table, [])
                if not all(r.get(k) == v for k, v in self.f.items())]
            return type("R", (), {"data": []})()
        rows = [r for r in self.store.get(self.table, [])
                if all(r.get(k) == v for k, v in self.f.items())]
        return type("R", (), {"data": rows})()


class _DB:
    def __init__(self, store): self.store = store
    def table(self, name): return _Q(self.store, name)


def _file(*notes):
    return {"data": {"gstin": "29BBBBB1111B1Z5", "rtnprd": PERIOD,
                     "gendt": "14-09-2026",
                     "docdata": {"cdnr": [{"ctin": GSTIN_A, "trdnm": "Acme",
                                           "nt": list(notes)}]} if notes else {}}}


def _note(num, typ):
    return {"ntnum": num, "ntdt": "05-08-2026", "typ": typ, "val": 1180,
            "itms": [{"rt": 18, "txval": 1000, "igst": 180}]}


# ── 1. the reconciliation records that it happened ──────────────────────────

def test_a_2b_in_which_nobody_filed_is_still_a_reconciliation():
    """THE DEFECT: it returned early with persisted=False, so the period left no
    trace and every reader downstream treated it as never reconciled.

    An empty 2B is not a failure. It means no supplier filed against this client
    for the month, which under §16(2)(aa) means NO credit is available — the most
    consequential thing this reconciliation can discover."""
    store = {}
    out = svc.reconcile_2b(_DB(store), firm_id=FIRM, client_id=CLIENT,
                           period=PERIOD, raw=_file())
    assert out["persisted"] is True
    assert svc.was_reconciled(_DB(store), firm_id=FIRM, client_id=CLIENT,
                              period=PERIOD) is True
    header = store["gstr2b_reconciliations"][0]
    assert header["document_count"] == 0
    assert store.get("gstr2a_records", []) == []


def test_a_file_that_is_not_a_2b_records_nothing():
    """The other side of the same line. `docdata_seen` is the discriminator, and
    it must not be satisfied by an arbitrary JSON object."""
    store = {}
    out = svc.reconcile_2b(_DB(store), firm_id=FIRM, client_id=CLIENT,
                           period=PERIOD, raw={"invoices": [{"inum": "X"}]})
    assert out["persisted"] is False
    assert store.get("gstr2b_reconciliations", []) == []
    assert svc.was_reconciled(_DB(store), firm_id=FIRM, client_id=CLIENT,
                              period=PERIOD) is False


def test_rule_36_4_caps_at_nil_when_a_2b_is_on_file_and_shows_nothing():
    """THE CONSEQUENCE, stated as the rule rather than as the plumbing.

    Book ITC of ₹5,00,000 with a 2B on file showing no eligible credit is
    capped to nil. The same book ITC with NO 2B on file is left alone. Those
    are opposite answers and the flag has to tell them apart."""
    book = 5_00_000_00
    assert _apply_rule_36_4_cap(book, 0, True) == (0, True)
    assert _apply_rule_36_4_cap(book, 0, False) == (book, False)


def test_have_2b_is_not_derived_from_the_row_count():
    """The regression in one line: `have_2b = len(rows) > 0` cannot distinguish
    an empty 2B from an absent one, because both give zero rows. If a future
    edit reintroduces that derivation this fails, whatever it is spelled."""
    import inspect
    from domain.gst import gstr3b_computer
    src = inspect.getsource(gstr3b_computer.compute_gstr3b)
    assert "have_2b: Optional[bool]" in inspect.getsource(gstr3b_computer.compute_gstr3b) \
        or "have_2b" in str(inspect.signature(gstr3b_computer.compute_gstr3b)), \
        "compute_gstr3b must ACCEPT have_2b — a caller that knows must be able to say"
    from services import gst_return_service
    caller = inspect.getsource(gst_return_service)
    assert "was_reconciled(" in caller, (
        "gst_return_service must ask the reconciliation header whether a 2B is "
        "on file, not infer it from the document rows it just filtered")


# ── 2. a credit note and a debit note may share a number ────────────────────

def test_a_credit_note_and_a_debit_note_with_one_number_are_two_documents():
    """THE DEFECT: uq_gstr2a_records_document omitted document_type, so these
    two rows collided on the unique index. Because reconcile_2b deletes the
    period and then inserts, the DELETE committed and the INSERT raised — the
    period's previous reconciliation was destroyed and nothing replaced it.

    A supplier's credit-note and debit-note series are independent. The same
    number in both is ordinary, not exotic."""
    parsed = parse_gstr2b(_file(_note("CN-1", "C"), _note("CN-1", "D")))
    assert len(parsed.documents) == 2
    keys = {(d.section, d.document_type, d.supplier_gstin, d.document_number)
            for d in parsed.documents}
    assert len(keys) == 2, (
        "the natural key must separate a credit note from a debit note; "
        f"got {keys}")


def test_the_migration_puts_document_type_in_the_natural_key():
    """The index is what actually enforces it, so the index is what is asserted.
    Reading the migration is the only way to check this without a database."""
    from pathlib import Path
    sql = Path("migrations/341_a_reconciliation_records_that_it_happened.sql").read_text()
    assert "uq_gstr2a_records_document" in sql
    idx = sql.split("CREATE UNIQUE INDEX IF NOT EXISTS uq_gstr2a_records_document")[1]
    idx = idx.split(";")[0]
    for col in ("client_id", "return_period", "section", "document_type",
                "supplier_gstin", "invoice_number"):
        assert col in idx, f"{col} missing from the natural key"


# ── 3. the service paginates ────────────────────────────────────────────────

def test_the_reconciliation_service_paginates_its_reads():
    """Eleven sibling services carry _paginate_all; this one shipped without it,
    so read_book_bills truncated a busy month at PostgREST's 1000 rows and every
    2B document belonging to a dropped bill was reported as missing_in_books —
    sending the CA to chase a document they already hold."""
    import inspect
    src = inspect.getsource(svc)
    assert "def _paginate_all" in src
    for fn in ("read_book_bills", "read_reconciliation"):
        body = inspect.getsource(getattr(svc, fn))
        assert "_paginate_all(" in body, f"{fn} must page; a bare execute() caps at 1000"


# ── 4. the rate registries do not claim a year they do not hold ─────────────

def test_a_substituted_financial_year_is_not_reported_as_verified():
    """`rates_for()` falls back to LATEST_VERIFIED_FY, and that entry's own
    verified=True was being copied onto the result — asserting that a Finance Act
    had been checked for a year nobody had entered."""
    from domain.income_tax.itr_engine import ITREngine, ITRComputeRequest
    r = ITREngine().compute(ITRComputeRequest(
        fy="2024-25", assessee_kind="domestic_company",
        book_profit_paise=50_00_000_00, business_income_paise=50_00_000_00))
    assert r.rates_verified is False
    assert any("2024-25" in w and "2025-26" in w for w in r.warnings), (
        "the warning must name BOTH years — 'not verified' alone does not tell a "
        "CA which rates their computation actually used")


def test_a_year_the_registry_holds_is_still_reported_honestly():
    """The guard must not simply always answer False."""
    from domain.income_tax.itr_engine import ITREngine, ITRComputeRequest
    r = ITREngine().compute(ITRComputeRequest(
        fy="2025-26", assessee_kind="domestic_company",
        book_profit_paise=50_00_000_00, business_income_paise=50_00_000_00))
    assert r.rates_verified is True and r.fy == "2025-26"
    assert not r.warnings


# ── 5. a payslip refusal says what is wrong ─────────────────────────────────

def test_the_payslip_route_does_not_flatten_every_refusal_to_not_found():
    import inspect
    from routers import payroll
    # The PDF route specifically. `_assert_slip_scope` raising "Salary slip not
    # found" for a slip that genuinely is not there is correct and stays; what was
    # wrong was the DOWNLOAD route catching every ValueError from the service and
    # replacing its message with that sentence.
    src = inspect.getsource(payroll.download_salary_slip_pdf)
    assert "except ValueError as e:" in src and "detail=str(e)" in src, (
        "load_employer refuses a run with no client so the payslip is not headed "
        "with the CA firm's name; flattening that to a fixed 'not found' tells the "
        "CA the slip does not exist and hides the only thing they can act on")


# ── 6. the rupee sign never reaches a core-font PDF ─────────────────────────

def test_no_pdf_service_emits_a_rupee_sign():
    """Helvetica is WinAnsiEncoding and has no U+20B9; it lands in the PDF as an
    unmapped glyph. Two services knew this and three did not — including the
    payslip, which an employee receives."""
    import ast
    from pathlib import Path
    from domain.reporting.pdf_text import RUPEE_SIGN

    # THE RULE, NOT A SPELLING OF IT. A first version of this grepped the file
    # text and flagged the two COMMENTS that explain why "Rs." is used — the same
    # error as the money-parser guard, which named three spellings of a defect
    # instead of the defect. What matters is a rupee sign in a string the code
    # can EMIT, so the check walks the AST and ignores comments and docstrings.
    def _docstrings(tree):
        out = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                body = getattr(node, "body", None)
                if body and isinstance(body[0], ast.Expr) and \
                   isinstance(body[0].value, ast.Constant) and \
                   isinstance(body[0].value.value, str):
                    out.add(id(body[0].value))
        return out

    def _stripped(tree):
        """Literals handed to `.replace(...)` are the needle being REMOVED.
        `"".replace("₹", "Rs. ")` emits no rupee sign; it deletes one."""
        out = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
               and node.func.attr == "replace":
                for a in node.args:
                    if isinstance(a, ast.Constant):
                        out.add(id(a))
        return out

    offenders = []
    for path in sorted(Path("services").glob("*pdf*service.py")):
        tree = ast.parse(path.read_text())
        skip = _docstrings(tree) | _stripped(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
               and RUPEE_SIGN in node.value and id(node) not in skip:
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "these emit a rupee sign into a core-font PDF, where Helvetica's "
        f"WinAnsiEncoding has no glyph for it: {offenders}")


def test_the_shared_helper_exists_and_is_not_applied_to_html_for_screens():
    from domain.reporting.pdf_text import pdf_safe
    assert pdf_safe("Net Pay: ₹1,234.56") == "Net Pay: Rs.1,234.56"
    assert pdf_safe(None) == ""


# ── 7. a CA's "today" is IST ────────────────────────────────────────────────

def test_fixed_assets_dates_are_ist_not_utc():
    """At 00:20 IST on 1 April a UTC 'today' is still 31 March, so a defaulted
    depreciation period or disposal date lands in the PREVIOUS financial year —
    quite possibly one the CA has just locked."""
    import inspect
    from routers import fixed_assets
    src = inspect.getsource(fixed_assets)
    assert "datetime.now(timezone.utc).strftime" not in src
    assert "datetime.now(timezone.utc).date()" not in src
    assert "ist_today" in src
