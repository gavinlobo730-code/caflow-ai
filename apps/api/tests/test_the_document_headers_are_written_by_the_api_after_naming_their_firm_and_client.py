"""An UPDATE or DELETE of a document header names the document, its firm AND its client, and is made by the API (POST-A-335, part 2).

THE DEFECT
    The six headers (`client_sales_invoices`, `purchase_bills`, `credit_notes`, `debit_notes`, `purchase_credit_notes`,
    `sales_debit_notes`) and their lines were written on the caller's own session, so a member who held the accounting tier could change
    a DRAFT's particulars over PostgREST and skip the API's checks (migration 541 froze an ISSUED document and 544 sealed the settlement
    columns; the draft was the part left). The API now writes them with the privileged client, which carries no row security, so the
    filters on the statement are the only confinement it has: a header UPDATE or DELETE has to name the document, the firm and the client.

WHAT IS HELD (no database)
    * every UPDATE, DELETE or UPSERT chained off `.table("<header>")` anywhere in the API's source has an `.eq("firm_id", ...)` and an
      `.eq("client_id", ...)` in its chain. A statement the reader cannot see into (the table held in a variable) fails the rule
      through the table-use scanner, which `test_a_write_of_a_table_the_signed_in_role_cannot_write_is_made_on_a_client_that_can`
      also runs; the detector is shown the shapes it must read and the ones it must leave alone.
    * the lines tables carry no firm of their own, so they are held by the other half: their writers are on the privileged client
      (the rule above, with the twelve tables on `tests/fixtures/tables_about_to_be_closed.txt`) and the parent they are confined to
      was read under the firm and the client first.

WHAT IT CANNOT SEE
    A filter added by a helper the chain is passed through, an INSERT (the row names its own firm and client, and the columns are
    NOT NULL), and the value the filter compares with.
"""
from __future__ import annotations

import ast
import textwrap

from tests._call_graph import chain_of
from tests._table_uses import API_ROOT, sources

HEADERS = ("client_sales_invoices", "purchase_bills", "credit_notes", "debit_notes", "purchase_credit_notes", "sales_debit_notes")
VERBS = ("update", "delete", "upsert")


def _eq_columns(call: ast.Call) -> set[str]:
    cols = set()
    for method, link in chain_of(call):
        if method in {"eq", "match"} and link.args and isinstance(link.args[0], ast.Constant) and isinstance(link.args[0].value, str):
            cols.add(link.args[0].value)
        if method == "match" and link.args and isinstance(link.args[0], ast.Dict):
            cols |= {k.value for k in link.args[0].keys if isinstance(k, ast.Constant)}
    return cols


def statements(source: str):
    """(line, table, verb, columns named by an eq) for every chain off a header table that updates, deletes or upserts."""
    out = []
    tree = ast.parse(source)
    inner = {id(c) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) for c in [n.func.value]
             if isinstance(c, ast.Call)}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or id(node) in inner:
            continue                                       # only the outermost call of a chain
        chain = chain_of(node)
        table = next((link.args[0].value for method, link in chain
                      if method in {"table", "from_"} and link.args and isinstance(link.args[0], ast.Constant)), None)
        verb = next((method for method, _ in chain if method in VERBS), None)
        if table in HEADERS and verb:
            out.append((node.lineno, table, verb, _eq_columns(node)))
    return out


def test_every_update_and_delete_of_a_header_names_the_document_its_firm_and_its_client():
    bad, seen = [], 0
    for rel, text in sources():
        if not any(t in text for t in HEADERS):
            continue
        for line, table, verb, cols in statements(text):
            seen += 1
            missing = {"id", "firm_id", "client_id"} - cols
            if missing:
                bad.append(f"{rel}:{line} {verb} of {table} does not name {sorted(missing)}")
    assert seen >= 20, f"only {seen} header writes found: the scan has gone blind"
    assert not bad, ("the privileged client carries no row security, so a header statement has to confine itself to the document, the firm "
                     "and the client:\n  " + "\n  ".join(bad))


def test_the_detector_reads_the_shapes_it_must_and_leaves_the_rest():
    ok = textwrap.dedent('''
        def f(db, i, firm, client):
            privileged_for(db).table("purchase_bills").update({}).eq("id", i).eq("firm_id", firm).eq("client_id", client).execute()
    ''')
    assert statements(ok) == [(3, "purchase_bills", "update", {"id", "firm_id", "client_id"})]
    no_client = ok.replace('.eq("client_id", client)', "")
    assert statements(no_client)[0][3] == {"id", "firm_id"}
    delete = 'def f(db):\n    db.table("credit_notes").delete().eq("id", 1).execute()\n'
    assert [s[2] for s in statements(delete)] == ["delete"]
    assert statements('def f(db):\n    return db.table("credit_notes").select("*").eq("id", 1).execute()\n') == []
    assert statements('def f(db):\n    db.table("customers").update({}).eq("id", 1).execute()\n') == []
    assert statements('def f(db):\n    db.table("credit_notes").insert({}).execute()\n') == []
    via_match = 'def f(db):\n    db.table("debit_notes").update({}).match({"id": 1, "firm_id": 2, "client_id": 3}).execute()\n'
    assert statements(via_match)[0][3] >= {"id", "firm_id", "client_id"}


def test_the_in_flight_list_names_exactly_the_twelve_tables():
    listed = {ln.strip() for ln in (API_ROOT / "tests" / "fixtures" / "tables_about_to_be_closed.txt").read_text().splitlines()
              if ln.strip() and not ln.startswith("#")}
    closed = {ln.strip() for ln in (API_ROOT / "tests" / "fixtures" / "tables_the_signed_in_role_cannot_write.txt").read_text().splitlines()
              if ln.strip() and not ln.startswith("#")}
    assert listed == set(HEADERS) | {"client_sales_invoice_lines", "purchase_bill_lines", "credit_note_lines", "debit_note_lines",
                                     "purchase_credit_note_lines", "sales_debit_note_lines"}
    assert not listed & closed, "a table is on both lists: the migration that closes it moves it, it does not copy it"
