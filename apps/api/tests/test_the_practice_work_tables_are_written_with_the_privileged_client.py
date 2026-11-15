"""The practice's own work tables are WRITTEN with the privileged client, and the source says so at the write (POST-A-008, the practice
tranche, part 1 of 2).

THE PREMISE
    `time_entries` (a member's logged hours, which the unbilled-work list and the practice's profitability read, and which an invoice marks
    billed), `task_recurring_configs` (a task the practice repeats on a cadence), `reminders` (a reminder against a task or a client) and
    `knowledge_article_versions` (each saved version of a knowledge-base article, its history) are granted to the signed-in role behind
    policies that ask the firm (and the client assignment where a row names a client) and NO role tier: a signed-in member could rewrite
    another member's hours, mark logged time billed, or rewrite an article's history with their own sign-in. The browser writes none of
    them; every writer is the API's. Found by POST-A-008's list of the tables a signed-in session reaches outside the access matrix.

    A later migration takes the signed-in write away. THIS is the half that ships first: every write to the four is made with the privileged
    client now, and every update and delete names the firm. Three did not, or not always: a time entry's update and delete named the firm
    only when the caller passed it (the timer's start, stopping the one already running, did not), a reminder marked sent named the reminder
    alone, and the recurring-task sweep moving a cadence to its next date named the config alone. The firm is now a required argument of
    both repository methods and is named in each chain.

    The four are keyed on the firm and the row's id: a time entry, a recurring task and a reminder may have no client (the column is
    nullable), and a version hangs from its article and is only ever inserted.

The rules are `tests/_privileged_write_sites.py`'s, shared with the other tranches; this file names the group and its census.
"""
from __future__ import annotations

import inspect

from tests import _privileged_write_sites as pw

TABLES = frozenset({"time_entries", "task_recurring_configs", "reminders", "knowledge_article_versions"})

#: A row of these may have no client (nullable `client_id`), so it is named by its id and the firm.
KEYS = {t: ("firm_id", "id") for t in TABLES}

#: How many write sites each table has today. A change that adds or removes one updates this.
WRITE_SITES = {"time_entries": 4, "task_recurring_configs": 4, "reminders": 2, "knowledge_article_versions": 2}


def test_every_write_to_the_practice_work_tables_starts_at_the_privileged_client():
    bad = pw.unprivileged_writes(TABLES)
    assert not bad, ("A write to a practice work table is made with the caller's own client: the migration that follows takes that "
                     "client's write grant away. Make it with `privileged_for(db)`, naming its scope:\n  " + "\n  ".join(bad))


def test_every_update_and_delete_names_the_firm_and_the_row():
    bad = pw.unscoped(TABLES, KEYS)
    assert not bad, "an update or delete of a practice work table does not name the firm and the row:\n  " + "\n  ".join(bad)


def test_the_census_finds_the_writes_there_are():
    found = pw.census(TABLES)
    assert found == WRITE_SITES, f"the writers changed: {found} (expected {WRITE_SITES}); update WRITE_SITES and read the new writer against the rule"


def test_the_firm_is_a_required_argument_of_the_two_repository_writers():
    """A firm that is optional is a firm a caller can forget: the timer's start did."""
    from repositories.reminders_repository import RemindersRepository
    from repositories.time_tracking_repository import TimeTrackingRepository
    for fn in (TimeTrackingRepository.update, TimeTrackingRepository.delete, RemindersRepository.update):
        param = inspect.signature(fn).parameters["firm_id"]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY and param.default is inspect.Parameter.empty, fn.__qualname__


def test_the_rules_can_fail():
    t = frozenset({"reminders"})
    src = ('def f(db):\n'
           '    db.table("reminders").insert({}).execute()\n'
           '    privileged_for(db).table("reminders").update({}).eq("id", 1).execute()\n')
    sites = pw.write_sites(src, t)
    assert [ok for *_x, ok, _r in sites] == [False, True]
    assert pw.unscoped_updates_and_deletes(src, t, KEYS) == ["reminders at line 3"]
