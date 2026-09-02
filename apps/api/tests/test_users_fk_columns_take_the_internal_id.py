"""
A column that FKs public.users(id) is written with the INTERNAL user id.

WHAT WAS WRONG
    current_user carries two ids: "id" (public.users.id) and "auth_user_id"
    (Supabase's). CLAUDE.md says which one a users-FK column takes. The
    year-end review workflow wrote the OTHER one into submitted_by,
    approved_by, revision_requested_by and final_approved_by — and users.id
    never equals auth_user_id (checked on production: 0 of 2) — so every
    submit / approve / request-revision / final-approve raised SQLSTATE 23503,
    unguarded. The bank column mapper made the identical mistake the same
    week and was caught only by a live database.

WHY THE MOCK SUITE COULD NOT SEE EITHER
    Mock mode has no foreign keys. An FK violation is invisible to ~9,000
    tests, and the one review-workflow test seeded users by auth_user_id and
    read them back by auth_user_id, so it was consistent with the bug.

The first test here is a source-level guard on the file that was wrong. The
second is the pattern: it needs the real schema to know which columns FK
users, so it lives with the _pg tests and runs in CI's migration-apply job.
"""
import os
import pathlib
import re
import subprocess

import pytest

API = pathlib.Path(__file__).resolve().parent.parent
_PG = os.environ.get("HARNESS_PG")


def test_the_review_workflow_writes_the_internal_id():
    src = (API / "routers" / "year_end_reviews.py").read_text()
    for col in ("submitted_by", "approved_by", "revision_requested_by", "final_approved_by"):
        bad = re.findall(rf'"{col}"\s*:\s*current_user\.get\("auth_user_id"\)', src)
        assert not bad, f"{col} is a public.users(id) FK; auth_user_id can never satisfy it"
        assert re.search(rf'"{col}"\s*:\s*current_user\.get\("id"\)', src), col
    # The review trail's actor and the name lookup have to agree on WHICH id.
    assert 'current_user.get("id"), data.comment)' in src
    assert '.in_("id", list(actor_ids))' in src
    assert 'in_("auth_user_id"' not in src


def test_the_audit_log_actor_is_deliberately_untouched():
    """audit_log.actor_id has no FK and takes the auth id everywhere in the
    codebase. Fixing the review columns must not have swept it along."""
    src = (API / "routers" / "year_end_reviews.py").read_text()
    assert 'actor_id=current_user.get("auth_user_id"), actor_email=' in src


@pytest.mark.skipif(not _PG, reason="needs HARNESS_PG — reads the real FK list")
def test_no_router_writes_the_auth_id_into_a_users_fk_column(pg_template):
    """The pattern, not the instance. Read every (table, column) that FKs
    public.users from the schema, then refuse any insert/update payload that
    sets one of them from auth_user_id.

    Reads the session's pre-migrated template database directly: the query
    only SELECTs from the catalogue, so there is nothing to isolate and no
    reason to pay for a clone. HARNESS_PG carries no dbname on purpose — every
    _pg test names its own — and pointing psql at it bare lands on the
    `postgres` database, which has no public.users."""
    out = subprocess.run(
        ["psql", f"{_PG} dbname={pg_template.name}", "-Atc",
         "select c.conrelid::regclass::text||'|'||a.attname "
         "from pg_constraint c join pg_attribute a "
         "  on a.attrelid=c.conrelid and a.attnum=c.conkey[1] "
         "where c.contype='f' and c.confrelid='public.users'::regclass"],
        capture_output=True, text=True, check=True).stdout
    pairs: dict[str, set[str]] = {}
    for line in out.splitlines():
        if "|" in line:
            t, c = line.split("|", 1)
            pairs.setdefault(t.replace("public.", ""), set()).add(c)
    assert pairs, "the FK list came back empty — the query or the schema is wrong"

    offenders = []
    for path in sorted((API / "routers").glob("*.py")) + sorted((API / "services").glob("*.py")):
        src = path.read_text()
        for m in re.finditer(r'\.table\(\s*["\'](?P<t>[a-z_]+)["\']\s*\)', src):
            cols = pairs.get(m.group("t"))
            if not cols:
                continue
            window = src[max(0, m.start() - 1500): m.end() + 1500]
            for col in cols:
                if re.search(rf'["\']{col}["\']\s*:\s*[^,\n]*auth_user_id', window):
                    offenders.append(f"{path.name}: {m.group('t')}.{col}")
    assert not offenders, (
        "these columns FK public.users(id) but are set from the Supabase auth "
        "id, which can never satisfy the FK:\n  " + "\n  ".join(sorted(set(offenders))))
