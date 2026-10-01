"""The static half of migrations 468 and 469 — what can be pinned without a
database, in the job that has none.

The behavioural proof is `test_a_suspended_member_is_nobody_to_the_database_pg.py`.
This file holds the three things that proof cannot, because each is a fact about
the REPOSITORY and not about a schema:

1. THE SQL NAMES ONLY PAIRS THE MATRIX DEFINES, AT THE ROLE THE MATRIX SAYS.
   Migration 469's storage policies call `my_permission('document', 'write',
   'Executive')` and its siblings. SQL holds no vocabulary (403's rule), so a
   pair PERMISSIONS does not define resolves closed for EVERYBODY — every upload
   refused, a Partner's included — and a minimum role the matrix does not say is
   a quiet change of who may write. Both are read OUT of the migration and
   asserted against `core/permissions.py`, from the Python side.

2. EVERY UPLOAD PATH PUTS THE CLIENT SECOND. 469 reads the second folder as the
   client and asks `can_access_client` about it. A new upload that writes
   `{firm}/exports/...` would be refused for everybody but a Partner with a
   "violates row-level security" and nothing pointing at why. The path templates
   are read from the API's own source (by AST) and the browser's (by regex), so a
   new door fails here with a sentence.

3. A LATER MIGRATION CANNOT REVERT 468 BY DERIVING FROM THE WRONG ANCESTOR. The
   rule in CLAUDE.md — derive a replacement from the migration that LAST defined
   the function, found by number — has been got wrong twice before a real
   database caught it. The five functions 468 replaced are found by scanning the
   migration directory, and the highest-numbered definer of each must still ask
   the liveness rule (or the hardened helper). A migration 480 that starts from
   019's `get_my_firm_id` would reopen the hole and compile.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from core.permissions import PERMISSIONS, Role, is_known_permission

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
WEB_ROOT = API_ROOT.parent / "web"

STORAGE_MIGRATION = MIGRATIONS / "469_a_stored_file_opens_only_for_the_staff_assigned_to_its_client.sql"
SESSION_MIGRATION = MIGRATIONS / "468_a_suspended_or_signed_out_member_is_nobody_to_the_database.sql"

_RANK = {Role.REVIEWER: 0, Role.EXECUTIVE: 1, Role.MANAGER: 2, Role.PARTNER: 3}


def _sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code(sql: str) -> str:
    """The migration without its `--` comments, which explain the old shape in
    prose and would otherwise satisfy or trip a substring test."""
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


# ── 1. the pairs and the minimum roles ───────────────────────────────────────
def _storage_pairs() -> list[tuple[str, str, str]]:
    return re.findall(r"my_permission\('(\w+)',\s*'(\w+)',\s*'(\w+)'\)", _code(_sql(STORAGE_MIGRATION)))


def test_the_storage_policies_name_only_pairs_the_matrix_defines():
    pairs = _storage_pairs()
    assert pairs, "469 names no my_permission pair — the parser read nothing"
    for resource, action, _minimum in pairs:
        assert is_known_permission(resource, action), (
            f"469 asks my_permission('{resource}', '{action}', …) and PERMISSIONS has no "
            f"such pair, so it resolves closed for EVERYBODY — every upload refused")


def test_the_storage_policies_ask_the_matrix_s_own_minimum_role():
    for resource, action, minimum in _storage_pairs():
        roles = PERMISSIONS[resource][action]
        lowest = min(roles, key=lambda r: _RANK[r])
        assert minimum.lower() == lowest.value.lower(), (
            f"469 gives {resource}:{action} a minimum of {minimum} where "
            f"PERMISSIONS' lowest role is {lowest.value}")


def test_the_three_upload_resources_are_all_named():
    """Three routes upload under the caller's own token. Dropping one from the
    OR refuses a per-person grant at the last step."""
    names = {(r, a) for r, a, _ in _storage_pairs()}
    assert {("document", "write"), ("accounting", "write"), ("year_end", "write")} <= names
    assert ("year_end", "read") in names


def test_a_delete_is_partner_only_for_the_same_reason_the_row_is():
    code = _code(_sql(STORAGE_MIGRATION))
    delete = re.search(r'CREATE POLICY "documents_storage_delete".*?;', code, re.S)
    assert delete, "the Documents delete policy could not be read"
    assert "public.my_role_at_least('Partner')" in delete.group(0)
    # 261's tier for the row it must agree with.
    row = _sql(MIGRATIONS / "261_role_aware_write_policies_part2.sql")
    assert re.search(r"\['client_documents',\s*'Executive',\s*'Partner'\]", row), (
        "client_documents' delete tier moved — a blob a member could delete and a row "
        "they could not is a row pointing at nothing; 469's delete tier must move with it")


def test_the_year_end_bucket_has_no_member_delete_policy_left():
    code = _code(_sql(STORAGE_MIGRATION))
    assert re.search(r'DROP POLICY IF EXISTS "year_end_exports_storage_delete"', code)
    assert not re.search(r'CREATE POLICY "year_end_exports_storage_delete"', code)


def test_the_role_storage_connects_as_may_run_what_the_policies_call():
    """204's lesson, as text: every function a policy calls is granted."""
    code = _code(_sql(STORAGE_MIGRATION))
    for fn in ("can_access_client(text)", "my_permission(text, text, text)", "my_role_at_least(text)"):
        assert re.search(
            rf"GRANT EXECUTE ON FUNCTION public\.{re.escape(fn)}\s+TO supabase_storage_admin", code), (
            f"469 no longer grants supabase_storage_admin {fn}; every upload would fail "
            f"with 'permission denied for function'")


# ── 2. every upload path puts the client second ──────────────────────────────
_DOCUMENT_BUCKETS = {"Documents", "year-end-exports"}


def _python_upload_paths() -> list[tuple[str, str]]:
    """(file:line, rendered template) for every `.upload(` onto a bucket these
    policies govern. The template is rendered with `{…}` for an interpolation so
    the shape reads off directly."""
    found: list[tuple[str, str]] = []
    for path in sorted((API_ROOT / "routers").glob("*.py")):
        src = path.read_text(encoding="utf-8")
        if ".upload(" not in src or "storage" not in src:
            continue
        tree = ast.parse(src)
        module_funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            # An upload under the SERVICE key matches the service-role policy and
            # never reaches the firm-folder one (shared_reports writes
            # `shared_reports/{client}/…` that way, on purpose).
            if "get_service_supabase" in ast.unparse(fn):
                continue
            for call in ast.walk(fn):
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "upload"):
                    continue
                if "storage" not in ast.unparse(call.func):
                    continue
                bucket_src = ast.unparse(call.func.value)
                if not any(b in bucket_src for b in ("BUCKET", "Documents")) \
                        or "LOGO" in bucket_src or "firm-assets" in bucket_src:
                    # shared_reports and branding write other buckets, as the
                    # service role, and have their own policies.
                    if "_STORAGE_BUCKET" not in bucket_src:
                        continue
                arg = next((k.value for k in call.keywords if k.arg == "path"), None) \
                    or (call.args[0] if call.args else None)
                tmpl = _render(arg, fn, module_funcs)
                found.append((f"{path.name}:{call.lineno}", tmpl))
    return found


def _render(node, fn: ast.FunctionDef, module_funcs: dict) -> str:
    if isinstance(node, ast.JoinedStr):
        out = ""
        for v in node.values:
            out += v.value if isinstance(v, ast.Constant) else "{" + ast.unparse(v.value) + "}"
        return out
    if isinstance(node, ast.Name):
        for stmt in ast.walk(fn):
            if isinstance(stmt, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == node.id for t in stmt.targets):
                return _render(stmt.value, fn, module_funcs)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in module_funcs:
        target = module_funcs[node.func.id]
        for stmt in ast.walk(target):
            if isinstance(stmt, ast.Return) and stmt.value is not None:
                return _render(stmt.value, target, module_funcs)
    return ast.unparse(node) if node is not None else ""


def _the_second_folder_is_the_client(template: str) -> bool:
    folders = template.split("/")
    if len(folders) < 3:
        return False
    return "firm" in folders[0].lower() and "client" in folders[1].lower()


def test_every_api_upload_path_is_firm_then_client_then_the_rest():
    paths = _python_upload_paths()
    sites = {site.split(":")[0] for site, _ in paths}
    # Not vacuous: the five known uploaders are all seen.
    assert {"documents.py", "debit_notes.py", "purchase_credit_notes.py",
            "document_intelligence_v1.py", "year_end_exports.py"} <= sites, sorted(sites)
    for site, tmpl in paths:
        assert _the_second_folder_is_the_client(tmpl), (
            f"{site} writes '{tmpl}'. Migration 469 reads the SECOND folder as the client "
            f"and asks can_access_client about it, so this upload is refused for every "
            f"member but a Partner. Write {{firm_id}}/{{client_id}}/…")


def _web_upload_paths() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for ext in ("*.tsx", "*.ts"):
        for path in (WEB_ROOT / "app").rglob(ext):
            if "node_modules" in path.parts:
                continue
            src = path.read_text(encoding="utf-8")
            for m in re.finditer(
                    r"\.from\((?:\"Documents\"|STORAGE_BUCKET|VAULT_BUCKET)\)\s*\.upload\(\s*(\w+)", src):
                var = m.group(1)
                decl = re.search(rf"(?:const|let)\s+{var}\s*=\s*`([^`]*)`", src)
                found.append((f"{path.relative_to(WEB_ROOT)}", decl.group(1) if decl else f"<{var}?>"))
    return found


def test_every_browser_upload_path_is_firm_then_client_then_the_rest():
    paths = _web_upload_paths()
    assert len(paths) >= 5, f"the scan saw {len(paths)} browser uploads; the five known doors moved?"
    for site, tmpl in paths:
        assert re.match(r"\$\{\w*[fF]irm\w*\}/\$\{\w*[cC]lient\w*\}/", tmpl), (
            f"{site} uploads to '{tmpl}'. Migration 469 reads the second folder as the "
            f"client; write ${{firmId}}/${{clientId}}/…")


# ── 3. a later migration cannot revert 468 ───────────────────────────────────
def _last_definer(name: str) -> tuple[str, str]:
    pattern = re.compile(
        rf"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?{re.escape(name)}\s*\(", re.I)
    last = None
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name.startswith("_") or path.name.endswith("_rollback.sql"):
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            last = path
    assert last is not None, f"no migration defines {name}"
    # The BODY of that one function, not the whole file: 468 defines five, and
    # three of them legitimately select from `users`.
    code = _code(last.read_text(encoding="utf-8"))
    start = list(pattern.finditer(code))[-1].start()
    opening = code.index("$$", start)
    closing = code.index("$$", opening + 2)
    return last.name, code[opening + 2:closing]


@pytest.mark.parametrize("name", ["get_my_firm_id", "get_my_role", "get_my_user_id"])
def test_the_last_definer_of_each_helper_still_asks_the_liveness_rule(name):
    where, body = _last_definer(name)
    assert "staff_session_is_live" in body, (
        f"{name} was last defined by {where}, which does not ask staff_session_is_live — "
        f"a suspended member's session is honoured by every RLS policy again. Derive the "
        f"replacement from 468 (the last definer, found by number), not from 019/073/079.")


@pytest.mark.parametrize("name", ["can_access_client", "my_permission"])
def test_the_last_definer_of_the_two_readers_does_not_read_users(name):
    where, body = _last_definer(name)
    assert "get_my_user_id()" in body, (
        f"{name} was last defined by {where}, which does not resolve the caller through "
        f"get_my_user_id() — it reads `users` itself and a suspension no longer reaches it.")
    assert not re.search(r"\b(?:from|join)\s+(?:public\.)?users\b", body, re.I), (
        f"{name} ({where}) selects from users directly")


def test_the_last_definers_are_the_ones_this_change_wrote():
    """Not vacuous: today the answer for all five is 468, so the guard is looking
    at the right file rather than at nothing."""
    for name in ("get_my_firm_id", "get_my_role", "get_my_user_id",
                 "can_access_client", "my_permission"):
        where, _ = _last_definer(name)
        assert where == SESSION_MIGRATION.name or int(where[:3]) > 468, (name, where)


def test_the_liveness_rule_mirrors_the_two_tests_core_auth_makes():
    """Pinned to the Python authority: the SQL says what core/auth.py says."""
    sql = _code(_sql(SESSION_MIGRATION))
    assert "COALESCE(p_is_active, TRUE)" in sql                 # `is_active is False`
    assert ">= extract(epoch FROM p_sessions_revoked_at)" in sql  # refuses only `iat <`
    assert "ELSE FALSE" in sql                                  # fails closed on an unreadable iat
    auth = (API_ROOT / "core" / "auth.py").read_text(encoding="utf-8")
    assert 'user_data.get("is_active") is False' in auth
    assert 'float(payload["iat"]) < revoked_epoch' in auth
