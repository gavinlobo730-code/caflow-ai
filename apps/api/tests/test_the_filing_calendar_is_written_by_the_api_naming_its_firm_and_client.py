"""The filing calendar is written by the API's privileged client, and each write names the firm and the client (POST-A-208, part 5).

THE PREMISE
    `compliance_calendar` still granted the signed-in role INSERT, UPDATE and DELETE behind migration 261's tier policies, though no screen writes
    it any more (the two trackers read and add through `GET /api/compliance/calendar/tracker` and `POST /api/compliance/calendar` since part 4).
    The API's Mark Filed wrote it with the caller's own client, so the grant could not be taken away. Now both writers use the privileged client
    and migration 707 takes the grant away after them. A hand-made PostgREST request could otherwise tick a return filed without the filing row
    that locks its period.

THE RULE
    Every write on `.table("compliance_calendar")` in the API starts at the privileged client (the general rule, with the table on the closed
    list); an update names `firm_id` and `client_id`, an insert carries both; the browser only names the table in comments and tests.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

API = Path(__file__).resolve().parents[1]
WEB = API.parent / "web"


def _writes():
    out = []
    for path in API.rglob("*.py"):
        rel = path.relative_to(API).as_posix()
        if rel.startswith(("tests/", "scripts/")) or "site-packages" in rel:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "compliance_calendar" not in text:
            continue
        tree = ast.parse(text)
        parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"insert", "update", "upsert", "delete"}):
                continue
            recv = node.func.value
            if not (isinstance(recv, ast.Call) and isinstance(recv.func, ast.Attribute) and recv.func.attr == "table" and recv.args
                    and isinstance(recv.args[0], ast.Constant) and recv.args[0].value == "compliance_calendar"):
                continue
            top = node
            while isinstance(parents.get(top), ast.Attribute) and isinstance(parents.get(parents[top]), ast.Call):
                top = parents[parents[top]]
            out.append((rel, node.lineno, node.func.attr, ast.unparse(top), ast.unparse(node.args[0]) if node.args else ""))
    return out


def test_the_census_finds_the_two_writers():
    assert sorted(w[2] for w in _writes()) == ["insert", "update"]


def test_an_update_names_the_firm_and_the_client_and_an_insert_carries_both():
    for rel, line, verb, chain, payload in _writes():
        if verb == "update":
            assert re.search(r"\.eq\(\s*'firm_id'", chain) and re.search(r"\.eq\(\s*'client_id'", chain), f"{rel}:{line} {chain[:200]}"
        if verb == "insert":
            assert "'firm_id'" in payload and "'client_id'" in payload, f"{rel}:{line}"


def test_the_browser_does_not_query_the_table():
    hits = []
    for folder in ("app", "components", "lib"):
        for path in (WEB / folder).rglob("*.ts*"):
            code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8", errors="ignore"), flags=re.S))
            if re.search(r"\.from\(\s*[\"'`]compliance_calendar", code):
                hits.append(str(path.relative_to(WEB)))
    assert not hits, hits
