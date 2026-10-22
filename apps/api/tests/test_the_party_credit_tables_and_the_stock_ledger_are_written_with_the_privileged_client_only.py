"""The party-credit tables and the stock ledger are written with the privileged client, and by nothing else (ledger POST-A-299).

THE DEFECT
    `party_credit_balances` (the figure `apply_credit` trusts to settle a document), `party_credit_ledger` (the trail behind it)
    and `inventory_stock_ledger` (the chain every movement is priced from, whose deltas tie to the Inventory control account)
    are writable by every signed-in member of the firm: a firm policy and nothing else. The migration that follows this change
    revokes the writes from `authenticated`, so their writers have to be on the privileged client BEFORE it applies, or every
    movement and credit operation answers 42501 in production while passing in mock mode (a double accepts any caller). The
    privileged client is a superset of what the request's client could write, so this change is safe on today's grants too. The
    real-Postgres half is the file of the migration.

WHAT IS HELD (no database)
    * (source, derived from the AST of every module of the API, `scripts/` included) the only code that writes the three tables is
      the set of functions named below, each through the client its helper returned (`_credit_db` in the credit service,
      `ledger_writer` in the inventory service) and never through the `db` it was handed; a query kept in a variable, the table's
      name held in a constant, `.from_`, a module-level statement and SQL text are each shown to the detector and each must fire;
    * the two helpers are the only functions of those modules that name a privileged client (by the accessor names listed in the
      test, however imported), and the privileged receiver is used ONLY to write the three tables: a read, a compare-and-set on
      the catalogue or a document-table update moved onto it would take row security away from a statement that relies on it;
    * `demo_filings` is read and written by nothing, in the API or in the browser, and the browser does not `.from()` the others;
    * the helpers hand out the privileged client where there is one, the request's own where there is none (mock mode), and
      `None` stays `None`;
    * driven end to end through a request client that REFUSES the tables' writes the way `authenticated` will, every credit
      operation and every stock movement still succeeds and every write lands on the privileged client; and each statement of
      the credit service that the privileged client runs names the firm and the client, because the privileged client does not
      carry row security.
"""
from __future__ import annotations

import ast
import re
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException

import core.db_provider
import domain.inventory_service as inventory_service
import services.inventory_location_service as location_service
from services.party_credit_service import _credit_db, party_credit_service as PCS
from tests._table_uses import WRITE_VERBS, sources as _sources, uses as _uses
from tests.e2e_harness import FakeDB

API_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = API_ROOT.parents[1] / "apps" / "web"

CREDIT_FILE = "services/party_credit_service.py"
STOCK_FILES = ("domain/inventory_service.py", "services/inventory_location_service.py")
# table -> {file: the set of functions that write it}
EXPECTED_WRITERS = {
    "party_credit_balances": {CREDIT_FILE: {"grant_credit", "revoke_credit", "apply_credit", "_restore_balance"}},
    "party_credit_ledger": {CREDIT_FILE: {"grant_credit", "revoke_credit", "apply_credit"}},
    "inventory_stock_ledger": {
        "domain/inventory_service.py": {"_insert_and_cache", "_set_ledger_journal_entry_id", "seed_opening_balances_batch"},
        "services/inventory_location_service.py": {"transfer"},
    },
}
FIRM, CLIENT, OTHER_CLIENT, CUST = "firm-credit-stock", "client-credit-stock", "client-other", "cust-1"


def test_only_the_named_functions_write_each_table_and_no_spelling_hides_a_write():
    found: dict[str, dict[str, set]] = {t: {} for t in EXPECTED_WRITERS}
    hidden = []
    for rel, text in _sources():
        for table in EXPECTED_WRITERS:
            if table not in text:
                continue
            for kind, fn, line, _receiver, _verbs in _uses(text, table):
                if kind == "write":
                    found[table].setdefault(rel, set()).add(fn)
                elif kind in {"unchained", "named", "raw_write"}:
                    hidden.append((rel, line, table, kind))
    assert not hidden, (f"these places name a table in a way the guard cannot read ({hidden}): a query kept in a variable, the "
                        "name held in a constant, or SQL text. Chain the verb off `.table(\"<table>\")` where it is used.")
    assert found == EXPECTED_WRITERS, found


def test_the_guard_sees_every_shape_a_write_can_take():
    for table in EXPECTED_WRITERS:
        shapes = {
            "a query kept in a variable": f'def f(db):\n    q = db.table("{table}")\n    q.update({{}}).execute()\n',
            "the name held in a constant": f'T = "{table}"\n\ndef f(db):\n    db.table(T).delete().execute()\n',
            "from_ instead of table": f'def f(db):\n    db.from_("{table}").insert({{}}).execute()\n',
            "a statement at module level": f'client.table("{table}").update({{}}).execute()\n',
            "an upsert": f'def f(db):\n    db.table("{table}").upsert({{}}).execute()\n',
            "raw SQL": f'def f(cur):\n    cur.execute("DELETE FROM public.{table} WHERE true")\n',
            "raw SQL, lower case": f'SQL = "update {table} set x = 1"\n',
        }
        for label, source in shapes.items():
            kinds = {k for k, *_ in _uses(source, table)}
            assert kinds & {"write", "unchained", "named", "raw_write"}, f"the guard is blind to: {label} ({table})"
        assert [k for k, *_ in _uses(f'def f(db):\n    return db.table("{table}").select("*").execute()\n', table)] == ["read"]
        assert list(_uses(f'def f():\n    """DELETE FROM {table} is what nobody does."""\n', table)) == []


def test_the_walk_reads_enough_modules_to_mean_something():
    rels = [rel for rel, _ in _sources()]
    assert len(rels) > 300, len(rels)
    assert any(r.startswith("scripts/") for r in rels), "the scripts directory is not walked: a one-off writer would pass"
    assert CREDIT_FILE in rels and all(f in rels for f in STOCK_FILES)


def test_each_write_goes_through_the_client_its_helper_returned_and_never_the_one_it_was_handed():
    """A write on `db` itself is the defect; so is a helper called after the write, and so is the helper's name being re-bound
    to something else in the same function."""
    allowed_name = {CREDIT_FILE: "wdb", "domain/inventory_service.py": None, "services/inventory_location_service.py": "writer"}
    for table, files in EXPECTED_WRITERS.items():
        for rel in files:
            text = (API_ROOT / rel).read_text(encoding="utf-8")
            tree = ast.parse(text)
            for kind, fn, line, receiver, _verbs in _uses(text, table):
                if kind != "write":
                    continue
                ok = isinstance(receiver, ast.Name) and receiver.id == allowed_name[rel]
                ok = ok or (isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Name) and receiver.func.id == "ledger_writer")
                assert ok, f"{rel}:{line} {fn} writes {table} through {ast.dump(receiver)[:80]}"
                if isinstance(receiver, ast.Name):
                    fdef = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn)
                    helper = "_credit_db" if rel == CREDIT_FILE else "ledger_writer"
                    bindings = [a for a in ast.walk(fdef) if isinstance(a, ast.Assign)
                                and any(isinstance(t, ast.Name) and t.id == receiver.id for t in a.targets)]
                    assert bindings, f"{rel} {fn}: {receiver.id} is never assigned"
                    assert all(isinstance(a.value, ast.Call) and isinstance(a.value.func, ast.Name) and a.value.func.id == helper
                               for a in bindings), f"{rel} {fn}: {receiver.id} is bound to something other than {helper}(...)"
                    assert min(a.lineno for a in bindings) < line, f"{rel} {fn}: {receiver.id} is bound after its first write"


def test_the_privileged_receivers_are_used_only_to_write_the_protected_tables():
    """The privileged client carries no row security, so it must not be handed a statement that relies on it: a READ of a
    protected table, the compare-and-set on the item's catalogue row (whose row-security confinement is the argument that the
    ledger row written next is for an item the caller can reach) or the update of a document table all stay on the caller's
    client. Every `.table(...)` called on a receiver that came from the helper must name one of the three tables and chain a
    write verb."""
    seen = 0
    for rel in (CREDIT_FILE, *STOCK_FILES):
        tree = ast.parse((API_ROOT / rel).read_text(encoding="utf-8"))
        parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}

        def is_helper_call(node):
            return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"_credit_db", "ledger_writer"}

        bound = {t.id for a in ast.walk(tree) if isinstance(a, ast.Assign) and is_helper_call(a.value)
                 for t in a.targets if isinstance(t, ast.Name)}
        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in {"table", "from_"}):
                continue
            receiver = call.func.value
            if not (is_helper_call(receiver) or (isinstance(receiver, ast.Name) and receiver.id in bound)):
                continue
            seen += 1
            name = call.args[0].value if call.args and isinstance(call.args[0], ast.Constant) else None
            assert name in EXPECTED_WRITERS, f"{rel}:{call.lineno} the privileged client is used on {name!r}, which is not one of the three tables"
            verbs, up = [], call
            while isinstance(parents.get(up), ast.Attribute) and isinstance(parents.get(parents[up]), ast.Call):
                verbs.append(parents[up].attr)
                up = parents[parents[up]]
            assert set(verbs) & WRITE_VERBS, f"{rel}:{call.lineno} the privileged client READS {name} (chain: {verbs}); reads stay on the caller's client"
    assert seen >= 10, seen            # the walk found the writers: a vacuous pass would find none


PRIVILEGED_NAMES = {"service_db", "service_db_or_none", "service_db_or_503", "get_service_supabase", "_service_client"}


def test_the_credit_and_stock_helpers_are_the_only_functions_that_name_a_privileged_client_in_those_modules():
    """However it is imported or spelled: an attribute (`db_provider.service_db`), a bare name (`from core.db_provider import
    service_db_or_none`) or an import alias."""
    for rel in (CREDIT_FILE, *STOCK_FILES):
        tree = ast.parse((API_ROOT / rel).read_text(encoding="utf-8"))
        namers = set()
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for node in ast.walk(fn):
                name = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else None
                if name in PRIVILEGED_NAMES:
                    namers.add(fn.name)
                if isinstance(node, (ast.ImportFrom, ast.Import)):
                    if any(a.name.split(".")[-1] in PRIVILEGED_NAMES for a in node.names):
                        namers.add(fn.name)
        top = [n for n in tree.body if isinstance(n, (ast.ImportFrom, ast.Import))
               and any(a.name.split(".")[-1] in PRIVILEGED_NAMES for a in n.names)]
        assert not top, (rel, "a module-level import of a privileged client accessor")
        assert namers <= {"_credit_db", "ledger_writer"}, (rel, namers)


def test_nothing_in_the_browser_reads_or_writes_the_tables_directly():
    """Stricter than the rule on purpose: SELECT stays granted (the API reads under the caller's sign-in), but nothing in the
    browser has a reason to read these tables, and a first read there would be a second reader that bypasses the routes' checks."""
    pattern = re.compile(r"""\.from\(\s*["'`](%s)["'`]""" % "|".join([*EXPECTED_WRITERS, "demo_filings"]))
    hits = []
    for path in WEB_ROOT.rglob("*"):
        if path.suffix not in {".ts", ".tsx"} or "node_modules" in path.parts or ".next" in path.parts:
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            hits.append(path.relative_to(WEB_ROOT).as_posix())
    assert not hits, hits


def test_demo_filings_is_read_and_written_by_nothing_in_the_api():
    """A sandbox table (migration 087) whose only writer, a browser-side demo, was deleted; the shared filing-demo framework
    writes nothing. Naming it anywhere in the API means somebody has started to use it again."""
    hits = [rel for rel, text in _sources() if "demo_filings" in text]
    assert not hits, hits


# ── the helpers ──────────────────────────────────────────────────────────────

class _Marker:
    pass


@pytest.mark.parametrize("helper", [_credit_db, inventory_service.ledger_writer])
def test_the_helpers_hand_out_the_privileged_client_and_keep_none_none(helper, monkeypatch):
    privileged, request = _Marker(), _Marker()
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: privileged)
    assert helper(request) is privileged
    assert helper(None) is None
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: None)
    assert helper(request) is request


# ── a request client that refuses the writes, as `authenticated` now does ─────

class _Recording:
    """Wraps an in-memory double. A write to a protected table is recorded with its filters; with `refuse` it raises as the
    database now does for a signed-in session."""

    def __init__(self, inner, protected, refuse):
        self.inner, self.protected, self.refuse, self.log, self.refused = inner, set(protected), refuse, [], []

    def table(self, name):
        return _Statement(self, self.inner.table(name), name)

    def __getattr__(self, attr):
        return getattr(self.inner, attr)


class _Statement:
    def __init__(self, owner, query, name):
        self._owner, self._query, self._name = owner, query, name
        self._filters, self._verb, self._payload = [], "select", None

    def __getattr__(self, attr):
        target = getattr(self._query, attr)

        def call(*args, **kwargs):
            if attr in WRITE_VERBS:
                self._verb, self._payload = attr, args[0] if args else None
                if self._owner.refuse and self._name in self._owner.protected:
                    # recorded BEFORE it raises, so a writer left on the request's client is seen even where the caller swallows
                    # the refusal (the stock callers do, by design)
                    self._owner.refused.append((self._name, attr))
                    raise RuntimeError(f"permission denied for table {self._name}")
            elif attr in {"eq", "is_", "in_", "gte", "lte", "neq"}:
                self._filters.append((attr, args))
            result = target(*args, **kwargs)
            return self if result is self._query else result
        return call

    def execute(self):
        result = self._query.execute()
        if self._verb in WRITE_VERBS and self._name in self._owner.protected:
            self._owner.log.append({"table": self._name, "verb": self._verb, "filters": list(self._filters),
                                    "payload": self._payload})
        return result


CREDIT_TABLES = {"party_credit_balances", "party_credit_ledger"}
STOCK_AND_CREDIT = CREDIT_TABLES | {"inventory_stock_ledger"}


def _pair(monkeypatch, protected):
    """One in-memory store seen through two clients: the request's (refuses the protected writes) and the privileged one."""
    inner = FakeDB()
    request, privileged = _Recording(inner, protected, True), _Recording(inner, protected, False)
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: privileged)
    return inner, request, privileged


def test_the_refusing_double_refuses_every_write_verb_on_a_protected_table_and_only_there():
    """The double stands in for `authenticated`: if it let a verb through, a writer left on the request's client would pass."""
    inner = FakeDB()
    request = _Recording(inner, STOCK_AND_CREDIT, True)
    for verb in sorted(WRITE_VERBS):
        with pytest.raises(RuntimeError, match="permission denied"):
            getattr(request.table("inventory_stock_ledger"), verb)({})
    assert {v for _t, v in request.refused} == WRITE_VERBS
    before = len(request.refused)
    request.table("service_catalogue").insert({"id": "x", "firm_id": FIRM})       # not protected: allowed
    assert len(request.refused) == before
    privileged = _Recording(inner, STOCK_AND_CREDIT, False)
    privileged.table("inventory_stock_ledger").insert({"id": "y", "firm_id": FIRM}).execute()
    assert privileged.refused == [] and [e["verb"] for e in privileged.log] == ["insert"]


def _invoice(inner, **over):
    return inner.seed("client_sales_invoices", {
        "id": "inv-1", "firm_id": FIRM, "client_id": CLIENT, "customer_id": CUST, "invoice_no": "INV-1",
        "total_paise": 100000, "paid_paise": 0, "status": "issued", **over})


def _statements_name_the_firm_and_client(log, clients=(CLIENT,)):
    for entry in log:
        if entry["verb"] == "update":
            cols = {a[0]: a[1] for kind, a in entry["filters"] if kind == "eq"}
            assert cols.get("firm_id") == FIRM and cols.get("client_id") in clients, entry
        elif entry["verb"] == "insert":
            assert entry["payload"]["firm_id"] == FIRM and entry["payload"]["client_id"] in clients, entry
        else:
            raise AssertionError(f"a {entry['verb']} on {entry['table']} by the privileged client: only inserts and updates are expected, "
                                 f"and a delete or upsert here would carry no firm or client filter: {entry}")


def test_a_grant_an_application_and_a_revocation_succeed_with_a_request_client_that_refuses_the_writes(monkeypatch):
    inner, request, privileged = _pair(monkeypatch, CREDIT_TABLES)
    _invoice(inner)

    PCS.grant_credit(request, FIRM, CLIENT, "customer", CUST, 50000, source_type="bank_overpayment",
                     source_id="txn-1", created_by="u1")
    assert PCS.get_balance(request, FIRM, CLIENT, "customer", CUST) == 50000
    PCS.apply_credit(request, FIRM, CLIENT, "customer", CUST, 20000, "sales_invoice", "inv-1", created_by="u1")
    assert PCS.get_balance(request, FIRM, CLIENT, "customer", CUST) == 30000
    assert next(r for r in inner.rows("client_sales_invoices") if r["id"] == "inv-1")["paid_paise"] == 20000
    PCS.revoke_credit(request, FIRM, CLIENT, "customer", CUST, 30000, source_type="bank_overpayment", source_id="txn-1")
    assert PCS.get_balance(request, FIRM, CLIENT, "customer", CUST) == 0

    assert request.log == [] and request.refused == []                       # nothing was written through the request's client
    kinds = [(e["table"], e["verb"]) for e in privileged.log]
    assert kinds.count(("party_credit_balances", "insert")) == 1
    assert kinds.count(("party_credit_balances", "update")) == 2          # the application and the revocation
    assert kinds.count(("party_credit_ledger", "insert")) == 3
    _statements_name_the_firm_and_client(privileged.log)


def test_a_failed_application_restores_the_balance_through_the_privileged_client(monkeypatch):
    inner, request, privileged = _pair(monkeypatch, CREDIT_TABLES)
    PCS.grant_credit(request, FIRM, CLIENT, "customer", CUST, 50000, source_type="bank_overpayment")
    with pytest.raises(HTTPException):
        PCS.apply_credit(request, FIRM, CLIENT, "customer", CUST, 20000, "sales_invoice", "no-such-invoice")
    assert PCS.get_balance(request, FIRM, CLIENT, "customer", CUST) == 50000      # restored
    assert request.log == [] and request.refused == []
    updates = [e for e in privileged.log if e["table"] == "party_credit_balances" and e["verb"] == "update"]
    assert len(updates) == 2                                                       # the decrement and the compensation
    _statements_name_the_firm_and_client(privileged.log)


def test_the_credit_of_another_client_is_not_touched_by_a_write_for_this_one(monkeypatch):
    inner, request, privileged = _pair(monkeypatch, CREDIT_TABLES)
    PCS.grant_credit(request, FIRM, OTHER_CLIENT, "customer", CUST, 9000, source_type="bank_overpayment")
    PCS.grant_credit(request, FIRM, CLIENT, "customer", CUST, 5000, source_type="bank_overpayment")
    PCS.grant_credit(request, FIRM, CLIENT, "customer", CUST, 1000, source_type="bank_overpayment")
    assert PCS.get_balance(request, FIRM, OTHER_CLIENT, "customer", CUST) == 9000
    assert PCS.get_balance(request, FIRM, CLIENT, "customer", CUST) == 6000
    # the second grant to the same party is an UPDATE of the balance, and it names the firm and the client
    updates = [e for e in privileged.log if e["table"] == "party_credit_balances" and e["verb"] == "update"]
    assert len(updates) == 1 and dict(a[0:2] for _k, a in updates[0]["filters"]).get("client_id") == CLIENT, updates
    _statements_name_the_firm_and_client(privileged.log, clients=(CLIENT, OTHER_CLIENT))


def test_with_no_privileged_client_the_credit_service_writes_through_the_requests_own(monkeypatch):
    inner = FakeDB()
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: None)
    PCS.grant_credit(inner, FIRM, CLIENT, "customer", CUST, 5000, source_type="bank_overpayment")
    assert PCS.get_balance(inner, FIRM, CLIENT, "customer", CUST) == 5000


# ── the stock ledger ─────────────────────────────────────────────────────────

STOCK = {"inventory_stock_ledger"}


def _item(inner, item_id="item-1"):
    inner.seed("service_catalogue", {"id": item_id, "firm_id": FIRM, "client_id": CLIENT, "name": "Widget",
                                     "kind": "good", "stock_qty_units": "0", "avg_cost_paise": 0})


def test_stock_in_and_out_write_the_ledger_through_the_privileged_client(monkeypatch):
    inner, request, privileged = _pair(monkeypatch, STOCK)
    _item(inner)
    row = inventory_service.record_stock_in(
        request, firm_id=FIRM, client_id=CLIENT, service_catalogue_id="item-1", movement_date="2026-04-10",
        quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="purchase", source_type="purchase_bill",
        source_id="bill-1", reference_no="BILL-1")
    assert row["running_qty_units"] == "10"
    out = inventory_service.record_stock_out(
        request, firm_id=FIRM, client_id=CLIENT, service_catalogue_id="item-1", movement_date="2026-04-15",
        quantity=Decimal("3"), movement_type="sale", source_type="sales_invoice", source_id="inv-1", reference_no="INV-1")
    assert out["running_qty_units"] == "7"
    assert request.log == [] and request.refused == []
    assert [(e["table"], e["verb"]) for e in privileged.log] == [("inventory_stock_ledger", "insert")] * 2
    assert all(e["payload"]["firm_id"] == FIRM and e["payload"]["client_id"] == CLIENT for e in privileged.log)
    # the item's cached columns are the caller's own statement, and they moved
    assert inner.rows("service_catalogue")[0]["stock_qty_units"] == "7"


def test_the_journal_link_is_backfilled_through_the_privileged_client(monkeypatch):
    inner, request, privileged = _pair(monkeypatch, STOCK)
    row = inner.seed("inventory_stock_ledger", {"firm_id": FIRM, "client_id": CLIENT, "service_catalogue_id": "item-1",
                                                "journal_entry_id": None})
    inventory_service._set_ledger_journal_entry_id(request, row["id"], "je-1")
    assert inner.rows("inventory_stock_ledger")[0]["journal_entry_id"] == "je-1"
    assert [(e["table"], e["verb"]) for e in privileged.log] == [("inventory_stock_ledger", "update")]
    assert request.log == [] and request.refused == []


def test_a_transfer_writes_both_of_its_rows_through_the_privileged_client(monkeypatch):
    inner, request, privileged = _pair(monkeypatch, STOCK)
    inner.seed("godowns", {"id": "g1", "firm_id": FIRM, "client_id": CLIENT, "name": "Bhiwandi", "state_code": "27",
                           "gstin": "27AAACA1234A1Z5", "is_default": True, "is_active": True})
    inner.seed("godowns", {"id": "g2", "firm_id": FIRM, "client_id": CLIENT, "name": "Hosur", "state_code": "29",
                           "gstin": "29AAACA1234A1Z2", "is_default": False, "is_active": True})
    inner.seed("service_catalogue", {"id": "i1", "firm_id": FIRM, "client_id": CLIENT, "name": "Widget", "kind": "good",
                                     "unit": "NOS"})
    inner.seed("inventory_stock_ledger", {
        "firm_id": FIRM, "client_id": CLIENT, "service_catalogue_id": "i1", "movement_date": "2026-01-01",
        "movement_type": "purchase", "quantity_delta": "100", "value_delta_paise": 10_000_00, "godown_id": "g1",
        "batch_id": None})
    out = location_service.transfer(request, firm_id=FIRM, client_id=CLIENT, service_catalogue_id="i1",
                                    from_godown_id="g1", to_godown_id="g2", quantity="40", movement_date="2026-02-01")
    assert out["ok"] is True
    assert [(e["table"], e["verb"]) for e in privileged.log] == [("inventory_stock_ledger", "insert")] * 2
    assert request.log == [] and request.refused == []


def test_the_opening_balance_batch_writes_its_ledger_rows_through_the_privileged_client(monkeypatch):
    from tests.test_inventory_opening_stock_journal import _seed_coa, _seed_item, _wire
    inner, request, privileged = _pair(monkeypatch, STOCK)
    _wire(monkeypatch, inner)
    _seed_coa(inner, firm_id="firm-inv-1", client_id="client-inv-1")
    rows = []
    for _ in range(3):
        item_id = str(uuid.uuid4())
        _seed_item(inner, item_id)
        rows.append({"id": item_id, "client_id": "client-inv-1", "kind": "good", "opening_qty_units": "10",
                     "opening_cost_paise": 100_00, "created_at": "2026-04-01T00:00:00Z"})
    inventory_service.seed_opening_balances_batch(request, firm_id="firm-inv-1", created_by="user-1", rows=rows)
    assert len(inner.rows("inventory_stock_ledger")) == 3          # the batch never raises, so the rows are the proof
    assert [(e["table"], e["verb"]) for e in privileged.log] == [("inventory_stock_ledger", "insert")]
    assert request.log == [] and request.refused == []


def test_with_no_privileged_client_the_stock_ledger_is_written_through_the_requests_own(monkeypatch):
    inner = FakeDB()
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: None)
    _item(inner)
    inventory_service.record_stock_in(
        inner, firm_id=FIRM, client_id=CLIENT, service_catalogue_id="item-1", movement_date="2026-04-10",
        quantity=Decimal("1"), total_cost_paise=100_00, movement_type="purchase", source_type="purchase_bill",
        source_id="b", reference_no="B")
    assert len(inner.rows("inventory_stock_ledger")) == 1
