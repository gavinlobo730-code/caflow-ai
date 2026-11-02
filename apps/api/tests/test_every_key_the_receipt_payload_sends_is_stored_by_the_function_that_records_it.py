"""Every key `create_receipt_core` puts in the receipt it sends to the database function is a column that function stores (POST-A-369 review of
migration 572, found on the way; migrations 574 and 575).

WHAT WAS WRONG
    Every receipt production records goes through `settle_receipt_atomic` (the real client always has `.rpc`), whose body is migration 235's INSERT
    INTO public.receipts with a fixed column list. The API later began sending `bank_account_id` (SALES-08, migration 342), the three GSTR-1 Table 11A
    columns (migration 286, SALES-15) and a pre-generated `id`, each added to the payload and to the table and NONE added to the function's list. The
    function dropped them without an error, and the test double the suite uses (`tests/e2e_harness.py`, which stored the whole payload) could not
    tell: the Receipts tab said a receipt was posted to the general Bank ledger when its journal debited the CA's bank, an advance receipt kept no rate
    or place of supply, and 101 of 101 production receipts were stored under an id their own ledger entry did not carry.

WHAT THIS HOLDS (mock mode, no database)
    The rule, not a spelling of it: it reads the keys of the `receipt_payload` dict literal in `create_receipt_core` from the SOURCE (an AST walk, so a
    key added tomorrow is seen), reads the column list of the INSERT INTO receipts in the LAST migration that defines the function's body
    (`tests/_receipt_function_source.py`: found by number, comments stripped, any spelling of the table name, an alias, VALUES or SELECT, the last
    INSERT of the last definition, and a definition it cannot read is an ERROR), and fails any key that is not a column in it. The only keys allowed to
    be missing are named here with the reason, and the list is empty. The test double stores no more than that list (`tests/e2e_harness.py`), so a mock
    test that reads a key the real function drops fails too. The real-Postgres half (the call stores them, and the stored id is the entry's
    `source_id`) is `test_574_..._pg.py`.
"""
import ast
from pathlib import Path

import pytest

from tests import _receipt_function_source as src

API = Path(__file__).resolve().parents[1]
SERVICE = API / "services" / "receipt_service.py"

#: Keys the service sends that the function deliberately does not store, each with the reason. None.
NOT_STORED: dict[str, str] = {}


def _payload_keys() -> set[str]:
    tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "create_receipt_core":
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "receipt_payload" for t in node.targets) \
                        and isinstance(node.value, ast.Dict):
                    return {k.value for k in node.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    raise AssertionError("create_receipt_core no longer builds a `receipt_payload` dict literal: this guard must be pointed at the new shape")


def test_the_payload_has_keys_and_the_function_has_columns():
    keys, (name, cols) = _payload_keys(), src.current_columns()
    assert {"id", "firm_id", "client_id", "bank_account_id", "gst_rate_bps", "place_of_supply", "is_interstate"} <= keys, (
        "the payload lost a key this guard exists for, or the service was restructured")
    assert {"firm_id", "client_id", "journal_entry_id"} <= set(cols), (name, cols)


def test_every_key_the_service_sends_is_a_column_the_function_stores():
    keys, (name, cols) = _payload_keys(), src.current_columns()
    dropped = sorted(k for k in keys if k not in cols and k not in NOT_STORED)
    assert not dropped, (
        f"create_receipt_core sends {dropped} in the receipt payload, and the last definition of the receipt function ({name}) does not store "
        "them: the function drops them without an error. Add them to its INSERT in a new migration (derive the body from that one, found by "
        "number), or name the key in NOT_STORED with the reason.")


def test_a_key_named_as_not_stored_is_really_sent_and_really_not_stored():
    keys, (_name, cols) = _payload_keys(), src.current_columns()
    for k, why in NOT_STORED.items():
        assert why.strip() and k in keys and k not in cols, f"{k} no longer needs an exemption"


# ── the reader is not fooled: each case below is a way the function could drop a key that a naive reader would miss ──────────────────

def _body(insert: str, name: str = "settle_receipt_atomic__unguarded") -> str:
    return f"CREATE OR REPLACE FUNCTION public.{name}(p jsonb) RETURNS jsonb LANGUAGE plpgsql AS $$ BEGIN {insert}; END $$;"


FULL = "INSERT INTO public.receipts (id, firm_id, bank_account_id) VALUES (1, 2, 3)"
MISSING = "INSERT INTO public.receipts (id, firm_id) VALUES (1, 2)"


@pytest.mark.parametrize("label, insert", [
    ("the table spelled without its schema", "INSERT INTO receipts (id, firm_id) VALUES (1, 2)"),
    ("an alias", "INSERT INTO public.receipts AS r (id, firm_id) VALUES (1, 2)"),
    ("a quoted table name", 'INSERT INTO public."receipts" (id, firm_id) VALUES (1, 2)'),
    ("a SELECT instead of VALUES", "INSERT INTO public.receipts (id, firm_id) SELECT 1, 2"),
])
def test_a_later_definition_in_another_spelling_is_still_read_and_its_missing_column_is_seen(label, insert):
    files = {"574_a.sql": _body(FULL), "576_b.sql": _body(insert)}
    name, cols = src.last_body_columns(files)
    assert name == "576_b.sql" and "bank_account_id" not in cols, label


def test_two_definitions_in_one_file_the_later_one_counts():
    files = {"574_a.sql": _body(FULL) + "\n" + _body(MISSING)}
    assert "bank_account_id" not in src.last_body_columns(files)[1]


def test_two_inserts_in_one_definition_the_last_one_counts():
    files = {"574_a.sql": _body(FULL + "; " + MISSING)}
    assert "bank_account_id" not in src.last_body_columns(files)[1]


def test_a_comment_that_quotes_a_full_insert_is_not_the_insert():
    files = {"574_a.sql": "-- INSERT INTO public.receipts (id, firm_id, bank_account_id) VALUES (1,2,3)\n/* INSERT INTO public.receipts (bank_account_id) SELECT 1 */\n"
                          + _body(MISSING)}
    assert "bank_account_id" not in src.last_body_columns(files)[1]


def test_a_backfill_insert_outside_any_function_is_not_the_functions():
    files = {"574_a.sql": _body(MISSING), "575_b.sql": "INSERT INTO public.receipts (id, firm_id, bank_account_id) VALUES (1, 2, 3);"}
    name, cols = src.last_body_columns(files)
    assert name == "574_a.sql" and "bank_account_id" not in cols


def test_the_wrapper_is_not_the_body():
    wrapper = ("CREATE OR REPLACE FUNCTION public.settle_receipt_atomic(p jsonb) RETURNS jsonb LANGUAGE plpgsql AS $$ BEGIN "
               "RETURN public.settle_receipt_atomic__unguarded(p); END $$;")
    files = {"574_a.sql": _body(MISSING), "575_b.sql": wrapper}
    assert src.last_body_columns(files)[0] == "574_a.sql"


def test_a_later_definition_of_the_body_that_cannot_be_read_is_an_error_not_a_reason_to_trust_the_earlier_one():
    files = {"574_a.sql": _body(FULL), "576_b.sql": _body("PERFORM public.store_the_receipt(p)")}
    with pytest.raises(AssertionError, match="holds no INSERT INTO receipts"):
        src.last_body_columns(files)


def test_before_the_rename_the_plain_function_is_the_body():
    files = {"235_a.sql": _body(FULL, "settle_receipt_atomic")}
    assert src.last_body_columns(files) == ("235_a.sql", ["id", "firm_id", "bank_account_id"])
