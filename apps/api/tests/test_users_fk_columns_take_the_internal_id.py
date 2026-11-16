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

The tests here are source-level guards on the files that were wrong. The
pattern itself needs the real schema to know which columns FK users, so it is
`test_users_fk_columns_take_the_internal_id_pg.py`. It used to be in THIS file,
skipped without HARNESS_PG, where the real-Postgres job (which collects
`tests/test_*_pg.py`) never saw it, so it had not run in CI and was red on main
(POST-A-438); the move is what makes it run.
"""
import pathlib
import re

API = pathlib.Path(__file__).resolve().parent.parent


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
    codebase. Fixing the review columns must not have swept it along.

    THIS TEST WAS PINNING THE BUG. It asserted the literal string
    `actor_id=current_user.get("auth_user_id"), actor_email=` anywhere in the
    file, and in that file exactly ONE call wrote those two arguments on one
    line: the `lock_year_if_completing(...)` call, whose actor_id reaches
    client_year_locks.locked_by — a public.users(id) FK that an auth id can
    never satisfy. Every log_event call spelt the same pair across two lines
    and so was never what the assertion matched. A guard that names a SPELLING
    rather than the rule can end up holding the defect in place, which is what
    happened here.

    So the question is asked properly now: it is log_event, and only log_event,
    that takes the auth id.
    """
    src = (API / "routers" / "year_end_reviews.py").read_text()

    # Every log_event call passes the AUTH id...
    calls = re.findall(r"log_event\((?:[^()]|\([^()]*\))*\)", src, re.S)
    assert calls, "no log_event calls found — the guard is asserting nothing"
    for call in calls:
        assert 'actor_id=current_user.get("auth_user_id")' in call, call

    # ...and nothing that reaches a users-FK column does. lock_year_if_completing
    # is named because its actor_id lands in client_year_locks.locked_by; the
    # auth id belongs in its actor_auth_id, which goes to audit_log.
    for fn in ("lock_year_if_completing", "unlock_year_on_reopen", "set_client_lock"):
        for call in re.findall(rf"{fn}\((?:[^()]|\([^()]*\))*\)", src, re.S):
            assert 'actor_id=current_user.get("auth_user_id")' not in call, call
            if "actor_id=" in call:
                assert 'actor_id=current_user.get("id")' in call, call


def test_the_year_lock_takes_the_internal_id_through_every_caller():
    """The instance the window sweep in the _pg twin could not see (ACC-05).

    client_year_locks.locked_by FKs public.users(id) and is written in
    services/year_lock_service.py as `"locked_by": actor_id` — a PARAMETER.
    The auth id was supplied one frame up, by the two routers that call
    lock_year_if_completing. The sweep looks for the column name and the auth
    id in the same window of source, so a value that crosses a function
    boundary is invisible to it: the write site has no `auth_user_id` in sight
    and the call site has no `locked_by`.

    Consequence, had it ever run against the live database: SQLSTATE 23503 out
    of set_client_lock, AFTER routers/year_end.py and year_end_reviews.py had
    already written status='locked' on the engagement row. The engagement
    would read as finalised — terminal, before ACC-05's reopen existed — while
    the client's year stayed open to posting. Latent only because production
    holds no year-end engagements yet.
    """
    for router in ("year_end.py", "year_end_reviews.py"):
        src = (API / "routers" / router).read_text()
        for fn in ("lock_year_if_completing", "unlock_year_on_reopen"):
            for call in re.findall(rf"{fn}\((?:[^()]|\([^()]*\))*\)", src, re.S):
                if "actor_id=" not in call:
                    continue
                assert 'actor_id=current_user.get("id")' in call, (router, call)
                assert 'actor_auth_id=current_user.get("auth_user_id")' in call, (router, call)

    svc = (API / "services" / "year_lock_service.py").read_text()
    # The split has to exist in the service too, or the routers are passing an
    # argument nothing reads.
    assert "actor_auth_id" in svc
    assert '"locked_by": actor_id' in svc, "locked_by must take the internal id"
    # POST-A-361 (3-11-2026): this used to pin `actor_id=actor_auth_id or actor_id`, "falling back to the internal one rather than recording
    # nobody". `audit_log.actor_id` holds ONE kind of id, the auth id (test_the_audit_log_names_one_kind_of_actor), so a missing auth id is
    # recorded as unknown and not as the internal id, which would put half a person's rows under the wrong key. Both callers pass the auth id.
    assert "actor_id=actor_auth_id," in svc and "actor_auth_id or actor_id" not in svc, (
        "audit_log attribution is the auth id, or unknown; never the internal id")


def test_the_year_end_dashboard_names_a_review_actor_by_the_internal_id():
    """POST-A-377 (an independent read): `year_end_review_events.actor_id` is a key to users(id) (migration 315) and the router writes the
    internal id, but the dashboard looked the name up by `users.auth_user_id`, which never equals it, so every event's actor was blank."""
    src = (API.parent / "web" / "app" / "clients" / "[id]" / "year-end" / "[engagementId]" / "dashboard" / "_page.tsx").read_text()
    assert 'from("users").select("id, full_name")' in src
    assert "selfNameById.get(e.actor_id)" in src and "auth_user_id" not in src.split('from("year_end_review_events")')[1].split("setData(")[0]
    assert "REFERENCES public.users(id)" in (API / "migrations" / "315_year_end_review_events_actor_fk.sql").read_text().replace("\n", " ")
