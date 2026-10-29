"""A PDF the platform issues names the party that issued it, and only a document the PRACTICE issues reads the practice's row
(ledger POST-A-100).

WHAT WAS WRONG
    The practice was printed where the client belongs in three PDF services: the payslip (PAY-03), the supplier block of a client's
    sales invoice and the customer statement (SALES-01). Each was fixed in its own file with a test in its own file
    (`test_a_payslip_names_the_employer_not_the_practice`, `test_sales_invoice_pdf_supplier`,
    `test_a_statement_names_the_client_not_the_practice`), so the payslip survived two rounds of review because no test looked at the
    whole set of PDF services at once, and the next PDF service written would have started from whichever file its author copied.

THE RULE, NOT A LIST OF TODAY'S FILES
    Every `services/*_pdf_service.py` is scanned, whatever it is called and however many there are. In it:

    * **THE READERS OF THE PRACTICE'S ROW ARE A REVIEWED SET.** A function that reads the practice (a call to `_load_firm` or
      `_firm_party`, or a read of the `firms` table) is named below with the document it belongs to. A new reader fails here until
      someone says which document the practice issues. A stale entry fails too.
    * **A DOCUMENT THE PRACTICE DOES NOT ISSUE NEVER REACHES A READER.** Every public function of every PDF service that is not in
      `ISSUED_BY_THE_PRACTICE` must be unable, through any chain of calls inside the PDF services, to reach a reader. The payslip,
      the client's sales invoice, the customer and vendor statements and the year-end pack are in that group by not being listed:
      the practice is not a party to them (the employer, the client and the client's customer are).
    * **A DOCUMENT THAT IS GIVEN THE PRACTICE SAYS SO IN ITS SIGNATURE.** A public function with a parameter named `firm`,
      `firm_row` or `firm_name` is on a reviewed list. The statement used to take `firm`; that parameter was the defect.
    * **NO PDF SERVICE IMPORTS A READER BY NAME UNLESS IT IS REVIEWED.** The customer statement imported `_load_firm` and never
      called it; the import is how the next author reaches for it.

    The rule works on source it is handed (`analyse`), so the cases below plant a payslip that reads the practice and a statement that
    takes a firm and show each is found: a rule that cannot see its subject is worse than none.

WHAT IT DOES NOT SEE
    A document that gets the practice's name by another route (a caller passes it in as data, the way the year-end pack takes
    `firm_name` from the engagement) is not a read of the row and is not found; those are held by the per-document tests, which render
    the PDF and read its text. This rule is the structural half that the per-document tests could not be: it stops the NEXT service.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

SERVICES = Path(__file__).resolve().parents[1] / "services"

#: The ways a PDF service reaches the practice's own row.
READER_CALLS = {"_load_firm", "_firm_party"}
READER_TABLES = {"firms"}
#: A parameter that hands the practice to a document.
FIRM_PARAMETERS = {"firm", "firm_row", "firm_name"}

#: (module, function) -> the document it belongs to. These are the functions that read the practice's row.
REVIEWED_READERS = {
    ("invoice_pdf_service", "_load_firm"):
        "the reader itself: the `firms` row, used by the practice's own FEE invoice and by the reconciliation working paper below",
    ("invoice_pdf_service", "build_invoice_pdf"):
        "the practice's FEE invoice (`fee_invoices`): builds the supplier block with `_firm_party`; the CA firm supplies and the client is billed",
    ("invoice_pdf_service", "get_invoice_pdf"):
        "loads the practice for the same FEE invoice; a client's sales invoice goes through `get_sales_invoice_pdf` instead",
    ("bank_reconciliation_pdf_service", "get_reconciliation_pdf"):
        "the bank reconciliation is the practice's working paper about a client's account, headed 'prepared by' the practice",
}

#: The public functions that may reach a reader: the documents the practice issues. Everything else is the client's, the employer's or
#: a third party's document, and the practice is not a party to it.
ISSUED_BY_THE_PRACTICE = {
    ("invoice_pdf_service", "get_invoice_pdf"),
    ("invoice_pdf_service", "build_invoice_pdf"),
    ("bank_reconciliation_pdf_service", "get_reconciliation_pdf"),
}

#: Public functions that take the practice as a parameter, with the reason. A report the practice hands to a banker or an auditor
#: about the client carries the practice's heading, and the fee invoice and the reconciliation are the practice's own.
REVIEWED_FIRM_PARAMETERS = {
    ("invoice_pdf_service", "build_invoice_pdf"): "the practice's FEE invoice",
    ("bank_reconciliation_pdf_service", "build_reconciliation_pdf"): "the reconciliation working paper, headed with the practice",
    ("report_pdf_service", "build_report_pdf"): "a report the practice hands to a banker or an auditor about the client; the heading is the practice's",
}

#: (importing module, name) pairs: a PDF service that imports a reader by name.
REVIEWED_READER_IMPORTS = {
    ("bank_reconciliation_pdf_service", "_load_firm"): "it calls it in `get_reconciliation_pdf`",
}


@dataclass
class Analysis:
    modules: dict[str, ast.Module]
    functions: dict[tuple[str, str], ast.AST] = field(default_factory=dict)
    readers: set[tuple[str, str]] = field(default_factory=set)
    edges: dict[tuple[str, str], set[tuple[str, str]]] = field(default_factory=dict)
    public: set[tuple[str, str]] = field(default_factory=set)
    firm_parameters: set[tuple[str, str]] = field(default_factory=set)
    reader_imports: set[tuple[str, str]] = field(default_factory=set)

    def reachable(self, start: tuple[str, str]) -> set[tuple[str, str]]:
        seen, stack = set(), [start]
        while stack:
            node = stack.pop()
            for nxt in self.edges.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen


def _stem(path_or_module: str) -> str:
    return path_or_module.rsplit("/", 1)[-1].removesuffix(".py").rsplit(".", 1)[-1]


def analyse(sources: dict[str, str]) -> Analysis:
    """`sources` maps a module name (`payslip_pdf_service`) to its source."""
    a = Analysis(modules={name: ast.parse(src) for name, src in sources.items()})
    imported_symbols: dict[str, dict[str, tuple[str, str]]] = {}
    imported_modules: dict[str, dict[str, str]] = {}
    for mod, tree in a.modules.items():
        syms, mods = {}, {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    local = alias.asname or alias.name
                    if _stem(node.module) in a.modules:
                        syms[local] = (_stem(node.module), alias.name)
                    elif alias.name in a.modules:
                        mods[local] = alias.name
                    if alias.name in READER_CALLS:
                        a.reader_imports.add((mod, alias.name))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _stem(alias.name) in a.modules:
                        mods[alias.asname or alias.name.rsplit(".", 1)[-1]] = _stem(alias.name)
        imported_symbols[mod], imported_modules[mod] = syms, mods
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a.functions[(mod, node.name)] = node
                if not node.name.startswith("_"):
                    a.public.add((mod, node.name))
                params = {p.arg for p in node.args.posonlyargs + node.args.args + node.args.kwonlyargs}
                if params & FIRM_PARAMETERS:
                    a.firm_parameters.add((mod, node.name))
    for (mod, name), fn in a.functions.items():
        targets: set[tuple[str, str]] = set()
        for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
            f = call.func
            called = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if called in READER_CALLS:
                a.readers.add((mod, name))
            if (isinstance(f, ast.Attribute) and f.attr in ("table", "from_") and call.args
                    and isinstance(call.args[0], ast.Constant) and call.args[0].value in READER_TABLES):
                a.readers.add((mod, name))
            if isinstance(f, ast.Name):
                if (mod, f.id) in a.functions:
                    targets.add((mod, f.id))
                elif f.id in imported_symbols[mod]:
                    targets.add(imported_symbols[mod][f.id])
            elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in imported_modules[mod]:
                targets.add((imported_modules[mod][f.value.id], f.attr))
        a.edges[(mod, name)] = {t for t in targets if t in a.functions}
    return a


def _tree() -> Analysis:
    sources = {p.stem: p.read_text(encoding="utf-8") for p in sorted(SERVICES.glob("*_pdf_service.py"))}
    return analyse(sources)


# ── the rule over the tree ─────────────────────────────────────────────────────────────────────────────────────────
def test_the_scan_finds_the_pdf_services_it_is_meant_to_guard():
    """Vacuity: the rule is only as wide as the glob."""
    a = _tree()
    assert len(a.modules) >= 7, sorted(a.modules)
    assert {"invoice_pdf_service", "payslip_pdf_service", "statement_pdf_service"} <= set(a.modules)
    assert len(a.public) >= 15, len(a.public)
    assert a.readers, "no function reads the practice's row: the detector has stopped seeing the reads it exists for"


def test_the_functions_that_read_the_practices_row_are_the_reviewed_ones():
    a = _tree()
    unreviewed = sorted(a.readers - set(REVIEWED_READERS))
    stale = sorted(set(REVIEWED_READERS) - a.readers)
    assert not unreviewed, (
        f"{unreviewed} read the practice's row (`_load_firm`, `_firm_party` or the `firms` table). A PDF names the party that "
        "issued it: the employer on a payslip, the client on its invoice and statements, the practice only on a document the "
        "practice issues. If the practice IS the issuer, add the function to REVIEWED_READERS and ISSUED_BY_THE_PRACTICE with "
        "the document; if not, read the client's row instead (`statement_pdf_service.load_account_holder` is the pattern).")
    assert not stale, f"these reviewed readers no longer read the practice's row: delete them: {stale}"


def test_a_document_the_practice_does_not_issue_never_reaches_the_practices_row():
    a = _tree()
    offenders = {}
    for fn in sorted(a.public - ISSUED_BY_THE_PRACTICE):
        reached = (a.reachable(fn) | {fn}) & a.readers
        if reached:
            offenders[fn] = sorted(reached)
    assert not offenders, (
        "these PDF functions are not documents the practice issues and still reach a reader of the practice's row, so the "
        f"practice can be printed where the client, the employer or the customer belongs: {offenders}")


def test_the_documents_the_practice_issues_are_real_and_do_reach_the_practices_row():
    a = _tree()
    for fn in sorted(ISSUED_BY_THE_PRACTICE):
        assert fn in a.public, f"{fn} is listed as issued by the practice but is not a public function of a PDF service"
        assert (a.reachable(fn) | {fn}) & a.readers, (
            f"{fn} is listed as issued by the practice but reads no practice row: delete the entry, the document needs no exemption")


def test_only_the_reviewed_documents_take_the_practice_as_a_parameter():
    a = _tree()
    unreviewed = sorted(a.firm_parameters & a.public - set(REVIEWED_FIRM_PARAMETERS))
    stale = sorted(set(REVIEWED_FIRM_PARAMETERS) - a.firm_parameters)
    assert not unreviewed, (
        f"{unreviewed} take the practice as a parameter (firm, firm_row or firm_name). The customer statement did, and the "
        "practice was printed where the client belongs. Take the party the document is issued BY, or review the function here.")
    assert not stale, f"these reviewed parameters are gone: delete the entries: {stale}"


def test_a_pdf_service_imports_a_reader_of_the_practice_only_where_it_is_reviewed():
    a = _tree()
    unreviewed = sorted(a.reader_imports - set(REVIEWED_READER_IMPORTS))
    stale = sorted(set(REVIEWED_READER_IMPORTS) - a.reader_imports)
    assert not unreviewed, (
        f"{unreviewed} import a reader of the practice's row. The customer statement imported `_load_firm` and never called it; "
        "an import is how the next author reaches for it.")
    assert not stale, f"these reviewed imports are gone: delete the entries: {stale}"


# ── the rule sees what it is meant to see ──────────────────────────────────────────────────────────────────────────
PLANTED_PAYSLIP = {
    "invoice_pdf_service": (
        "def _load_firm(firm_id):\n    return db.table('firms').select('*').execute()\n"
        "def _firm_party(firm):\n    return firm\n"),
    "payslip_pdf_service": (
        "from services.invoice_pdf_service import _load_firm\n"
        "def build_payslip_pdf(slip, employee):\n    return _head(slip)\n"
        "def _head(slip):\n    return _load_firm(slip['firm_id'])\n"),
}


def test_a_payslip_that_reads_the_practice_through_a_helper_is_found():
    a = analyse(PLANTED_PAYSLIP)
    assert ("payslip_pdf_service", "_head") in a.readers
    reached = a.reachable(("payslip_pdf_service", "build_payslip_pdf")) & a.readers
    assert reached == {("payslip_pdf_service", "_head"), ("invoice_pdf_service", "_load_firm")}, reached
    assert ("payslip_pdf_service", "_load_firm") in a.reader_imports


def test_a_read_through_the_imported_module_and_a_direct_table_read_are_found():
    a = analyse({
        "invoice_pdf_service": "def _load_firm(i):\n    return i\n",
        "statement_pdf_service": (
            "import services.invoice_pdf_service as ipdf\n"
            "def build_statement_pdf(statement, firm):\n    return ipdf._load_firm(1)\n"
            "def load_holder(db):\n    return db.table('firms').select('*').execute()\n"),
    })
    assert ("statement_pdf_service", "build_statement_pdf") in a.readers
    assert ("statement_pdf_service", "load_holder") in a.readers
    assert ("statement_pdf_service", "build_statement_pdf") in a.firm_parameters


def test_the_client_row_is_not_a_reader():
    a = analyse({"statement_pdf_service": (
        "def load_account_holder(db, firm_id, client_id):\n"
        "    return db.table('clients').select('*').eq('id', client_id).maybe_single().execute()\n")})
    assert not a.readers and not a.firm_parameters
