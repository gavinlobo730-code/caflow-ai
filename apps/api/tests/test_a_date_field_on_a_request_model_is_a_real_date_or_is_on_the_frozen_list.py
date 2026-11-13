"""A request model's date field is a real date by construction, or it is on a list that only shrinks (POST-A-380).

THE RULE, NOT A SPELLING OF IT
    A field of a request model whose NAME says it is a date (`..._date`, `..._on`, `..._dt`, `date_...`, `as_at`, `valid_until`, `effective_from`, ...) and whose
    ANNOTATION is a bare `str` or `Optional[str]` hands whatever a caller sent to the period check, `fy_code` and a DATE column, and a caller that is not the screen
    gets a 500 with no sentence. A field is judged when it is annotated `IsoDate`, `OptionalIsoDate` or `PatchIsoDate` (`models/iso_date`), or when a
    `field_validator` names it, in whatever form the validator is written (decorator, or `x = field_validator("f")(fn)`).

    What is left is on `tests/fixtures/bare_date_fields.txt`, one `file::Class.field` per line. The list is SHRINK-ONLY, in both directions:
      * a bare date field that is not on it FAILS (give the field one of the three types, or a validator; do not add a line);
      * a line that no longer names a bare date field FAILS (delete the line: the field was fixed, and a list that keeps its fixed entries lets the next
        author put one back unseen).
    The list is not a verdict that the field is wrong: some hold a due-date phrase or a date a bulk import judges row by row (an opening-document row with a blank date is that
    row's error, not the batch's), and each is read against its callers before it is narrowed, as the ledger line POST-A-380 says.

    The scan is over the Pydantic models of the API tree it can resolve: a `BaseModel` subclass (also under an alias, `from pydantic import BaseModel as _BaseModel`), or a subclass of
    one in the same module or imported from `models`, `routers` or `services`. A dataclass in `domain/` is not a request model, and a class whose name ends in `Out`, `Response` or
    `Record` is a shape the API sends, not one it takes, and is not judged. The annotation is read in its common spellings (`Optional[str]`, `str | None`, `Union[str, None]`, quoted,
    `typing.`-prefixed, inside `Annotated[...]`). THE NAME RULE IS A HEURISTIC and says so: a date called `valid_from`, `dob` or `expiry` is not matched, and a `field_validator` that
    does nothing counts as judging; this is a ratchet against the commonest spelling of the defect and not a proof that no request model takes a bad date.

    A RENAME OR A MOVE of a still-bare field replaces its line (delete the old one, add the new); every other addition is a violation.
    A field that is bare ON PURPOSE stays on the list with its reason where the field is declared: `NearDuplicateProbeIn.bill_date` is a read-only advisory probe that never refuses.
"""
from __future__ import annotations

import ast
import functools
import re
from pathlib import Path

from models.iso_date import DATE_TYPE_NAMES

API = Path(__file__).resolve().parent.parent
LIST = API / "tests" / "fixtures" / "bare_date_fields.txt"
SKIP_DIRS = ("tests", "migrations", "scripts", "node_modules", ".venv", "venv")
NAMED_LIKE_A_DATE = (
    "_date", "_on", "_dt",
)
EXACT_NAMES = {"date", "as_of", "as_at", "valid_until", "effective_from", "effective_to", "period_start", "period_end"}
SENT_BY_US = ("Out", "Response", "Record")
BARE = {"str", "Optional[str]"}


def _normal(annotation: str) -> str:
    """The annotation's spelling folded to one: quotes, `typing.`, `Union[str, None]`, `str | None`, `None | str` and `Annotated[str, ...]` all read as `str` or `Optional[str]`."""
    text = annotation.replace('"', "").replace("'", "").replace("typing.", "").replace(" ", "")
    text = re.sub(r"^Annotated\[(.*?),.*\]$", r"\1", text)
    if text in ("str|None", "None|str", "Union[str,None]", "Union[None,str]"):
        return "Optional[str]"
    return text


def _is_a_date_name(name: str) -> bool:
    return name.endswith(NAMED_LIKE_A_DATE) or name.startswith("date_") or name in EXACT_NAMES


def _validated_fields(cls: ast.ClassDef) -> set[str]:
    named: set[str] = set()
    for node in ast.walk(cls):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in ("field_validator", "validator"):
            for a in node.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    named.add(a.value)
    return named


def _pydantic_models(tree: ast.Module) -> set[str]:
    """Names of the classes in a module that are Pydantic models: a `BaseModel` subclass, a subclass of one defined in the same module, or of a name imported from `models.*`.
    A dataclass or a plain class in `domain/` is not a request model and is not judged."""
    imported = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] in ("models", "routers", "services") for a in n.names}
    # `from pydantic import BaseModel as _BaseModel` (routers/inventory.py) is still BaseModel.
    aliases = {a.asname for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "pydantic" for a in n.names if a.name == "BaseModel" and a.asname}
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    found: set[str] = set()
    changed = True
    while changed:
        changed = False
        for c in classes:
            if c.name in found:
                continue
            bases = {getattr(b, "attr", getattr(b, "id", "")) for b in c.bases}
            if "BaseModel" in bases or bases & aliases or bases & found or bases & imported:
                found.add(c.name)
                changed = True
    return found


@functools.lru_cache(maxsize=1)
def scan() -> tuple[frozenset[str], frozenset[str]]:
    """(bare date fields as `file::Class.field`, fields annotated with one of the three date types)."""
    bare: set[str] = set()
    typed: set[str] = set()
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API).as_posix()
        if rel.split("/")[0] in SKIP_DIRS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        models = _pydantic_models(tree)
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name in models):
            validated = _validated_fields(cls)
            for stmt in cls.body:
                if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                    continue
                name, ann = stmt.target.id, _normal(ast.unparse(stmt.annotation))
                if ann in DATE_TYPE_NAMES:
                    typed.add(f"{rel}::{cls.name}.{name}")
                elif _is_a_date_name(name) and ann in BARE and name not in validated and not cls.name.endswith(SENT_BY_US):
                    bare.add(f"{rel}::{cls.name}.{name}")
    return frozenset(bare), frozenset(typed)


def _frozen() -> set[str]:
    return {ln.strip() for ln in LIST.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")}


def test_the_scan_sees_what_it_is_for():
    bare, typed = scan()
    # Vacuity floors on what does not shrink with the work: the typed fields only grow, and bare + typed together are the date fields the scan sees at all
    # (a field moves from one to the other as the list is narrowed, so the sum holds while either floor alone would be wrong).
    assert len(typed) >= 20, f"only {len(typed)} fields are annotated with a date type"
    assert "models/invoices.py::ReceiptIn.receipt_date" in typed and "models/invoices.py::PurchasePaymentIn.payment_date" in typed
    assert len(bare) + len(typed) >= 120, f"the scan found only {len(bare) + len(typed)} date fields; it has stopped reading what it reads"
    # The aliased import is read: routers/inventory.py writes `from pydantic import BaseModel as _BaseModel`.
    tree = ast.parse((API / "routers" / "inventory.py").read_text(encoding="utf-8"))
    assert "GodownIn" in _pydantic_models(tree), "a model whose base is an aliased BaseModel is not read"


def test_no_bare_date_field_is_new():
    bare, _ = scan()
    new = sorted(bare - _frozen())
    assert not new, ("A request model takes a date as a bare string (give the field IsoDate, OptionalIsoDate or PatchIsoDate from models/iso_date, or a "
                     "field_validator; do not add it to tests/fixtures/bare_date_fields.txt):\n  " + "\n  ".join(new))


def test_the_frozen_list_names_only_fields_that_are_still_bare():
    bare, _ = scan()
    fixed = sorted(_frozen() - bare)
    assert not fixed, ("These are no longer bare date fields: delete their lines from tests/fixtures/bare_date_fields.txt:\n  " + "\n  ".join(fixed))


def test_the_frozen_list_is_sorted_and_has_no_duplicates():
    lines = [ln.strip() for ln in LIST.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert lines == sorted(set(lines)), "keep the list sorted, one entry once"


def test_the_document_dates_are_not_on_the_list():
    on_it = _frozen()
    for entry in ("models/invoices.py::SalesInvoiceIn.invoice_date", "models/invoices.py::PurchaseBillIn.bill_date", "models/invoices.py::ReceiptIn.receipt_date",
                  "models/invoices.py::PurchasePaymentIn.payment_date", "routers/credit_notes.py::CreditNoteIn.credit_note_date",
                  "routers/sales_debit_notes.py::SalesDebitNoteIn.debit_note_date", "models/accounting.py::JournalReversalIn.reversal_date"):
        assert entry not in on_it, f"{entry} went back on the list"


def test_the_scan_reads_the_spellings_and_the_bases_it_says_it_reads():
    spellings = ['Optional[str]', 'Optional["str"]', '"Optional[str]"', 'typing.Optional[str]', 'Union[str, None]', 'Union[None, str]', 'str | None', 'None | str']
    assert {_normal(a) for a in spellings} == {"Optional[str]"}
    assert _normal("str") == "str" and _normal('Annotated[str, Field(max_length=10)]') == "str"
    assert _normal('Annotated[Optional[str], Field(None)]') == "Optional[str]"
    assert _normal("int") == "int" and _normal("Optional[int]") == "Optional[int]"      # a number field is none of this rule's business
    tree = ast.parse("from pydantic import BaseModel as BM\nfrom services.x import Shared\nfrom models.y import Other\n"
                     "class A(BM):\n    a_date: str\nclass B(Shared):\n    b_date: str\nclass C(Other):\n    c_date: str\nclass D(A):\n    d_date: str\nclass E:\n    e_date: str\n")
    assert _pydantic_models(tree) == {"A", "B", "C", "D"}
