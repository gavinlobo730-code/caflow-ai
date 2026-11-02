"""Every key a note router puts on a line is a column the numbering function stores (POST-A-370; migration 576; the receipt's twin is
`test_every_key_the_receipt_payload_sends_is_stored_by_the_function_that_records_it.py`).

WHAT WAS WRONG
    The four note kinds are recorded through `numbered_document_atomic` (body `numbered_document_atomic__unguarded`, migration 167). Its HEADER insert
    is generic (the keys the caller sends), but its LINES insert names a fixed column list, written before the routers began sending `unit` and
    `service_catalogue_id`, so both were dropped on every note line without an error. The suite's double stores whatever it is given.

WHAT THIS HOLDS (mock mode, no database)
    The rule, not a spelling of it: for each of the four note routers it reads from the SOURCE (an AST walk) the keys of the dict literal each line is
    built as (the one carrying `hsn_sac` and `line_total_paise`), reads the column list of the lines INSERT in the LAST migration that defines the
    function's body (found by number, because `CREATE OR REPLACE` replaces the whole body), and fails any key not in it. Exemptions are named here
    with the reason; the list is empty. The real-Postgres half is `test_576_..._pg.py`.
"""
import ast
import re
from pathlib import Path

API = Path(__file__).resolve().parents[1]
MIGRATIONS = API / "migrations"
ROUTERS = ("credit_notes", "debit_notes", "purchase_credit_notes", "sales_debit_notes")

#: Keys a router puts on a line that the function deliberately does not store, each with the reason. None.
NOT_STORED: dict[str, str] = {}

_DEFINES = re.compile(r"FUNCTION\s+(public\.)?numbered_document_atomic(__unguarded)?\s*\(", re.I)
_LINES_INSERT = re.compile(r"INSERT INTO public\.%1\$I \('(.*?)\)\s*SELECT", re.S)


def _line_keys(router: str) -> set[str]:
    tree = ast.parse((API / "routers" / f"{router}.py").read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if {"hsn_sac", "line_total_paise", "taxable_amount_paise"} <= keys:
                found |= keys
    return found


def _columns(raw: str) -> set[str]:
    """The column names in the quoted, concatenated list of the INSERT (the foreign key's `%2$I` is called FK)."""
    return {c for c in re.split(r"[,\s']+", raw.replace("%2$I", "FK")) if c}


def _function_columns() -> tuple[str, set[str]]:
    """(the migration, the line columns) of the last migration whose text defines the function and holds its lines INSERT."""
    last = None
    for path in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")):
        if path.name.endswith("_rollback.sql"):
            continue
        text = path.read_text(encoding="utf-8")
        if _DEFINES.search(text) and _LINES_INSERT.search(text):
            last = (path.name, text)
    assert last, "no migration defines the note function's lines insert"
    return last[0], _columns(_LINES_INSERT.search(last[1]).group(1))


def test_each_router_builds_a_line_dict_and_the_function_has_columns():
    for router in ROUTERS:
        keys = _line_keys(router)
        assert {"description", "hsn_sac", "unit", "service_catalogue_id", "line_total_paise"} <= keys, (router, sorted(keys))
    name, cols = _function_columns()
    assert {"FK", "description", "hsn_sac", "line_total_paise"} <= cols, (name, sorted(cols))


def test_every_key_a_note_router_puts_on_a_line_is_a_column_the_function_stores():
    name, cols = _function_columns()
    for router in ROUTERS:
        dropped = sorted(k for k in _line_keys(router) if k not in cols and k not in NOT_STORED)
        assert not dropped, (
            f"routers/{router}.py puts {dropped} on every note line, and the last definition of the numbering function ({name}) does not store "
            "them: the function drops them without an error. Add them to the lines INSERT in a new migration (derive the body from that one, "
            "found by number), or name the key in NOT_STORED with the reason.")


def test_a_key_named_as_not_stored_is_really_sent_and_really_not_stored():
    name, cols = _function_columns()
    sent = set().union(*(_line_keys(r) for r in ROUTERS))
    for k, why in NOT_STORED.items():
        assert why.strip() and k in sent and k not in cols, f"{k} no longer needs an exemption"


def test_the_scan_sees_a_dropped_key_in_a_synthetic_case():
    sample = ("CREATE OR REPLACE FUNCTION public.numbered_document_atomic__unguarded(a text) AS $$ EXECUTE format("
              "'INSERT INTO public.%1$I ('\n      '  %2$I, description, hsn_sac, line_total_paise'\n      ') SELECT '\n '1' ) $$;")
    assert _DEFINES.search(sample) and _LINES_INSERT.search(sample)
    cols = _columns(_LINES_INSERT.search(sample).group(1))
    assert "unit" not in cols and "description" in cols
