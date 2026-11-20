"""A read of the `clients` table that is not a lookup by id leaves the practice out, or is listed with why it does not (POST-A-169).

WHAT WAS WRONG
    The firm's own practice is a `clients` row (`is_internal = true`), and Guardrail G2 says it is not one of the firm's clients to
    count, list, score or chase (docs/architecture/11-revenue-ops-and-knowledge.md, section 3). `client_repo.find_all()` leaves it out
    by default, and docs/REVENUE_OPS_BRIDGE.md B2-2 recorded the debt: every NEW direct `clients` query has to remember the filter, and
    nothing but review made it. The browser side has had its rule since the picker guard
    (`apps/web/scripts/a-client-picker-leaves-out-the-internal-client.test.ts`); the API had none.

THE RULE
    Every `.table("clients").select(...)` in the API is one of: keyed on `id` (`.eq("id", ...)` / `.in_("id", ...)`: a lookup of a row
    somebody already chose, which may be the practice on purpose); in a function that asks `is_internal` (it decided); or named below
    with the reason the practice is in its answer. The list is an equality: a new unkeyed read that never asks fails until somebody
    decides it, and an entry whose read has gone or now asks fails until it is deleted.

WHAT THE CENSUS FOUND, 16-11-2026
    Thirteen reads. Two were `ClientRepository.find_by_pan` and `find_by_gstin`: no caller anywhere, and neither named a firm, so the
    first caller would have read another firm's client by its PAN; they are deleted. Nine were listed as including the practice on
    purpose (its books, its own GST and e-invoices, names for rows chosen elsewhere). Two count or list the practice among the firm's
    clients, which G2 says they should not, and are listed as open rather than changed here: the hub worklist's rows come from a
    database function that does not leave it out either, so the count and the rows have to move together, and the risk register is
    the practice's own exposure too, so which way it falls is a decision. They are open work, carried by a new-findings line.

AND ONE OF THE NINE WAS NOT ON PURPOSE, 17-11-2026
    `client_metrics_service.refresh_firm` was listed with "the screens that read them choose whom they show", but its rows have one
    reader, the benchmark (`routers/analytics._benchmark_rows`), and it did not choose: the practice was counted in every distribution
    of a Partner's benchmark. The sweep now leaves the practice out, and the benchmark skips a practice row stored before that, by id.
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests._call_graph import chain_of

API = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("routers", "services", "domain", "repositories", "jobs", "core")

#: (module, function) -> why the practice is in this read's answer. Each was read on 16-11-2026.
PRACTICE_IN_ON_PURPOSE: dict[tuple[str, str], str] = {
    ("routers/payroll.py", "payroll_client_states"):
        "names for the clients payroll settings and runs already chose; the answer goes through `_the_firms_clients_only`, which leaves the practice out unless a Partner names it (POST-A-532)",
    ("routers/payroll.py", "payroll_employee_exceptions"):
        "names for the clients whose employees are listed; the list goes through `_the_firms_clients_only`, which leaves the practice's own staff out (POST-A-532)",
    ("services/balance_cache_service.py", "audit_and_heal_firm"):
        "the nightly balance heal covers every set of books, and the practice keeps books",
    ("services/reconciliation_service.py", "run_reconciliation_for_firm"):
        "the nightly ledger reconciliation covers every set of books, and the practice keeps books",
    ("services/gst_2b_reconciliation_service.py", "holders_of"):
        "routes a GSTR-2B file to the registration named in it, and the practice files its own returns",
    ("services/irn_worklist_service.py", "_clients"):
        "names for the invoices that owe an IRN, and the practice issues its own invoices",
    ("services/compliance_obligation_service.py", "_dashboard_names"):
        "names for obligations already chosen (mock mode reads the repository with include_internal=True for the same reason)",
    ("services/portal_access_service.py", "_legacy_client"):
        "the client a portal login belongs to, keyed on that login; not a population",
}

#: (module, function) -> what is open. SHRINK-ONLY: these count or list the practice among the firm's clients, which G2 says not to.
#: They are OPEN WORK and not accepted exceptions: being named here keeps the census an equality, it does not carry the work. Each is
#: carried by a new-findings line (POST-A-457 emptied it on 17-11-2026), and an entry is deleted in the
#: commit that fixes its read and closes that line.
G2_OPEN: dict[tuple[str, str], str] = {}


def _outer_functions(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    """node -> the outermost function it sits in."""
    out: dict[ast.AST, ast.AST] = {}

    def visit(node, outer):
        for child in ast.iter_child_nodes(node):
            here = outer or (child if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else None)
            out[child] = here
            visit(child, here)
    visit(tree, None)
    return out


def unkeyed_reads_that_never_ask(source: str) -> dict[str, int]:
    """function name -> how many `clients` selects in it are neither keyed on `id` nor in a function that asks `is_internal`."""
    tree = ast.parse(source)
    outer = _outer_functions(tree)
    parent = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    found: dict[str, int] = {}
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "table" and len(n.args) == 1
                and isinstance(n.args[0], ast.Constant) and n.args[0].value == "clients"):
            continue
        top = n
        while isinstance(parent.get(top), ast.Attribute) and isinstance(parent.get(parent[top]), ast.Call):
            top = parent[parent[top]]
        ops = chain_of(top)
        if "select" not in {m for m, _ in ops}:
            continue
        if any(m in ("eq", "in_") and c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value == "id" for m, c in ops):
            continue
        fn = outer.get(n)
        if fn is not None and any(isinstance(x, ast.Constant) and x.value == "is_internal" for x in ast.walk(fn)):
            continue
        name = fn.name if fn is not None else "<module>"
        found[name] = found.get(name, 0) + 1
    return found


def census(root: Path = API) -> set[tuple[str, str]]:
    out = set()
    for d in SCAN_DIRS:
        for path in sorted((root / d).rglob("*.py")):
            for fn in unkeyed_reads_that_never_ask(path.read_text(encoding="utf-8")):
                out.add((path.relative_to(root).as_posix(), fn))
    return out


def test_every_unkeyed_read_of_clients_leaves_the_practice_out_or_says_why():
    found = census()
    listed = set(PRACTICE_IN_ON_PURPOSE) | set(G2_OPEN)
    new = sorted(found - listed)
    assert not new, (
        "these read the firm's clients without asking `is_internal`, so the firm's own practice is in their answer (Guardrail G2: it "
        "is not a client to count, list, score or chase). Add `.eq(\"is_internal\", False)`, read through `client_repo.find_all()`, "
        f"or add the read to PRACTICE_IN_ON_PURPOSE with why the practice belongs in it: {new}")
    gone = sorted(listed - found)
    assert not gone, f"these no longer read clients without asking is_internal; delete them from the lists: {gone}"
    assert not set(PRACTICE_IN_ON_PURPOSE) & set(G2_OPEN)


def test_the_census_sees_a_population_read_and_passes_a_lookup_and_a_decision():
    population = 'def f(db, firm):\n    return db.table("clients").select("id").eq("firm_id", firm).execute()\n'
    lookup = 'def g(db, firm, cid):\n    return db.table("clients").select("id").eq("firm_id", firm).eq("id", cid).execute()\n'
    decided = ('def h(db, firm, include_internal=False):\n    q = db.table("clients").select("id").eq("firm_id", firm)\n'
               '    if not include_internal:\n        q = q.eq("is_internal", False)\n    return q.execute()\n')
    nested = ('def k(db, firm):\n    def page():\n        return db.table("clients").select("id").eq("firm_id", firm)\n'
              '    return page\n')
    write = 'def w(db, row):\n    db.table("clients").insert(row).execute()\n'
    assert unkeyed_reads_that_never_ask(population) == {"f": 1}
    assert unkeyed_reads_that_never_ask(lookup) == {}
    assert unkeyed_reads_that_never_ask(decided) == {}
    assert unkeyed_reads_that_never_ask(nested) == {"k": 1}
    assert unkeyed_reads_that_never_ask(write) == {}


# ── the benchmark, which the census listed as choosing and which did not ─────────────────────────────────────────────────────────

FIRM, PRACTICE = "firm-g2", "c-practice"


def test_the_nightly_figures_are_not_computed_for_the_practice(monkeypatch):
    """The sweep's rows have one reader, the benchmark, and the practice is not a client to benchmark (G2)."""
    import datetime as dt

    from services import client_metrics_service as svc
    from tests._capped_postgrest import CappedDB

    db = CappedDB({"clients": [
        {"id": "c-one", "firm_id": FIRM, "is_internal": False},
        {"id": PRACTICE, "firm_id": FIRM, "is_internal": True},
        {"id": "c-elsewhere", "firm_id": "firm-other", "is_internal": False},
    ]})
    stored: list[str] = []
    monkeypatch.setattr(svc, "compute_for_client", lambda _db, _rep, firm_id, client_id, fy: {"client_id": client_id})
    monkeypatch.setattr(svc, "store", lambda _db, row: stored.append(row["client_id"]))

    out = svc.refresh_firm(db, FIRM, reporting=object(), today=dt.date(2026, 11, 17))

    assert set(stored) == {"c-one"}, "a figure was computed and stored for the firm's own practice"
    assert out["clients"] == 1
    assert all(("eq", "is_internal", False) in ops for ops in db.requests["clients"]), "the sweep's read does not ask"


def _rows_the_benchmark_counts(monkeypatch, stored, practice, allowed=None):
    """The practice is found the way production finds it, off `firms.internal_client_id`."""
    import routers.analytics as an
    import services.internal_client_service as ics
    from tests._capped_postgrest import CappedDB

    firms = CappedDB({"firms": [{"id": FIRM, "internal_client_id": practice},
                                {"id": "firm-other", "internal_client_id": "c-one"}]})
    monkeypatch.setattr(ics, "_USE_MOCK", False)
    monkeypatch.setattr(ics, "_db", lambda: firms)
    monkeypatch.setattr(an, "_client_period_metrics", lambda firm_id, fy: [{"client_id": c} for c in stored])
    monkeypatch.setattr(an.client_repo, "names_by_id", lambda firm_id, include_archived=False: {"c-one": "One", "c-two": "Two"})
    return [r.client_id for r in an._benchmark_rows(FIRM, "2026-27", allowed)]


def test_a_practice_row_the_sweep_stored_before_is_not_benchmarked(monkeypatch):
    """The rows written before the sweep left the practice out stay in the table, so the reader skips them by id."""
    assert _rows_the_benchmark_counts(monkeypatch, ["c-one", PRACTICE, "c-two"], PRACTICE) == ["c-one", "c-two"]


def test_the_benchmark_skips_the_practice_alongside_the_callers_scope(monkeypatch):
    assert _rows_the_benchmark_counts(monkeypatch, ["c-one", PRACTICE, "c-two"], PRACTICE, allowed={"c-two", PRACTICE}) == ["c-two"]


def test_a_firm_with_no_practice_provisioned_has_every_row_benchmarked(monkeypatch):
    """No `firms.internal_client_id` is no practice to leave out, never a reason to drop a row."""
    assert _rows_the_benchmark_counts(monkeypatch, ["c-one", "c-two"], None) == ["c-one", "c-two"]


def test_the_benchmark_endpoint_counts_the_clients_without_the_practice(monkeypatch):
    import core.authz as authz
    import routers.analytics as an

    monkeypatch.setattr(authz, "effective_client_ids", lambda user: None)
    _rows_the_benchmark_counts(monkeypatch, ["c-one", PRACTICE], PRACTICE)

    data = an.tax_benchmark(financial_year="2026-27", client_id=None,
                            current_user={"id": "u1", "firm_id": FIRM, "role": "Partner"})["data"]

    assert data["clients"] == 1


def test_the_identifier_lookups_that_named_no_firm_are_gone():
    from repositories.client_repository import ClientRepository
    assert not hasattr(ClientRepository, "find_by_pan") and not hasattr(ClientRepository, "find_by_gstin")
