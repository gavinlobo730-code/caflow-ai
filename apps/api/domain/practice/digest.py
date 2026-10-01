"""The practice digest: what needs attention today, drawn from checks that already
exist (ai-25).

WHAT THIS IS
    A short list a CA reads in the morning — "3 clients have overdue filings,
    5 filings fall due this week, 2 critical books findings" — built ONLY from
    what the product's existing exception engines already return, scoped to the
    caller's own clients, with a sentence a model may word and may not add to.

    Nothing is computed here that an engine computes. Each section's COUNT is read
    off that engine's own answer:

      * filings overdue / due this week  <- `intelligence_service.compute_compliance_risk`
                                            (the Insights page's compliance-risk table)
      * tasks overdue                    <- `task_repo.find_overdue`, the read the
                                            Executive Dashboard's overdue-task count
                                            uses, through `executive_dashboard.
                                            overdue_task_facts`
      * books-integrity findings         <- the unresolved rows the NIGHTLY
                                            reconciliation sweep stored
                                            (`reconciliation_findings`), which is where
                                            the ledger-anomaly, sub-ledger and bank
                                            checks put what they found

    so "every count in it equals the count the underlying report returns" is true
    by construction and a test holds it from outside (the report is asked
    independently and the digest compared).

A NIL IS OF THREE KINDS, AND THE DIGEST SAYS WHICH
    `attention` — something to look at; `clear` — the engine looked and found
    nothing; `unknown` — nobody looked (no completed books check lately, or the
    read failed). A digest that printed "0" for the third would tell a CA their
    books are sound on the strength of a sweep that never ran — the
    `table_4a_gaps` discipline, applied to a morning list. And what the digest
    deliberately does NOT cover is NAMED in `gaps` on every answer, so a short
    list is never read as a clean one.

WHAT IS DELIBERATELY NOT HERE
    GSTR-2B ("bills missing in 2B"), Rule 37A, near-duplicate bills and the
    recurring-journal suggestions are the other exception engines, and none has
    a STORED result to read. Computing them for every client on every page load
    would read each client's purchase register or three months of every posted
    entry — a read proportional to transaction volume, which the reporting rule
    forbids — so they are named in `gaps` with their own reason rather than
    approximated. A nightly job that stores them is the way to add them and is a
    piece of work of its own.

THE MODEL IS GIVEN COUNTS, NEVER NAMES
    The firm-level copilot's decision is that client names do not go to a
    provider, and the digest follows it: `narration_messages` carries the section
    headlines — counts and nothing that identifies a client — and the list of
    clients below each section is rendered from the engines' own rows and never
    passes through a model. The reply is read for figures
    (`domain/ai/narration`): a reply carrying a number no engine computed is
    discarded for `plain_summary`, which is built from the same items, so a model
    failure costs style and never substance.

Pure: no database, no model call, no clock beyond what the caller passes.
"""
from __future__ import annotations

from typing import Iterable, Optional

from domain.practice import executive_dashboard as ed

#: The "falls due soon" window of `compute_compliance_risk`, which hardcodes it.
#: Named here so the sentence and the engine can be held together by a test that
#: asks the ENGINE where day 7 and day 8 fall.
DUE_SOON_DAYS = 7

#: How far back a nightly sweep may be and still count as "the latest check".
#: The sweep runs daily, so three days tolerates a missed night; a client with no
#: completed run in the window is reported as not recently checked rather than as
#: clear.
RUN_WINDOW_DAYS = 3

#: Clients named under a section. The count is over ALL of them and `clients_total`
#: says so — a list cut at eight is never read as the whole population.
MAX_CLIENTS_LISTED = 8

KEY_FILINGS_OVERDUE = "filings_overdue"
KEY_FILINGS_DUE_SOON = "filings_due_soon"
KEY_BOOKS_FINDINGS = "books_findings"
KEY_TASKS_OVERDUE = "tasks_overdue"

#: The vocabulary the browser routes on. The ROUTE map is the browser's (a fact
#: about Next.js paths the backend cannot hold) and is pinned to this tuple from
#: the Python side, the way `journal_source.ALL_SOURCES` pins `sourceDocument.ts`.
ITEM_KEYS = (KEY_FILINGS_OVERDUE, KEY_BOOKS_FINDINGS, KEY_FILINGS_DUE_SOON, KEY_TASKS_OVERDUE)

ATTENTION, CLEAR, UNKNOWN = "attention", "clear", "unknown"


def _n(count: int, singular: str, plural: Optional[str] = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def _clients(counts: dict[str, int], names: dict[str, str]) -> tuple[list[dict], int]:
    """(the clients to name, the number of clients in all), biggest count first,
    then by name so the order is the same on every read."""
    rows = [{"client_id": cid, "client_name": names.get(cid) or "A client", "count": n}
            for cid, n in counts.items() if n > 0]
    rows.sort(key=lambda r: (-r["count"], r["client_name"].lower(), r["client_id"]))
    return rows[:MAX_CLIENTS_LISTED], len(rows)


def _item(key: str, *, label: str, status: str, count: Optional[int], headline: str,
          source: str, clients: Optional[list[dict]] = None, clients_total: int = 0,
          facts: Optional[dict] = None) -> dict:
    return {"key": key, "label": label, "status": status, "count": count,
            "headline": headline, "source": source,
            "clients": clients or [], "clients_total": clients_total,
            "facts": facts or {}}


# ── sections ─────────────────────────────────────────────────────────────────

def compliance_items(risk_clients: Iterable[dict]) -> list[dict]:
    """Overdue filings and filings falling due, from the compliance-risk rows.

    The totals are sums of the engine's own `overdue_count` / `due_soon_count`
    over the rows it returned for this caller, so the digest cannot disagree with
    the Insights page's table: it is that table, summed.
    """
    rows = list(risk_clients)
    names = {r["client_id"]: r.get("client_name") for r in rows if r.get("client_id")}
    source = "compliance risk (the Insights compliance-risk engine)"

    out = []
    for key, field, label, due_phrase in (
        (KEY_FILINGS_OVERDUE, "overdue_count", "Overdue filings", "overdue"),
        (KEY_FILINGS_DUE_SOON, "due_soon_count", f"Filings due in {DUE_SOON_DAYS} days",
         f"due within the next {DUE_SOON_DAYS} days"),
    ):
        per = {r["client_id"]: int(r.get(field) or 0) for r in rows if r.get("client_id")}
        total = sum(per.values())
        listed, clients_total = _clients(per, names)
        if total:
            headline = (f"{_n(total, 'filing')} {due_phrase} across "
                        f"{_n(clients_total, 'client')}")
            out.append(_item(key, label=label, status=ATTENTION, count=total,
                             headline=headline, source=source, clients=listed,
                             clients_total=clients_total))
        else:
            out.append(_item(key, label=label, status=CLEAR, count=0,
                             headline=f"No filings are {due_phrase}", source=source))
    return out


def task_item(overdue_tasks: Iterable[dict], user_id: Optional[str],
              names: dict[str, str]) -> dict:
    """Overdue tasks, from the rows `find_overdue` returned.

    `overdue_task_facts` (the Executive Dashboard's own function) gives the total
    and the unowned count; "assigned to you" is added because this is a PER-PERSON
    digest, and it reads the same two owner columns that function does
    (`assignee_id` is current, `assigned_to` the older one).
    """
    tasks = list(overdue_tasks)
    facts = ed.overdue_task_facts(tasks)
    total, unassigned = facts["overdue_tasks"], facts["unassigned_overdue_tasks"]
    mine = sum(1 for t in tasks
               if user_id and (t.get("assignee_id") or t.get("assigned_to")) == user_id)
    source = "overdue tasks (the Executive Dashboard's overdue-task read)"
    if not total:
        return _item(KEY_TASKS_OVERDUE, label="Overdue tasks", status=CLEAR, count=0,
                     headline="No tasks are overdue", source=source)
    per: dict[str, int] = {}
    for t in tasks:
        cid = t.get("client_id")
        if cid:
            per[str(cid)] = per.get(str(cid), 0) + 1
    listed, clients_total = _clients(per, names)
    headline = (f"{_n(total, 'task')} overdue — {mine} assigned to you, "
                f"{unassigned} with nobody assigned")
    return _item(KEY_TASKS_OVERDUE, label="Overdue tasks", status=ATTENTION, count=total,
                 headline=headline, source=source, clients=listed,
                 clients_total=clients_total,
                 facts={"assigned_to_you": mine, "unassigned": unassigned})


def latest_completed_run_per_client(runs: Iterable[dict]) -> dict[str, dict]:
    """Each client's most recent COMPLETED reconciliation run.

    Only the latest, and that is the point: the sweep inserts a fresh set of
    findings every night and never closes the old ones, so a finding raised on
    the first of the month and repeated nightly is thirty rows. Counting every
    unresolved row would report thirty findings for one problem.
    """
    best: dict[str, dict] = {}
    for r in runs:
        if r.get("status") != "completed" or not r.get("client_id"):
            continue
        cid = str(r["client_id"])
        cur = best.get(cid)
        key = (str(r.get("started_at") or ""), str(r.get("id") or ""))
        if cur is None or key > (str(cur.get("started_at") or ""), str(cur.get("id") or "")):
            best[cid] = r
    return best


def findings_item(latest_runs: dict[str, dict], open_findings: Iterable[dict],
                  names: dict[str, str]) -> dict:
    """The books-integrity findings the latest nightly checks left open.

    `open_findings` are the UNRESOLVED findings of exactly the runs in
    `latest_runs`. When no client has a completed check in the window the answer
    is UNKNOWN, never zero.
    """
    source = "the nightly books check (Verify Books)"
    label = "Books-integrity findings"
    if not latest_runs:
        return _item(KEY_BOOKS_FINDINGS, label=label, status=UNKNOWN, count=None,
                     headline=(f"No books check completed in the last {RUN_WINDOW_DAYS} days, "
                               f"so there is nothing to report"),
                     source=source)
    critical = other = 0
    per: dict[str, int] = {}
    for f in open_findings:
        cid = str(f.get("client_id") or "")
        if cid not in latest_runs:
            continue                      # a finding of an older run is not "latest"
        if f.get("severity") == "critical":
            critical += 1
        else:
            other += 1
        per[cid] = per.get(cid, 0) + 1
    checked = len(latest_runs)
    total = critical + other
    if not total:
        return _item(KEY_BOOKS_FINDINGS, label=label, status=CLEAR, count=0,
                     headline=(f"No open books-integrity findings in the latest checks of "
                               f"{_n(checked, 'client')}"),
                     source=source, facts={"clients_checked": checked})
    listed, clients_total = _clients(per, names)
    return _item(
        KEY_BOOKS_FINDINGS, label=label, status=ATTENTION, count=total,
        headline=(f"{critical} critical and {other} other books-integrity "
                  f"{'finding' if total == 1 else 'findings'} across "
                  f"{_n(clients_total, 'client')} in the latest checks"),
        source=source, clients=listed, clients_total=clients_total,
        facts={"critical": critical, "other": other, "clients_checked": checked})


# ── what is not here ─────────────────────────────────────────────────────────

NOT_INCLUDED = (
    ("gstr_2b",
     "GSTR-2B (bills missing in 2B) is not in this digest: that answer is worked out "
     "per client per return period when a reconciliation is opened and is not stored, "
     "and running the matcher for every client on each page load would read every "
     "client's purchase register."),
    ("rule_37a",
     "Rule 37A is not in this digest: whether a supplier has filed its GSTR-3B is not "
     "held anywhere in this product, so there is no count to give."),
    ("duplicate_bills",
     "Possible duplicate bills are not in this digest: they are checked as a bill is "
     "typed and no result is stored."),
    ("recurring_journals",
     "Recurring journal entries missing this month are not in this digest: that engine "
     "reads three months of every posted entry, which grows with the ledger."),
)


def not_included() -> list[str]:
    return [sentence for _key, sentence in NOT_INCLUDED]


def not_recently_checked(count: int) -> str:
    """Clients in scope with no completed books check in the window — reported
    beside the books section, because the section's figure says nothing about
    them (neither clear nor in trouble: not looked at)."""
    return (f"{_n(count, 'client')} had no completed books check in the last "
            f"{RUN_WINDOW_DAYS} days, so nothing is reported for "
            f"{'it' if count == 1 else 'them'}.")


def unreadable(label: str) -> str:
    return f"{label} could not be read just now, so it is missing from this digest."


def withheld(label: str, why: str) -> str:
    return f"{label} is not shown to you: {why}."


# ── the sentence ─────────────────────────────────────────────────────────────

def ordered(items: Iterable[dict]) -> list[dict]:
    """Attention first, then what was clear, then what nobody looked at; within a
    status, the engine order of `ITEM_KEYS`."""
    rank = {ATTENTION: 0, CLEAR: 1, UNKNOWN: 2}
    keys = {k: i for i, k in enumerate(ITEM_KEYS)}
    return sorted(items, key=lambda it: (rank.get(it["status"], 3), keys.get(it["key"], 99)))


def plain_summary(items: Iterable[dict]) -> str:
    """The sentence shown when no model wrote one, built from the same items.

    Lists what needs attention in order, then says what was checked and clear and
    what nobody looked at — so it is a complete account on its own, not a stub.
    """
    items = ordered(items)
    attention = [i["headline"] for i in items if i["status"] == ATTENTION]
    clear = [i["label"].lower() for i in items if i["status"] == CLEAR]
    unknown = [i["label"].lower() for i in items if i["status"] == UNKNOWN]
    if not items:
        return "Nothing could be read for this digest."
    parts = []
    if attention:
        parts.append("Needs attention: " + "; ".join(attention) + ".")
    else:
        parts.append("Nothing needs attention in what was checked.")
    if clear:
        parts.append("Checked and clear: " + ", ".join(clear) + ".")
    if unknown:
        parts.append("Not known: " + ", ".join(unknown) + ".")
    return " ".join(parts)


def allowed_figures(items: Iterable[dict], *, today_day: int, today_year: int) -> list:
    """The closed set of numbers a narration may contain: every count and fact an
    engine produced, the windows the sentences name, and today's date."""
    out: list = [DUE_SOON_DAYS, RUN_WINDOW_DAYS, today_day, today_year]
    for it in items:
        out.append(it.get("count"))
        out.append(it.get("clients_total"))
        out.extend((it.get("facts") or {}).values())
    return out


SYSTEM_PROMPT = (
    "You write the morning briefing for a chartered accountant who runs an Indian "
    "practice. You are given short factual lines already computed by the software. "
    "Word them as at most three plain sentences, most urgent first. Use ONLY the "
    "figures in the lines, exactly as given: do not add, derive, round or estimate any "
    "other figure, do not name clients, do not give advice, and do not mention any "
    "check that is not in the lines."
)


def narration_messages(items: Iterable[dict], *, today_label: str) -> list[dict]:
    """What the model is given: the section headlines and nothing that identifies a
    client. `facts` never contain a name, and the headlines are built from counts."""
    lines = []
    for it in ordered(items):
        status = {"attention": "needs attention", "clear": "checked, clear",
                  "unknown": "not known"}[it["status"]]
        lines.append(f"- {it['label']} ({status}): {it['headline']}")
    body = f"As at {today_label}:\n" + "\n".join(lines)
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": body}]
