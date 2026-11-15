"""The notification and message tables are WRITTEN with the privileged client, and the source says so at the write (POST-A-008, the
messages tranche, part 1 of 2).

THE PREMISE
    `notifications` (a member's in-app notices: a task assigned, a filing due, a government notice approved), `portal_messages` (the thread
    between the practice and a client on the portal) and `user_notification_preferences` (which of the practice's own mails a member gets) are
    granted to the signed-in role behind policies that ask the firm (and the recipient or the client assignment) and NO role tier: a signed-in
    member could write a notice into a colleague's inbox, post a message in a client's thread as the client, or turn a colleague's mail off
    with their own sign-in. The browser writes none of them; every writer is the API's. Found by POST-A-008's list of the tables a signed-in
    session reaches outside the access matrix.

    A later migration takes the signed-in write away. THIS is the half that ships first: every write to the three is made with the privileged
    client now (the thread's mark-as-read and a member's preference already were), and every update names its scope. The notification
    repository's three updates (mark one read, mark all read, archive) named the firm and the recipient only when the caller passed them; they
    are required keyword arguments now and are named in each chain, so a notification id cannot reach another member's notice.

    A notification is keyed on its firm and its recipient; a portal message on its firm and its client.

The rules are `tests/_privileged_write_sites.py`'s, shared with the other tranches; this file names the group and its census.
"""
from __future__ import annotations

import inspect

from tests import _privileged_write_sites as pw

TABLES = frozenset({"notifications", "portal_messages", "user_notification_preferences"})

#: A notification is a member's: it is named by its firm and its recipient.
KEYS = {"notifications": ("firm_id", "user_id")}

#: How many write sites each table has today. A change that adds or removes one updates this.
WRITE_SITES = {"notifications": 5, "portal_messages": 3, "user_notification_preferences": 1}


def test_every_write_to_the_notification_and_message_tables_starts_at_the_privileged_client():
    bad = pw.unprivileged_writes(TABLES)
    assert not bad, ("A write to a notification or message table is made with the caller's own client: the migration that follows takes "
                     "that client's write grant away. Make it with `privileged_for(db)`, naming its scope:\n  " + "\n  ".join(bad))


def test_every_update_names_its_scope():
    bad = pw.unscoped(TABLES, KEYS)
    assert not bad, "an update of a notification or message table does not name its scope:\n  " + "\n  ".join(bad)


def test_the_census_finds_the_writes_there_are():
    found = pw.census(TABLES)
    assert found == WRITE_SITES, f"the writers changed: {found} (expected {WRITE_SITES}); update WRITE_SITES and read the new writer against the rule"


def test_the_firm_and_the_recipient_are_required_arguments_of_the_notification_updates():
    """An optional recipient is one a caller can leave out, and then the update reaches every member's notice."""
    from repositories.notifications_repository import NotificationsRepository
    for fn in (NotificationsRepository.mark_read, NotificationsRepository.mark_all_read, NotificationsRepository.archive):
        for name in ("firm_id", "user_id"):
            param = inspect.signature(fn).parameters[name]
            assert param.kind is inspect.Parameter.KEYWORD_ONLY and param.default is inspect.Parameter.empty, (fn.__qualname__, name)


def test_the_rules_can_fail():
    t = frozenset({"notifications"})
    src = ('def f(db):\n'
           '    db.table("notifications").insert({}).execute()\n'
           '    privileged_for(db).table("notifications").update({}).eq("id", 1).eq("firm_id", 2).execute()\n')
    sites = pw.write_sites(src, t)
    assert [ok for *_x, ok, _r in sites] == [False, True]
    assert pw.unscoped_updates_and_deletes(src, t, KEYS) == ["notifications at line 3"]
