"""
Nothing in `tests/` may terminate the interpreter when it is imported.

WHAT THIS REPLACES

    `tests/e2e_gst_verification.py` was a 42 KB procedural SCRIPT living in the
    test directory: twenty-four `check()` calls, a readiness scorecard and a
    `sys.exit(1)` at module level. Two things followed from that.

    It never ran. No `test_` prefix, so `pytest tests/` skipped it — and asking
    for it BY NAME did not run it either: the module-level `sys.exit` raised
    during collection and pytest answered `INTERNALERROR`, not a failure. A file
    that cannot be collected cannot be red, so nothing ever told anyone it had
    gone stale.

    And it had. Its last honest reading was months old: "Engine Readiness 93%",
    "UI Readiness 0% — no GSTR-1 review UI, no GSTR-3B review UI", "Commercial
    Readiness 5%", "56 tests passing", and seven "BLOCKERS BEFORE A CA CAN
    GENERATE RETURNS" of which every single one is built. Run today it failed
    six checks, and **all six were the script being wrong**:

      * it expected the B2CL threshold to be ₹2,50,000. Notification
        12/2024-Central Tax moved it to ₹1,00,000 from 01-08-2024, which is
        what `classifier.b2cl_threshold_paise` answers, by invoice date.
      * it expected reverse charge in Table 3.2. Table 3.2 is supplies to
        unregistered persons, composition dealers and UIN holders; inward
        reverse charge is 3.1(d).
      * it expected net IGST to be outward IGST less IGST credit. Since the
        four-step §49(5) set-off with Rule 88A, IGST credit also pays CGST and
        SGST, so the net legitimately differs.
      * its own fixture GSTIN carried a wrong check digit, which GST-29 now
        catches — the same correction the other 77 fixture files took.
      * and one check's expectation contradicted its own label.

    So a file whose entire purpose was to verify the engine end to end reported
    the engine at 93% and the product at 5%, and was wrong about all of it. That
    is worse than no file: somebody runs it and doubts a correct engine.

    Deleted rather than repaired. Its twenty-four assertions are covered by the
    suite that actually runs — `test_gstr3b_setoff_and_rcm.py` alone has
    twenty-four cases across cross-utilisation, the CGST/SGST bar, stranded
    IGST, reverse charge in cash and zero-rated supplies, and
    `test_the_return_declares_what_the_books_hold.py` covers the 3.1(e) line the
    script's own scorecard never mentioned. `docs/audits/` is where a
    point-in-time scorecard belongs, and CLAUDE.md already says those are
    historical records rather than current specs.

THE RULE

    Every file in `tests/` is importable. A file that is not a test is a named
    helper — a parser, the harness, a fixture set — and a helper does not exit
    the interpreter either.
"""
from __future__ import annotations

import ast
import pathlib

TESTS = pathlib.Path(__file__).resolve().parent

#: Files in tests/ that are deliberately not test modules. Each is imported BY
#: a test rather than collected as one. Listed rather than pattern-matched, so
#: adding a script to this directory is a decision somebody writes down.
HELPERS = {
    "__init__.py",
    "conftest.py",
    "_backend_query_parser.py",
    "_frontend_select_parser.py",
    "_schema_checked_db.py",
    # The one call graph of the API's own source (imports, singletons and methods resolved) that two rules read: the named-row rule and
    # the rule over the client a write of a closed table is made on. Imported by both, so neither carries its own resolver.
    "_call_graph.py",
    # What a test reads off a FastAPI body parameter, the same on the version in the lock and on the next (0.141 has no `ModelField.type_`).
    # Two test modules read the model a route takes, so the spelling is here once (POST-A-171).
    "_fastapi_compat.py",
    "e2e_harness.py",
    # What the receipt-recording database function stores, read from the migrations (the last definer of its body, found by number): the rule
    # test compares it with what the service sends and `e2e_harness` stores no more than it (migration 574, POST-A-369's review).
    "_receipt_function_source.py",
    # A stand-in for the health engine's stored scores (`repositories/health_scores_repository`) for the tests whose fixture clients carry a
    # `health_score`; five test files use it, so none of them grows its own copy.
    "health_double.py",
    "generate_gst_parity_vectors.py",
    # PAY-21. Five guards read `inspect.getsource(routers.payroll.create_run)`
    # BY NAME to assert something about the payroll run's computation. Moving
    # the slip-building body into `_compute_and_store_slips` so the recompute
    # door could call the same code broke all five — on a move that did not
    # break their rule. This helper reconstructs the create path from the AST
    # instead, so the next extraction cannot silently empty them.
    "payroll_create_path.py",
    "production_types.py",
    # A GUARD THAT READS PROSE FORBIDS EXPLAINING THE FIX. Every source-scanning
    # test here has hit it: the scan trips on the comment or docstring
    # describing the very thing it bans, so either the ban loses its
    # explanation or the guard gets quietly narrowed. This blanks docstrings
    # through the AST -- never by blanking every triple-quoted string, because a
    # module-level SQL constant is triple-quoted too and IS a real read.
    # Extracted from test_one_supplier_master.py rather than copied into the
    # second module that needed it.
    "_python_source.py",
    "uat_fixtures.py",
    # D22. The narrowest PostgREST stand-in that RUNS
    # `hub_worklist_service._python_twin` — a service whose job is to fetch
    # needs a test that fetches, which is `test_the_hub_actually_answers`'s
    # own lesson. It is shared deliberately: the mock guard and
    # `test_hub_client_worklist_parity_pg` feed it the SAME rows, one from a
    # fixture and one read back out of Postgres, and a second double would be
    # two fixtures agreeing with each other rather than with the database.
    "_hub_worklist_double.py",
    # POST-A-234. Migration 499 takes the signed-in write privilege from seventeen payroll tables. The real-Postgres modules
    # that exist to measure the SECOND lock (the row policies and the 498 triggers) write as a signed-in role, so each
    # gives the privilege back in its own throwaway database through this one helper, which applies 499's rollback file
    # and so cannot drift from what the migration took away.
    "_signed_in_payroll_writes.py",
    # POST-A-304, migration 565. The database now refuses a row that names a client of another firm (and a customer or vendor of another
    # client). The real-Postgres modules that measure the OTHER defences against exactly that shape of row plant it in a throwaway
    # database with the six triggers off, through this one helper, and two modules that roll a table back to an older column shape drop
    # them first. It names only the six trigger names 565 creates; the triggers themselves are measured by test_565_*_pg.py.
    "_cross_tenant_rows.py",
    # POST-A-339, migration 550. The same device for the bank tables and the two bank reports: 550 takes every signed-in privilege
    # on the eight `bank_` tables and EXECUTE on `bank_register` and `bank_reconciling_items`, and the modules that measure the
    # row policies of those tables as a signed-in member give the privilege back in their own throwaway database through this one
    # helper, which applies 550's rollback file and so cannot drift from what the migration took away. (The payroll side of 549 is
    # `give_the_signed_in_payroll_access_back` in the helper above.)
    "_signed_in_bank_access.py",
    # POST-A-339, migration 551. The same device for the five document tables and the object policies on `storage.objects`: 551
    # takes every signed-in privilege on the tables and drops the policies a signed-in session was let into Storage by, and the
    # modules that measure the table policies, or the Storage policies as 551's rollback restores them, give both back in their own
    # throwaway database through this one helper, which applies 551's rollback file and so cannot drift from what it took away.
    "_signed_in_document_access.py",
    # POST-A-248, migration 509. The same device for the workflow tables: migration 509 takes INSERT, UPDATE and DELETE from the
    # signed-in roles on the eleven `workflow_*` tables, and the migration 503 test measures their row policies by writing as a
    # signed-in member, so it gives the privilege back in its throwaway database through this one helper, which applies 509's
    # rollback file and so cannot drift from what the migration took away.
    "_signed_in_workflow_writes.py",
    # POST-A-335 part 2, migration 563. The same device for the six document headers and their six lines tables: 563 takes INSERT,
    # UPDATE and DELETE from the signed-in roles on them, and the modules that measure the second lock (the particulars and settlement
    # triggers of 539, 541 and 544, the internal-practice guard) write as a signed-in member, so each gives the privilege back in its
    # throwaway database through this one helper, which applies 563's rollback file and so cannot drift from what the migration took.
    "_signed_in_document_writes.py",
    # POST-A-314, migration 532. A PostgREST-shaped client that runs each call in a REAL database as `authenticated` (with a
    # token's claims) or as `service_role`, for the tests that must see row security and grants: every other double answers from
    # Python, which is how the year lock's table could refuse every signed-in write and no test notice. Imported by
    # `test_a_year_end_is_finalised_and_reopened_under_a_request_sign_in_pg.py`.
    "_signed_in_postgrest.py",
    # POST-A-339. The one list of the payroll, bank and document tables that the signed-in role loses its grants on, and the one rule for
    # spotting a reference to one in source text: `test_a_sensitive_table_is_not_read_from_the_browser.py` (the browser) and
    # `test_a_payroll_bank_or_document_table_is_queried_with_the_privileged_client.py` (the API) both import it so the two guards can
    # never disagree about which tables are meant.
    "_sensitive_tables.py",
    # POST-A-319 / POST-A-299. ONE scanner for "who writes this table": the AST of every module of the API, `scripts/` included, reports
    # each place a table's name is used as a value or written in SQL text. The guards that hold `filings`, the two party-credit tables
    # and the stock ledger to their one writer each carried a copy and the copies drifted (one could not see a table name held in a
    # constant), so they import this.
    "_table_uses.py",
    # POST-A-048 / POST-A-072. A PostgREST double that has the ~1000-row cap, for tests that exist to prove a read
    # PAGES: a double that returns everything from one `.execute()` passes against exactly the defect those tests are
    # written for. Imported by `test_a_read_that_pages_reads_every_page_and_the_indian_day.py`.
    "_capped_postgrest.py",
    # practice_management-02/-03. The columns a NEW migration declares, read out of
    # the migration FILE, so a test for a new table cannot disagree with the SQL it
    # is proving (a hand-copied REAL_COLUMNS list is how the two drift). Imported by
    # `test_450_a_practices_own_mail_is_recorded_pg.py` and the notification-type guard.
    "_columns_from_migration.py",
    # market_and_trust-09. The claims ledger, in three parts that are imported by
    # `test_every_capability_sentence_on_the_marketing_site_is_in_the_claims_ledger.py`
    # and are not tests: the copy extractor (`_marketing_copy`: what the site SAYS, as
    # sentences), the vocabulary (`_marketing_vocabulary`: which sentences promise
    # something) and the ledger itself (`_marketing_claims`: each such sentence, the fact
    # it asserts and the test that proves it). Data and rules, in files a reviewer reads.
    "_marketing_claims.py",
    "_marketing_copy.py",
    "_marketing_vocabulary.py",
    # engineering-23. The one place a Hypothesis test's settings are decided (derandomized, no replay
    # database, a deadline that cannot flake) and the amount strategies the property tests share. Imported
    # by `test_the_money_and_statutory_kernels_hold_for_any_input.py`; it skips the importer where hypothesis
    # is not installed and raises where `CI` is set.
    "_property.py",
    # ops-16. A stand-in for `psql` that records how the migration runner CALLED it and models
    # what a transaction does (a file that fails on its third statement leaves nothing, a
    # baseline file keeps its partial effects). Imported by
    # `test_the_migration_runner_is_atomic_and_remembers.py`; the real server's half of the
    # proof is `test_a_migration_is_atomic_pg.py`, which needs HARNESS_PG.
    "_fake_psql.py",
    # ops-14. The scheduler's claim state machine as ONE table of scenarios (who claims, who is
    # refused, what an expired lease allows), run through the in-memory store by
    # `test_a_scheduled_job_is_claimed_before_it_runs.py` and through migration 471's SQL on a real
    # PostgreSQL by `test_471_a_scheduled_job_is_claimed_before_it_runs_pg.py`. Shared on purpose: two
    # copies of the table would be two suites agreeing with themselves, not with each other.
    "_claim_scenarios.py",
    # engineering-28. The reader behind `test_every_query_on_a_firm_table_carries_its_firm_scope.py`:
    # it walks every PostgREST chain in apps/api as a unit (its table, its operation, its filters
    # and the statements around it) and says whether it carries its firm's scope. Kept apart from
    # the guard so the guard's negative controls, and the reader's own tests, can run it over a
    # synthetic source and over a real file with one line removed.
    "_firm_scope_scan.py",
    # POST-A-070. A small set of books as the year-end statements serve them, every figure hand-chosen and balanced, so the tests of the
    # Part A schedules write their expected values out instead of deriving them from the function under test. Imported by
    # `test_the_books_schedules_place_every_line_once.py`, `test_the_depreciation_schedules_come_from_the_blocks.py` and
    # `test_the_books_schedules_route_asks_who_may_see_the_books.py`.
    "_books_statements.py",
}

_EXITS = {"exit", "quit", "_exit"}


def _module_level_exit(tree: ast.Module) -> ast.AST | None:
    """A call that ends the process, reachable at import.

    Statements inside `if __name__ == "__main__":` are skipped — that is the
    one place a module may legitimately behave like a script, because pytest
    never takes that branch.
    """
    for node in tree.body:
        if isinstance(node, ast.If) and ast.dump(node.test).find("__main__") != -1:
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            fn = inner.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else fn.id if isinstance(fn, ast.Name) else "")
            if name in _EXITS and not isinstance(node, (ast.FunctionDef,
                                                        ast.AsyncFunctionDef,
                                                        ast.ClassDef)):
                return inner
    return None


def test_no_file_in_tests_exits_the_interpreter_at_import():
    offenders = []
    for path in sorted(TESTS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        hit = _module_level_exit(tree)
        if hit is not None:
            offenders.append(f"{path.name}:{hit.lineno}")
    assert offenders == [], (
        "a module-level exit makes the file uncollectable — pytest answers "
        "INTERNALERROR rather than a failure, so the file can never be red and "
        "nothing tells you it has gone stale: " + ", ".join(offenders))


def test_every_file_here_is_a_test_or_a_declared_helper():
    stray = sorted(p.name for p in TESTS.glob("*.py")
                   if not p.name.startswith("test_") and p.name not in HELPERS)
    assert stray == [], (
        "a script in tests/ reads as verification and runs in no CI. Give it a "
        "test_ prefix so it is collected, move it to scripts/, or add it to "
        "HELPERS above with a reason: " + ", ".join(stray))


def test_the_declared_helpers_all_exist():
    """So the list cannot quietly outlive what it exempts."""
    missing = sorted(h for h in HELPERS if not (TESTS / h).exists())
    assert missing == [], f"HELPERS names files that are gone: {missing}"
