"""The party-credit tables, the stock ledger and the item's cached stock figures are written with the privileged client, and by nothing else
(ledger POST-A-299 and POST-A-327).

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
    * the item's CACHED STOCK FIGURES (`service_catalogue.stock_qty_units`, `avg_cost_paise`, `stock_version`, a copy of the
      ledger's last row, which the catalogue's Stock column, the product form's "stock already started" gate, the item ledger's
      item block and the stock reconciliation show; the stock register, the reorder check and the next movement's cost read the
      LEDGER) are written by three functions only, through the same helper: the movement's compare-and-set, its restore after a
      refused ledger insert, and the opening-stock batch's upsert (`_write_opening_cache`, fed by `seed_opening_balances_batch`). The privileged client carries no row security, so the first two name the firm and the
      client, and the batch hands the upsert only the rows whose id the caller's own client reads as that firm's and that
      client's. A catalogue edit of anything else (the name, the rate) stays on the request's client;
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


CACHE_COLUMNS = {"stock_qty_units", "avg_cost_paise", "stock_version"}
# the only functions that WRITE the item's cached stock figures (a statement on the catalogue chained off the privileged helper)
CACHE_WRITERS = {("domain/inventory_service.py", "_insert_and_cache"), ("domain/inventory_service.py", "_restore_stock_cache_from_ledger"),
                 ("domain/inventory_service.py", "_write_opening_cache")}
# the only functions that BUILD a cache column as a value to store (a payload may be handed to a writer in another function)
CACHE_BUILDERS = {("domain/inventory_service.py", "_insert_and_cache"), ("domain/inventory_service.py", "_restore_stock_cache_from_ledger"),
                  ("domain/inventory_service.py", "seed_opening_balances_batch")}
# functions that put the ledger's figure under one of those names to SHOW it, and write nothing: a response overlay and a report's own
# `avg_cost_paise`. A new one is classified here with its reason, or it is a builder above.
CACHE_DISPLAYS = {("routers/inventory.py", "list_stock_items"): "the stock register shows the ledger's last row under the cache's names",
                  ("domain/reporting/stock_position.py", "position"): "a report's own average cost, summed from the ledger"}


def _enclosing_function(node, parents):
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return "<module>"


def _chain(call, parents):
    """Every (verb, call node) chained off a `.table(...)` call, in order."""
    out, up = [], call
    while isinstance(parents.get(up), ast.Attribute) and isinstance(parents.get(parents[up]), ast.Call):
        out.append((parents[up].attr, parents[parents[up]]))
        up = parents[parents[up]]
    return out


def _eq_columns(chain):
    return {c.args[0].value for verb, c in chain if verb == "eq" and c.args and isinstance(c.args[0], ast.Constant)}


def test_the_privileged_receivers_are_used_only_to_write_the_protected_tables_and_the_items_cache():
    """The privileged client carries no row security, so it must not be handed a statement that relies on it: a READ of a
    protected table or the update of a document table stays on the caller's client. Every `.table(...)` called on a receiver
    that came from the helper must name one of the three tables and chain a write verb, or be the item's cache: an UPDATE that
    names the firm and the client (the compare-and-set and its restore) or the opening batch's UPSERT, which is handed only the
    rows the caller's client has read as this client's."""
    seen = catalogue = 0
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
            chain = _chain(call, parents)
            verbs = [v for v, _c in chain]
            if name == "service_catalogue":
                catalogue += 1
                fn = _enclosing_function(call, parents)
                assert (rel, fn) in CACHE_WRITERS, f"{rel}:{call.lineno} {fn} writes the item's cache with the privileged client and is not named"
                if "update" in verbs:
                    assert {"firm_id", "client_id"} <= _eq_columns(chain), (
                        f"{rel}:{call.lineno} {fn} updates the item's cache with a client that has no row security and does not name the "
                        f"firm and the client (filters: {sorted(_eq_columns(chain))})")
                else:
                    assert verbs[:1] == ["upsert"] and fn == "_write_opening_cache", (rel, call.lineno, fn, verbs)
                continue
            assert name in EXPECTED_WRITERS, f"{rel}:{call.lineno} the privileged client is used on {name!r}, which is not one of the three tables"
            assert set(verbs) & WRITE_VERBS, f"{rel}:{call.lineno} the privileged client READS {name} (chain: {verbs}); reads stay on the caller's client"
    assert seen >= 14 and catalogue >= 4, (seen, catalogue)       # the walk found the writers: a vacuous pass would find none


def _cache_mentions(source: str):
    """(function, line, shape) for every place a module builds one of the cache columns as a value to store: a dict key, a
    subscript assignment or a keyword argument."""
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value in CACHE_COLUMNS:
                    yield _enclosing_function(node, parents), key.lineno, "dict key"
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
            if isinstance(node.slice, ast.Constant) and node.slice.value in CACHE_COLUMNS:
                yield _enclosing_function(node, parents), node.lineno, "subscript assignment"
        elif isinstance(node, ast.keyword) and node.arg in CACHE_COLUMNS:
            yield _enclosing_function(node, parents), node.value.lineno, "keyword argument"


def _cache_builders(text: str) -> set:
    """The functions of a module that build one of the cache columns as a value to store (a dict key, a subscript assignment, a
    keyword argument), whether or not they write the catalogue themselves: a payload built in one function and handed to a
    writer in another is the shape that a rule on "writes the catalogue AND names the column" would miss."""
    return {fn for fn, *_ in _cache_mentions(text)}


def test_only_three_functions_build_the_items_cached_stock_figures_and_no_spelling_hides_one():
    """Every function that builds a cache column as a value to store is one of the named three, or is a named display (the stock
    register shows the ledger's figure under those names; a report has an `avg_cost_paise` of its own) that writes nothing. A
    pydantic field of that name would let a request body carry the figure into an update, so none may exist."""
    found, fields = set(), []
    for rel, text in _sources():
        if not any(c in text for c in CACHE_COLUMNS):
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                fields += [(rel, node.name, st.target.id) for st in node.body
                           if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.target.id in CACHE_COLUMNS]
        found |= {(rel, fn) for fn in _cache_builders(text)}
    assert not fields, f"a request model or class declares a cache column: {fields}"
    assert found - set(CACHE_DISPLAYS) == CACHE_BUILDERS, found
    assert set(CACHE_DISPLAYS) <= found, "a named display no longer builds those names: take it off the list"


def test_the_cache_guard_sees_every_shape_a_cache_write_can_take():
    shapes = {
        "a dict key": 'def f(db):\n    db.table("service_catalogue").update({"stock_qty_units": 1}).execute()\n',
        "a subscript assignment": 'def f(db):\n    p = {}\n    p["stock_version"] = 1\n    return p\n',
        "a keyword argument": 'def f(db):\n    db.table("service_catalogue").update(dict(avg_cost_paise=1)).execute()\n',
        "the table held in a constant": 'T = "service_catalogue"\n\ndef f(db):\n    db.table(T).update({"stock_version": 1}).execute()\n',
        "an upsert": 'def f(db):\n    db.table("service_catalogue").upsert([{"stock_qty_units": 1}]).execute()\n',
        "a payload built here and written elsewhere": 'def build():\n    return {"stock_version": 1, "avg_cost_paise": 2}\n',
    }
    for label, source in shapes.items():
        assert _cache_builders(source), f"the cache guard is blind to: {label}"
    reader = 'def f(db):\n    rows = db.table("service_catalogue").select("id").execute().data\n    return [r["stock_qty_units"] for r in rows]\n'
    assert _cache_builders(reader) == set(), "reading a cache column is not building one"


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

    def __init__(self, inner, protected, refuse, guard_cache=False):
        self.inner, self.protected, self.refuse, self.log, self.refused = inner, set(protected), refuse, [], []
        self.guard_cache = guard_cache

    def covers(self, name, payload) -> bool:
        """Is this write one the database now refuses a signed-in session: a protected table, or (with `guard_cache`) an
        update or upsert of the catalogue that names one of the item's cached stock columns."""
        if name in self.protected:
            return True
        if self.guard_cache and name == "service_catalogue":
            rows = payload if isinstance(payload, list) else [payload]
            return any(isinstance(r, dict) and CACHE_COLUMNS & set(r) for r in rows)
        return False

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
                if self._owner.refuse and self._owner.covers(self._name, self._payload):
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
        if self._verb in WRITE_VERBS and self._owner.covers(self._name, self._payload):
            self._owner.log.append({"table": self._name, "verb": self._verb, "filters": list(self._filters),
                                    "payload": self._payload})
        return result


CREDIT_TABLES = {"party_credit_balances", "party_credit_ledger"}
STOCK_AND_CREDIT = CREDIT_TABLES | {"inventory_stock_ledger"}


def _pair(monkeypatch, protected, guard_cache=False):
    """One in-memory store seen through two clients: the request's (refuses the protected writes) and the privileged one."""
    inner = FakeDB()
    request, privileged = _Recording(inner, protected, True, guard_cache), _Recording(inner, protected, False, guard_cache)
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


# ── the item's cached stock figures ──────────────────────────────────────────

def _cache_updates(log):
    return [e for e in log if e["table"] == "service_catalogue"]


def test_the_double_refuses_a_cache_write_and_lets_a_catalogue_edit_through():
    inner = FakeDB()
    inner.seed("service_catalogue", {"id": "item-1", "firm_id": FIRM, "client_id": CLIENT, "name": "Widget", "kind": "good"})
    request = _Recording(inner, set(), True, guard_cache=True)
    for payload in ({"stock_qty_units": "5"}, {"avg_cost_paise": 1}, {"stock_version": 9}):
        with pytest.raises(RuntimeError, match="permission denied"):
            request.table("service_catalogue").update(payload).eq("id", "item-1")
    with pytest.raises(RuntimeError, match="permission denied"):
        request.table("service_catalogue").upsert([{"id": "item-1", "stock_qty_units": "5"}], on_conflict="id")
    # an edit of anything else is the request's own, as before
    request.table("service_catalogue").update({"name": "Gadget"}).eq("id", "item-1").execute()
    assert inner.rows("service_catalogue")[0]["name"] == "Gadget"
    assert len(request.refused) == 4


def test_a_movement_claims_the_items_cache_through_the_privileged_client_and_names_the_firm_and_the_client(monkeypatch):
    inner, request, privileged = _pair(monkeypatch, STOCK, guard_cache=True)
    _item(inner)
    inventory_service.record_stock_in(
        request, firm_id=FIRM, client_id=CLIENT, service_catalogue_id="item-1", movement_date="2026-04-10",
        quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="purchase", source_type="purchase_bill",
        source_id="bill-1", reference_no="BILL-1")
    inventory_service.record_stock_out(
        request, firm_id=FIRM, client_id=CLIENT, service_catalogue_id="item-1", movement_date="2026-04-15",
        quantity=Decimal("3"), movement_type="sale", source_type="sales_invoice", source_id="inv-1", reference_no="INV-1")
    assert request.log == [] and request.refused == []                  # nothing was written through the request's client
    claims = _cache_updates(privileged.log)
    # (an item that never had a version is tried as 0 and then as NULL, so the first movement logs two attempts)
    assert len(claims) >= 2 and all(e["verb"] == "update" for e in claims)
    for entry in claims:
        eq = {a[0]: a[1] for kind, a in entry["filters"] if kind == "eq"}
        assert eq.get("id") == "item-1" and eq.get("firm_id") == FIRM and eq.get("client_id") == CLIENT, entry
    row = inner.rows("service_catalogue")[0]
    assert row["stock_qty_units"] == "7" and row["stock_version"] == 2


def test_an_item_of_another_client_is_not_claimed_by_a_movement_for_this_one(monkeypatch):
    """The compare-and-set used to lean on row security to confine it to the caller's own clients. It names the client now,
    so an item that is somebody else's matches nothing, however the id came to be handed over."""
    inner, request, privileged = _pair(monkeypatch, STOCK, guard_cache=True)
    inner.seed("service_catalogue", {"id": "theirs", "firm_id": FIRM, "client_id": OTHER_CLIENT, "name": "Theirs", "kind": "good",
                                     "stock_qty_units": "4", "avg_cost_paise": 500, "stock_version": 3})
    with pytest.raises(HTTPException):
        inventory_service.record_stock_in(
            request, firm_id=FIRM, client_id=CLIENT, service_catalogue_id="theirs", movement_date="2026-04-10",
            quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="purchase", source_type="purchase_bill",
            source_id="bill-1", reference_no="BILL-1")
    theirs = inner.rows("service_catalogue")[0]
    assert (theirs["stock_qty_units"], theirs["avg_cost_paise"], theirs["stock_version"]) == ("4", 500, 3)
    assert inner.rows("inventory_stock_ledger") == []
    attempts = _cache_updates(privileged.log)
    assert attempts and len(attempts) == len(privileged.log), "the only thing the privileged client was asked to do is the refused claim"
    for entry in attempts:
        eq = {a[0]: a[1] for kind, a in entry["filters"] if kind == "eq"}
        assert eq.get("firm_id") == FIRM and eq.get("client_id") == CLIENT, entry


def test_a_refused_ledger_insert_restores_the_cache_through_the_privileged_client(monkeypatch):
    inner, request, privileged = _pair(monkeypatch, STOCK, guard_cache=True)
    _item(inner)
    original_table = privileged.table

    def table(name):
        if name == "inventory_stock_ledger":
            class Refused:
                def __getattr__(self, attr):
                    def call(*a, **k):
                        raise RuntimeError("ledger insert refused")
                    return call
            return Refused()
        return original_table(name)

    privileged.table = table
    with pytest.raises(RuntimeError, match="ledger insert refused"):
        inventory_service.record_stock_in(
            request, firm_id=FIRM, client_id=CLIENT, service_catalogue_id="item-1", movement_date="2026-04-10",
            quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="purchase", source_type="purchase_bill",
            source_id="bill-1", reference_no="BILL-1")
    assert request.log == [] and request.refused == []
    writes = _cache_updates(privileged.log)
    assert len(writes) >= 2                                    # the claim (once or twice for an item with no version) and the restore
    for entry in writes:
        eq = {a[0]: a[1] for kind, a in entry["filters"] if kind == "eq"}
        assert eq.get("firm_id") == FIRM and eq.get("client_id") == CLIENT, entry
    assert writes[-1]["payload"]["stock_qty_units"] == "0"     # the last statement is the restore, from the ledger's tail
    row = inner.rows("service_catalogue")[0]
    assert row["stock_qty_units"] == "0" and row["avg_cost_paise"] == 0           # the ledger has no row, so the copy says nothing
    assert row["stock_version"] == 2                                                 # the counter only moves forward


def test_the_opening_batch_caches_through_the_privileged_client_for_this_clients_items_only(monkeypatch, caplog):
    from tests.test_inventory_opening_stock_journal import _seed_coa, _seed_item, _wire
    inner, request, privileged = _pair(monkeypatch, STOCK, guard_cache=True)
    _wire(monkeypatch, inner)
    _seed_coa(inner, firm_id="firm-inv-1", client_id="client-inv-1")
    rows = []
    for _ in range(2):
        item_id = str(uuid.uuid4())
        _seed_item(inner, item_id)
        rows.append({"id": item_id, "client_id": "client-inv-1", "name": "Mine", "kind": "good", "opening_qty_units": "10",
                     "opening_cost_paise": 100_00, "created_at": "2026-04-01T00:00:00Z"})
    # a row whose id is ANOTHER client's item: the upsert would rewrite its client and name if it were handed over
    theirs = inner.seed("service_catalogue", {"id": str(uuid.uuid4()), "firm_id": "firm-inv-1", "client_id": "client-other",
                                              "name": "Theirs", "kind": "good", "stock_qty_units": "1", "avg_cost_paise": 9})
    rows.append({"id": theirs["id"], "client_id": "client-inv-1", "name": "Mine", "kind": "good", "opening_qty_units": "10",
                 "opening_cost_paise": 100_00, "created_at": "2026-04-01T00:00:00Z"})
    # and one that is ANOTHER FIRM's item under the same client id string: the firm is part of "this client's" (client ids are
    # unique in production, so this is the belt to the braces, and it is what an upsert on a service-role client must never cross)
    foreign = inner.seed("service_catalogue", {"id": str(uuid.uuid4()), "firm_id": "firm-other", "client_id": "client-inv-1",
                                               "name": "Foreign", "kind": "good", "stock_qty_units": "2", "avg_cost_paise": 8})
    rows.append({"id": foreign["id"], "client_id": "client-inv-1", "name": "Mine", "kind": "good", "opening_qty_units": "10",
                 "opening_cost_paise": 100_00, "created_at": "2026-04-01T00:00:00Z"})
    with caplog.at_level("WARNING", logger=inventory_service._logger.name):
        inventory_service.seed_opening_balances_batch(request, firm_id="firm-inv-1", created_by="user-1", rows=rows)
    assert any("2 of 4 opening-stock cache rows" in r.getMessage() and "left out" in r.getMessage() for r in caplog.records), \
        [r.getMessage() for r in caplog.records]                       # a row that was left out is said, not silently dropped
    assert request.log == [] and request.refused == []
    upserts = [e for e in _cache_updates(privileged.log) if e["verb"] == "upsert"]
    assert len(upserts) == 1 and {r["id"] for r in upserts[0]["payload"]} == {r["id"] for r in rows[:2]}, upserts
    other = next(r for r in inner.rows("service_catalogue") if r["id"] == theirs["id"])
    assert (other["client_id"], other["name"], other["stock_qty_units"], other["avg_cost_paise"]) == ("client-other", "Theirs", "1", 9)
    other_firm = next(r for r in inner.rows("service_catalogue") if r["id"] == foreign["id"])
    assert (other_firm["firm_id"], other_firm["name"], other_firm["stock_qty_units"], other_firm["avg_cost_paise"]) == ("firm-other", "Foreign", "2", 8)
    mine = [r for r in inner.rows("service_catalogue") if r["id"] in {x["id"] for x in rows[:2]}]
    assert all(r["stock_qty_units"] == "10" for r in mine)


class _CountingIn:
    """The request's client with the sizes of every `.in_()` list sent to the catalogue recorded (a PostgREST filter is part of the
    URL, which is why `fetch_all_in` chunks), and, optionally, the catalogue READ refused."""

    def __init__(self, inner, *, fail_reads=False):
        self.inner, self.sizes, self.fail_reads = inner, [], fail_reads

    def table(self, name):
        query = self.inner.table(name)
        if name != "service_catalogue":
            return query
        owner = self

        class Catalogue:
            def __getattr__(self, attr):
                target = getattr(query, attr)

                def call(*args, **kwargs):
                    if attr == "select" and owner.fail_reads:
                        raise RuntimeError("catalogue unreadable")
                    if attr == "in_":
                        owner.sizes.append(len(list(args[1])))
                    result = target(*args, **kwargs)
                    return self if result is query else result
                return call
        return Catalogue()

    def __getattr__(self, attr):
        return getattr(self.inner, attr)


def _cache_rows_for(inner, n):
    rows = []
    for i in range(n):
        item = inner.seed("service_catalogue", {"id": f"bulk-{i}", "firm_id": FIRM, "client_id": CLIENT, "name": f"Item {i}", "kind": "good"})
        rows.append({"id": item["id"], "firm_id": FIRM, "client_id": CLIENT, "name": f"Item {i}", "stock_qty_units": "10", "avg_cost_paise": 100})
    return rows


def test_the_membership_read_is_chunked_for_a_large_import_and_every_row_is_still_cached(monkeypatch):
    """A 300-product import is the reason the batch exists; an unchunked `.in_()` of its ids is a URL the gateway refuses."""
    from core.db_paging import IN_CHUNK
    inner, request, privileged = _pair(monkeypatch, STOCK, guard_cache=True)
    rows = _cache_rows_for(inner, IN_CHUNK * 2 + 10)
    counting = _CountingIn(request)
    inventory_service._write_opening_cache(counting, firm_id=FIRM, cache_rows=rows)
    assert len(counting.sizes) >= 3 and max(counting.sizes) <= IN_CHUNK, counting.sizes
    upserts = [e for e in _cache_updates(privileged.log) if e["verb"] == "upsert"]
    assert len(upserts) == 1 and len(upserts[0]["payload"]) == len(rows)
    assert request.log == [] and request.refused == []


def test_a_membership_read_that_fails_writes_no_cache_and_says_so(monkeypatch):
    """The failure must not fail OPEN: handing the upsert every row because the check could not be made is the one thing the
    check exists to prevent."""
    inner, request, privileged = _pair(monkeypatch, STOCK, guard_cache=True)
    rows = _cache_rows_for(inner, 3)
    reported = []
    monkeypatch.setattr(inventory_service, "capture_posting_failure", lambda exc, **ctx: reported.append((str(exc), ctx)))
    inventory_service._write_opening_cache(_CountingIn(request, fail_reads=True), firm_id=FIRM, cache_rows=rows)
    assert privileged.log == [] and request.log == []
    assert all(r.get("stock_qty_units") != "10" for r in inner.rows("service_catalogue")), "a cache was written although the check failed"
    assert len(reported) == 1 and reported[0][1].get("operation") == "seed_opening_balances_batch.cache_upsert", reported
