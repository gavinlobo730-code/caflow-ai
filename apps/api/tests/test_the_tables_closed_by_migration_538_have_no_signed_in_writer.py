"""The sixteen tables migration 538 closes to the signed-in role have no signed-in writer: ten are used by nothing, one is used only
through the privileged client, four are written only through it, and one had write methods nobody called (POST-A-305's dead-table half).

THE DEFECT
    `authenticated` held every privilege on these tables behind a firm policy and no role tier, so any member of the firm, a
    read-only Reviewer included, could write them over PostgREST: among them `invoice_settings`, the bank details printed on every
    invoice. The migration revokes the writes (the eleven the signed-in role neither reads nor writes lose the read as well), so
    what keeps the product working afterwards is this file's premise, held from the source: no code path writes them with the
    caller's own sign-in. Mock mode would not show a break (a double accepts any caller), so the premise is asserted here and the
    grants are asserted in `test_538_..._pg.py`.

WHAT IS HELD (no database)
    * (source, derived from the AST of every module the API runs or ships, `scripts/` included, by the one scanner the other writer
      guards share) nothing in the API names any of the ten tables nothing uses, and the only code that writes each of the others
      is the set of functions named below;
    * `recurring_journal_template_lines` is named by one module only, and no caller hands that module's functions a client of its
      own, so every read and write of it is on `_db`, which is `db_provider.service_db`; the branding repository writes through
      `_svc`, the same function (always privileged, with no fallback to the request's client);
    * `escalation_rules` has no write method at all (the base repository's `create` and `update` raise NotImplementedError, so a
      future caller fails loudly instead of reaching a database that would refuse it);
    * the browser (`apps/web`) names none of the sixteen tables anywhere in a line, an embed inside a select string included, so no
      screen needs a signed-in write or read on any of them;
    * the scanner is shown each spelling a write can take and fires on each (a negative control for the guard itself).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from repositories.escalation_rule_repository import EscalationRuleRepository
from tests._table_uses import sources as _sources, uses as _uses

API_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = API_ROOT.parents[1] / "apps" / "web"

BRANDING = "repositories/branding_repository.py"
ESCALATION = "repositories/escalation_rule_repository.py"
RECURRING = "services/recurring_journal_service.py"

NOTHING_USES = ["ai_trigger_registry", "entity_addresses", "entity_documents", "lead_activities", "lead_contacts", "pending_invites",
                "permission_grants", "retainer_logs", "team_members", "xbrl_tag_mappings"]
# table -> {file: the functions that write it}; an empty dict is a table nothing writes
EXPECTED_WRITERS = {
    "email_templates": {BRANDING: {"upsert_email_template", "update_email_template", "delete_email_template"}},
    "firm_branding": {BRANDING: {"upsert_branding"}},
    "invoice_settings": {BRANDING: {"upsert_invoice_settings"}},
    "invoice_templates": {BRANDING: {"create_invoice_template", "update_invoice_template", "delete_invoice_template",
                                     "set_default_template", "clear_default_templates"}},
    "recurring_journal_template_lines": {RECURRING: {"_insert_lines", "update_template"}},
    "escalation_rules": {},
}
ALL_SIXTEEN = NOTHING_USES + list(EXPECTED_WRITERS)


def test_nothing_in_the_api_names_a_table_nothing_uses():
    named = []
    for rel, text in _sources():
        for table in NOTHING_USES:
            if table in text:
                named += [(rel, line, table, kind) for kind, _fn, line, *_ in _uses(text, table)]
    assert not named, f"a table migration 538 closes entirely is used by {named}"


def test_only_the_named_functions_write_each_of_the_others_and_no_spelling_hides_a_write():
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
    for table in ALL_SIXTEEN:
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


def test_the_walk_reads_enough_modules_to_mean_something():
    rels = [rel for rel, _ in _sources()]
    assert len(rels) > 300, len(rels)
    assert any(r.startswith("scripts/") for r in rels), "the scripts directory is not walked: a one-off writer would pass"
    assert BRANDING in rels and ESCALATION in rels and RECURRING in rels


def _module_level_assignment(tree: ast.Module, name: str) -> ast.AST:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
    raise AssertionError(f"{name} is not assigned at module level")


def _is_service_db(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "service_db" and isinstance(node.value, ast.Name) and node.value.id == "db_provider"


def test_the_branding_repository_writes_only_through_the_privileged_client():
    text = (API_ROOT / BRANDING).read_text(encoding="utf-8")
    tree = ast.parse(text)
    assert _is_service_db(_module_level_assignment(tree, "_svc")), "_svc is no longer db_provider.service_db"
    checked = 0
    for table, files in EXPECTED_WRITERS.items():
        if BRANDING not in files:
            continue
        for kind, fn, line, receiver, _verbs in _uses(text, table):
            if kind != "write":
                continue
            ok = (isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Name) and receiver.func.id == "_svc")
            assert ok, f"{BRANDING}:{line} {fn} writes {table} through {ast.dump(receiver)[:90]}, not _svc()"
            checked += 1
    assert checked >= 12, checked


def test_the_recurring_journal_lines_are_used_by_one_module_on_the_privileged_client_and_no_caller_hands_in_its_own():
    # (1) no other module names the table, whatever it does with it
    elsewhere = [(rel, line) for rel, src in _sources() if rel != RECURRING and "recurring_journal_template_lines" in src
                 for _kind, _fn, line, *_ in _uses(src, "recurring_journal_template_lines")]
    assert not elsewhere, f"the table is used outside {RECURRING}: {elsewhere}"
    # (2) inside it, the client every function uses is `db or _db()`, with `_db` the privileged accessor
    text = (API_ROOT / RECURRING).read_text(encoding="utf-8")
    tree = ast.parse(text)
    assert _is_service_db(_module_level_assignment(tree, "_db")), "_db is no longer db_provider.service_db"
    for fn_name in ("create_template", "update_template"):
        fdef = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn_name)
        assigns = [a for a in ast.walk(fdef) if isinstance(a, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "db" for t in a.targets)]
        assert assigns and all(isinstance(a.value, ast.BoolOp) and isinstance(a.value.op, ast.Or)
                               and isinstance(a.value.values[-1], ast.Call) and isinstance(a.value.values[-1].func, ast.Name)
                               and a.value.values[-1].func.id == "_db" for a in assigns), f"{fn_name} no longer falls back to _db()"
    # (3) no caller of any function of the module hands it a client: not by keyword and not in the position of its `db` parameter
    positions = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            names = [a.arg for a in node.args.args]
            if "db" in names:
                positions[node.name] = names.index("db")
    assert {"create_template", "update_template"} <= set(positions), positions
    handed = []
    for rel, src in _sources():
        if rel == RECURRING or "recurring_journal_service" not in src:
            continue
        mod = ast.parse(src)
        aliases = set()
        names = set()
        for node in ast.walk(mod):
            if isinstance(node, ast.Import):
                aliases |= {(a.asname or a.name.split(".")[-1]) for a in node.names if a.name.endswith("recurring_journal_service")}
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").endswith("recurring_journal_service"):
                    names |= {(a.asname or a.name): a.name for a in node.names}.keys()
                elif any(a.name == "recurring_journal_service" for a in node.names):
                    aliases |= {(a.asname or a.name) for a in node.names if a.name == "recurring_journal_service"}
        for node in ast.walk(mod):
            if not isinstance(node, ast.Call):
                continue
            fname = None
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id in aliases:
                fname = node.func.attr
            elif isinstance(node.func, ast.Name) and node.func.id in names:
                fname = node.func.id
            if fname is None:
                continue
            if any(k.arg == "db" for k in node.keywords) or (fname in positions and len(node.args) > positions[fname]):
                handed.append((rel, node.lineno, fname))
    assert not handed, f"a caller hands the recurring-journal service a client of its own: {handed}"


def test_the_escalation_rule_repository_has_no_write_method():
    tree = ast.parse((API_ROOT / ESCALATION).read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "EscalationRuleRepository")
    defined = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    assert not defined & {"create", "update", "delete", "soft_delete", "upsert"}, defined
    # the inherited ones fail loudly rather than reach a database that would refuse them
    for call in (lambda r: r.create({}), lambda r: r.update("x", {})):
        try:
            call(EscalationRuleRepository())
        except NotImplementedError:
            continue
        raise AssertionError("an inherited write method did not raise NotImplementedError")


def test_the_browser_reaches_none_of_the_sixteen_tables():
    """A response KEY of the same name is not a table (the invoice settings screen reads `data.invoice_settings` from the API), so
    the two ways the browser could reach a table are matched: `.from("<table>")`, and an embed of the table inside a select string
    (`"*, firm_branding(*)"`), which needs the name followed by an opening parenthesis on a line that selects."""
    assert WEB_ROOT.exists(), WEB_ROOT
    hits = []
    for path in sorted(WEB_ROOT.rglob("*")):
        if path.suffix not in {".ts", ".tsx"} or any(part in {"node_modules", ".next", "out"} for part in path.parts):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            for table in ALL_SIXTEEN:
                if table not in line:
                    continue
                if _BROWSER_FROM.search(line.replace(table, "@T@")) or ("select" in line and re.search(rf"(?:^|[\s,\"'`:(]){table}\s*\(", line)):
                    hits.append((path.relative_to(WEB_ROOT).as_posix(), lineno, table))
    assert not hits, f"the browser reaches a table migration 538 closes: {hits}"


_BROWSER_FROM = re.compile(r"""from\(\s*["'`]@T@["'`]""")


def test_the_browser_pattern_sees_a_from_and_an_embed_and_ignores_a_response_key():
    probe = lambda line, table: bool(_BROWSER_FROM.search(line.replace(table, "@T@"))
                                     or ("select" in line and re.search(rf"(?:^|[\s,\"'`:(]){table}\s*\(", line)))
    assert probe('const r = await sb.from("invoice_settings").select("*")', "invoice_settings")
    assert probe("await sb.from('firm_branding').update({})", "firm_branding")
    assert probe('.select("id, name, email_templates(*)")', "email_templates")
    assert not probe("res.data.invoice_settings && Object.keys(res.data.invoice_settings).length", "invoice_settings")
