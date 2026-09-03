"""
The drift check for GUARDS — RLS switches, policies and constraints — between
what the migrations declare and what a database has.

WHY A SECOND DIFF

scripts/db/schema_drift.py compares columns and deliberately nothing else. It
was right to: the failures it was written for were all column shape. But
migration 293 then found two things no column diff can see — a foreign key
production lacked, and two RESTRICTIVE policies drifted from their declared
form — and the first real run of this diff found a CHECK constraint that had
been quietly rejecting a real feature: migration 042 widened
clients_status_check to admit 'archived', production never received it, and
archiving a client failed there while every test here passed.

THE CATEGORIES THAT MATTER, IN ORDER

  rls_off_in_live                          every policy on the table is decoration
  restrictive_policies_missing_from_live   a per-row check is not being applied
  tables_left_without_a_policy_in_live     fail-closed: direct reads return nothing
  check_constraints_differ                 production may REJECT what passes here
  unique_constraints_missing_from_live     an upsert against it fails there

Everything else is real drift worth knowing and not a live failure.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "guard_drift",
    Path(__file__).resolve().parents[1] / "scripts" / "db" / "guard_drift.py")
drift_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(drift_mod)
diff_guards, render = drift_mod.diff_guards, drift_mod.render


def rls(*tables, off=()):
    return {t: {"detail": "OFF" if t in off else "on", "expr_md5": ""} for t in tables}


def pol(detail="permissive cmd=* roles=PUBLIC", md5="aaa"):
    return {"detail": detail, "expr_md5": md5}


def con(kind="f", md5="bbb"):
    return {"detail": kind, "expr_md5": md5}


def snap(rls_=None, policy=None, constraint=None):
    return {"rls": rls_ or {}, "policy": policy or {}, "constraint": constraint or {}}


# ── The dangerous categories, each with a planted offender ────────────────────

def test_rls_switched_off_in_live_is_the_headline():
    declared = snap(rls("clients"))
    live = snap(rls("clients", off=("clients",)))
    assert diff_guards(declared, live)["rls_off_in_live"] == ["clients"]


def test_rls_switched_off_in_the_migrations_is_reported_too():
    """The mirror direction, and the one that is easy to wave through.

    The live database is fine, so nothing is broken today — but the migrations
    are what the CI template and every new environment are built from. This is
    the shape migration 317 fixed: eight tables with RLS off here, on in
    production, and `authenticated` granted full DML by migrations 095/287.
    """
    declared = snap(rls("task_tags", off=("task_tags",)))
    live = snap(rls("task_tags"))
    report = diff_guards(declared, live)
    assert report["rls_off_in_the_migrations"] == ["task_tags"]
    assert report["rls_off_in_live"] == []


def test_rls_off_on_both_sides_is_reported_as_the_live_one_only():
    """Off in both is still off in live, which is the more urgent statement.
    Reporting it twice would double-count one table."""
    declared = snap(rls("t", off=("t",)))
    live = snap(rls("t", off=("t",)))
    report = diff_guards(declared, live)
    assert report["rls_off_in_live"] == ["t"]
    assert report["rls_off_in_the_migrations"] == []


def test_a_restrictive_policy_missing_from_live_is_reported_twice():
    """Once under the headline, once in the full list — the headline is a
    subset, exactly as schema_drift's live_requires_but_migrations_do_not is."""
    declared = snap(rls("t"), {"t.scope": pol("RESTRICTIVE cmd=* roles=PUBLIC")})
    live = snap(rls("t"))
    report = diff_guards(declared, live)
    assert report["restrictive_policies_missing_from_live"] == ["t.scope"]
    assert report["policies_missing_from_live"] == ["t.scope  [RESTRICTIVE cmd=* roles=PUBLIC]"]


def test_a_permissive_policy_missing_from_live_is_not_the_headline():
    declared = snap(rls("t"), {"t.own_firm": pol()})
    live = snap(rls("t"), {"t.firm_iso": pol()})   # renamed, not absent
    report = diff_guards(declared, live)
    assert report["restrictive_policies_missing_from_live"] == []
    assert report["tables_left_without_a_policy_in_live"] == []
    assert report["policies_missing_from_live"] == ["t.own_firm  [permissive cmd=* roles=PUBLIC]"]
    assert report["policies_only_in_live"] == ["t.firm_iso  [permissive cmd=* roles=PUBLIC]"]


def test_a_table_with_policies_declared_and_none_in_live_is_reported():
    declared = snap(rls("t"), {"t.own_firm": pol()})
    live = snap(rls("t"))
    assert diff_guards(declared, live)["tables_left_without_a_policy_in_live"] == ["t"]


def test_a_table_with_no_policy_on_either_side_is_not_reported():
    """platform_admins and platform_audit are service-role only by design."""
    both = snap(rls("platform_admins"))
    assert diff_guards(both, both)["tables_left_without_a_policy_in_live"] == []


def test_a_check_constraint_whose_expression_differs_is_the_headline():
    """clients_status_check, exactly: same name, same type, different set of
    admitted values. Production rejected 'archived'."""
    declared = snap(rls("clients"), constraint={"clients.clients_status_check": con("c", "with-archived")})
    live = snap(rls("clients"), constraint={"clients.clients_status_check": con("c", "without")})
    report = diff_guards(declared, live)
    assert report["check_constraints_differ"] == ["clients.clients_status_check"]
    assert report["constraints_differ"] == []


def test_a_foreign_key_whose_definition_differs_is_informational():
    """ON DELETE CASCADE here and no action there: a deletion behaves
    differently, but no insert is rejected."""
    declared = snap(rls("t"), constraint={"t.t_client_id_fkey": con("f", "cascade")})
    live = snap(rls("t"), constraint={"t.t_client_id_fkey": con("f", "plain")})
    report = diff_guards(declared, live)
    assert report["check_constraints_differ"] == []
    assert report["constraints_differ"] == ["t.t_client_id_fkey: definition differs"]


def test_a_unique_constraint_missing_from_live_is_the_headline():
    declared = snap(rls("t"), constraint={"t.t_firm_id_account_id_key": con("u")})
    live = snap(rls("t"))
    report = diff_guards(declared, live)
    assert report["unique_constraints_missing_from_live"] == ["t.t_firm_id_account_id_key"]
    assert report["constraints_missing_from_live"] == ["t.t_firm_id_account_id_key  [u]"]


def test_a_foreign_key_missing_from_live_is_not_the_unique_headline():
    declared = snap(rls("t"), constraint={"t.t_client_id_fkey": con("f")})
    report = diff_guards(declared, snap(rls("t")))
    assert report["unique_constraints_missing_from_live"] == []
    assert report["constraints_missing_from_live"] == ["t.t_client_id_fkey  [f]"]


# ── Scoping ───────────────────────────────────────────────────────────────────

def test_objects_on_a_table_the_other_side_lacks_are_folded_into_the_table():
    """notes_to_accounts: 067's table exists in a replay and not in production.
    Its policy and its four constraints are not five findings; the table is
    the one finding."""
    declared = snap(rls("notes_to_accounts"),
                    {"notes_to_accounts.iso": pol("RESTRICTIVE cmd=* roles=PUBLIC")},
                    {"notes_to_accounts.notes_to_accounts_pkey": con("p")})
    report = diff_guards(declared, snap())
    assert report["tables_missing_from_live"] == ["notes_to_accounts"]
    assert report["restrictive_policies_missing_from_live"] == []
    assert report["policies_missing_from_live"] == []
    assert report["constraints_missing_from_live"] == []


def test_the_runners_own_tables_are_not_drift():
    live = snap(rls("schema_migrations", "schema_migration_failures"))
    report = diff_guards(snap(), live)
    assert report["tables_only_in_live"] == []


def test_a_policy_whose_roles_differ_names_both_sides():
    declared = snap(rls("t"), {"t.own_firm": pol("permissive cmd=* roles=PUBLIC")})
    live = snap(rls("t"), {"t.own_firm": pol("permissive cmd=* roles=authenticated")})
    assert diff_guards(declared, live)["policies_differ"] == [
        "t.own_firm: migrations say permissive cmd=* roles=PUBLIC, "
        "live says permissive cmd=* roles=authenticated"]


def test_a_policy_whose_expression_differs_says_so():
    declared = snap(rls("t"), {"t.own_firm": pol(md5="x")})
    live = snap(rls("t"), {"t.own_firm": pol(md5="y")})
    assert diff_guards(declared, live)["policies_differ"] == [
        "t.own_firm: USING / WITH CHECK expression differs"]


# ── Reporting ─────────────────────────────────────────────────────────────────

def test_no_drift_says_so_plainly():
    same = snap(rls("t"), {"t.p": pol()}, {"t.c": con()})
    report = diff_guards(same, same)
    assert report == {k: [] for k in report}
    assert "No drift" in render(report)


def test_the_rendered_report_leads_with_rls_off():
    declared = snap(rls("a", "b"), {"b.p": pol()})
    live = snap(rls("a", "b", off=("a",)))
    text = render(diff_guards(declared, live))
    assert text.index("Row-level security is OFF") < text.index("gives NONE")


def test_every_category_the_diff_produces_has_a_heading():
    assert set(diff_guards(snap(), snap())) == set(drift_mod.HEADINGS)
