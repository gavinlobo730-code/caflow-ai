"""Every key `create_receipt_core` puts in the receipt it sends to the database function is a column that function stores (POST-A-369 review of
migration 572, found on the way; migrations 574 and 575).

WHAT WAS WRONG
    Every receipt production records goes through `settle_receipt_atomic` (the real client always has `.rpc`), whose body is migration 235's INSERT
    INTO public.receipts with a fixed column list. The API later began sending `bank_account_id` (SALES-08, migration 342), the three GSTR-1 Table 11A
    columns (migration 286, SALES-15) and a pre-generated `id`, each added to the payload and to the table and NONE added to the function's list. The
    function dropped them without an error, and the test double the suite uses (`tests/e2e_harness.py`, which stores the whole payload) could not
    tell: the Receipts tab said a receipt was posted to the general Bank ledger when its journal debited the CA's bank, an advance receipt kept no rate
    or place of supply, and 101 of 101 production receipts were stored under an id their own ledger entry did not carry.

WHAT THIS HOLDS (mock mode, no database)
    The rule, not a spelling of it: it reads the keys of the `receipt_payload` dict literal in `create_receipt_core` from the SOURCE (an AST walk, so a
    key added tomorrow is seen), reads the column list of the INSERT INTO public.receipts in the LAST migration that defines the receipt function's body
    (found by number, because `CREATE OR REPLACE` replaces the whole body), and fails any key that is not a column in it. The only keys allowed to be
    missing are named here with the reason, and the list is empty. The real-Postgres half (the call stores them, and the stored id is the entry's
    `source_id`) is `test_574_..._pg.py`.
"""
import ast
import re
from pathlib import Path

API = Path(__file__).resolve().parents[1]
MIGRATIONS = API / "migrations"
SERVICE = API / "services" / "receipt_service.py"

#: Keys the service sends that the function deliberately does not store, each with the reason. None.
NOT_STORED: dict[str, str] = {}

_DEFINES_THE_BODY = re.compile(r"CREATE\s+(OR\s+REPLACE\s+)?FUNCTION\s+(public\.)?settle_receipt_atomic(__unguarded)?\s*\(", re.I)
_INSERT = re.compile(r"INSERT\s+INTO\s+public\.receipts\s*\((.*?)\)\s*VALUES", re.I | re.S)


def _payload_keys() -> set[str]:
    tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "create_receipt_core":
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "receipt_payload" for t in node.targets) \
                        and isinstance(node.value, ast.Dict):
                    return {k.value for k in node.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    raise AssertionError("create_receipt_core no longer builds a `receipt_payload` dict literal: this guard must be pointed at the new shape")


def _function_columns() -> tuple[str, set[str]]:
    """(the migration, the columns) of the last migration whose text defines the receipt function and inserts into receipts."""
    found = []
    for path in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")):
        if path.name.endswith("_rollback.sql"):
            continue
        text = path.read_text(encoding="utf-8")
        if _DEFINES_THE_BODY.search(text) and _INSERT.search(text):
            found.append((path.name, text))
    assert found, "no migration defines the receipt function's insert"
    name, text = found[-1]
    cols = {c.strip() for c in _INSERT.search(text).group(1).split(",") if c.strip()}
    return name, cols


def test_the_payload_has_keys_and_the_function_has_columns():
    keys, (name, cols) = _payload_keys(), _function_columns()
    assert {"id", "firm_id", "client_id", "bank_account_id", "gst_rate_bps", "place_of_supply", "is_interstate"} <= keys, (
        "the payload lost a key this guard exists for, or the service was restructured")
    assert {"firm_id", "client_id", "journal_entry_id"} <= cols, (name, cols)


def test_every_key_the_service_sends_is_a_column_the_function_stores():
    keys, (name, cols) = _payload_keys(), _function_columns()
    dropped = sorted(k for k in keys if k not in cols and k not in NOT_STORED)
    assert not dropped, (
        f"create_receipt_core sends {dropped} in the receipt payload, and the last definition of the receipt function ({name}) does not store "
        "them: the function drops them without an error. Add them to its INSERT in a new migration (derive the body from that one, found by "
        "number), or name the key in NOT_STORED with the reason.")


def test_a_key_named_as_not_stored_is_really_sent_and_really_not_stored():
    keys, (_name, cols) = _payload_keys(), _function_columns()
    for k, why in NOT_STORED.items():
        assert why.strip() and k in keys and k not in cols, f"{k} no longer needs an exemption"


def test_the_guard_sees_a_dropped_key_in_a_synthetic_case():
    """The scan is not vacuous: a column list without `bank_account_id` fails the same comparison."""
    sample = "CREATE OR REPLACE FUNCTION public.settle_receipt_atomic__unguarded(a jsonb) AS $$ INSERT INTO public.receipts (id, firm_id) VALUES (1,2) $$;"
    assert _DEFINES_THE_BODY.search(sample)
    cols = {c.strip() for c in _INSERT.search(sample).group(1).split(",")}
    assert "bank_account_id" not in cols and "id" in cols
