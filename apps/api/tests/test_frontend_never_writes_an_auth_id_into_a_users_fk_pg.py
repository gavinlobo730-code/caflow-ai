"""
The frontend must not write a Supabase AUTH id into a column that FKs users(id).

WHY THE FRONTEND NEEDS ITS OWN CHECK

`apps/web` is a static export that talks to PostgREST DIRECTLY — roughly 320
`.from(…)` calls over ~83 tables — so a write there never passes through
`apps/api` and no backend test, fixture or type can see it.

`tests/test_users_fk_columns_take_the_internal_id.py` asserts this rule for the
backend and could not have caught the instance that prompted this file:
`apps/web/app/client-portal/page.tsx` set

    uploaded_by: userSession?.session?.user?.id ?? null

on every `client_documents` insert. `client_documents.uploaded_by` is a foreign
key to `public.users(id)` — the INTERNAL id of a firm user — while the value to
hand is the Supabase auth id. The two are never equal (production: 0 of 2 users
have `id = auth_user_id`), so every client-portal document upload was rejected
by the foreign key.

There was no correct value to write, which is the deeper point: a portal
uploader is the CLIENT, and a client has no `public.users` row at all — the
link is `clients.portal_user_id`, which holds an AUTH id. The fix was to stop
writing the column; `client_id` already carries the attribution.

This is the third instance of one pattern. The first two were backend and are
recorded in task #89 (the year-end review trail) and in migration 315.

WHAT IT MATCHES

A `.from("table").insert({…})` / `.update({…})` payload that sets one of the
FK columns from anything that looks like an auth identity — `auth.getUser`,
`session.user.id`, `auth.uid`, a variable named like `authUserId`. The FK list
comes from the migration-built schema, so a new FK to users is covered without
editing this file.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
_HARNESS_PG = os.environ.get("HARNESS_PG")
_NEEDS_PG = pytest.mark.skipif(
    not _HARNESS_PG or shutil.which("psql") is None or not _WEB.is_dir(),
    reason="real-Postgres harness requires HARNESS_PG + psql + apps/web")

# Anything that reads as "the id of the signed-in auth principal".
_AUTH_SHAPE = re.compile(
    r"auth\.getUser|auth\.getSession|session\??\.user\??\.id|auth\.uid\(\)"
    r"|\bauthUserId\b|\bauth_user_id\b|\buserSession\b", re.I)


def _users_fk_columns(template: str) -> dict[str, set[str]]:
    out = subprocess.run(
        ["psql", f"{_HARNESS_PG.strip()} dbname={template}", "-X", "-tA", "-c",
         "SELECT c.conrelid::regclass::text||'|'||a.attname "
         "FROM pg_constraint c JOIN pg_attribute a "
         "  ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] "
         "WHERE c.contype='f' AND c.confrelid='public.users'::regclass"],
        capture_output=True, text=True, check=True).stdout
    pairs: dict[str, set[str]] = {}
    for line in out.splitlines():
        if "|" in line:
            t, col = line.split("|", 1)
            pairs.setdefault(t.replace("public.", ""), set()).add(col)
    return pairs


def _payloads(src: str):
    """(table, start, end) for each `.from("t") … .insert({…})/.update({…})`,
    the object literal delimited by balanced braces."""
    for m in re.finditer(r'\.from\(\s*["\'`](?P<t>[a-z_0-9]+)["\'`]\s*\)', src):
        tail = src[m.end(): m.end() + 200]
        nxt = re.search(r'\.from\(', tail)
        if nxt:
            tail = tail[:nxt.start()]
        op = re.search(r'\.(insert|update|upsert)\(\s*[\[{]', tail)
        if not op:
            continue
        i = m.end() + op.end() - 1
        opener, closer = src[i], "}" if src[i] == "{" else "]"
        depth, j = 0, i
        while j < len(src):
            if src[j] == opener:
                depth += 1
            elif src[j] == closer:
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield m.group("t"), i, j


@_NEEDS_PG
def test_no_frontend_write_puts_an_auth_id_in_a_users_fk_column(pg_template):
    pairs = _users_fk_columns(pg_template.name)
    assert pairs, "the FK list came back empty — the query or the schema is wrong"

    offenders = []
    for path in sorted(_WEB.rglob("*.ts")) + sorted(_WEB.rglob("*.tsx")):
        if "node_modules" in path.parts or ".next" in path.parts:
            continue
        src = path.read_text(encoding="utf-8")
        for tbl, i, j in _payloads(src):
            cols = pairs.get(tbl)
            if not cols:
                continue
            body = src[i:j]
            for col in cols:
                for w in re.finditer(rf'\b{col}\s*:\s*([^,\n}}]*)', body):
                    if _AUTH_SHAPE.search(w.group(1)):
                        line = src[:i + w.start()].count("\n") + 1
                        offenders.append(
                            f"{path.relative_to(_WEB.parent.parent)}:{line}  "
                            f"{tbl}.{col} = {w.group(1).strip()[:60]}")
    assert not offenders, (
        "These frontend writes put a Supabase AUTH id into a column that is a "
        "foreign key to public.users(id) — the INTERNAL user id. The two are "
        "never equal, so every such write is rejected by the foreign key, and "
        "because the frontend talks to PostgREST directly no backend test can "
        "see it. That is how every client-portal document upload failed.\n"
        "Resolve the auth id to users.id first, or — if the writer is a portal "
        "CLIENT, who has no users row at all — do not set the column.\n  "
        + "\n  ".join(offenders))


@_NEEDS_PG
def test_the_scan_reads_real_frontend_writes():
    """A selector that matched nothing would pass vacuously for ever."""
    seen = [t for p in list(_WEB.rglob("*.tsx"))
            if "node_modules" not in p.parts
            for t, _, _ in _payloads(p.read_text(encoding="utf-8"))]
    assert len(seen) > 20, (
        f"only {len(seen)} frontend write payloads found — the scan is not "
        "reading the code it claims to")
    assert "client_documents" in seen, (
        "the client-portal upload this test was built around is no longer "
        "matched by the scan")
