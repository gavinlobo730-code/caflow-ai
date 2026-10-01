"""Fetches what `domain/practice/digest` assembles, and asks a model to WORD it.

`domain/practice/digest` is the rule: what each section is, which engine it comes
from and what the plain sentence says. This module calls those engines, narrows
every read to the caller's own clients, and — only when something needs
attention — asks `groq_text.chat` to put the computed lines into a short
paragraph. It decides nothing the domain module decides and invents no figure.

EVERY READ IS NARROWED TO THE CALLER'S CLIENTS
    `effective_client_ids` is None for a firm-wide role and a set of assigned ids
    otherwise, and it goes into every read: the compliance-risk engine takes it
    as a parameter, the overdue tasks and the books-check runs are filtered
    against it. A scoped Manager's digest therefore names only their clients and
    counts only theirs — the rule the Executive Dashboard learned (ai-09), applied
    here from the first line. A client the caller cannot see is not named in a
    section, in a count, or in the model's prompt.

EACH SECTION FOLLOWS THE ACCESS OF THE SCREEN IT SUMMARISES
    Compliance risk is `ai:read`, which is the route's own gate. Overdue tasks
    need `task:read`. The books-integrity findings are what "Verify Books" shows,
    and that router needs `accounting:approve`, so a caller without it does not get
    them in a digest either. A section withheld, or one that could not be read, is
    NAMED in `gaps` — a missing section reads as "nothing found" unless it says
    otherwise.

THE BOOKS FINDINGS ARE READ FROM THE LATEST COMPLETED RUN OF EACH CLIENT
    See `latest_completed_run_per_client`: the sweep never closes an old finding,
    so every unresolved row would count a persistent problem once per night. The
    runs are read inside a window of `RUN_WINDOW_DAYS` days (a read proportional
    to clients, not to history), and a client with no completed run in it is
    reported as not recently checked rather than as clear.

THE MODEL
    Called once at most per distinct set of facts: the narration is cached in the
    process under a hash of exactly what was sent, so opening the page ten times
    on a quiet morning is one call, and a change in any count is a new one. The
    COUNTS are never cached — they are read fresh each time, so the digest cannot
    lag the reports it summarises. The reply is read for figures and discarded if
    it carries one no engine computed. With no key, no answer, an error or a
    discarded reply the digest still appears, as the plain sentence, labelled
    `rule-based`. ⚠️ The cache is in-process, like the rate limiter: right for one
    worker, and a second worker simply makes its own call.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from starlette.concurrency import run_in_threadpool

from core.db_paging import fetch_all, fetch_all_in
from core.ist_clock import ist_now, ist_today
from core.permissions import can_user
from domain.ai import groq_text, narration
from domain.practice import digest

_logger = logging.getLogger("caflow.digest")

#: How long a worded narration is reused for the SAME facts. Facts that change
#: hash to a different key, so this only bounds how long an unchanged morning
#: keeps one sentence.
NARRATION_TTL_S = 6 * 60 * 60
NARRATION_MAX_ENTRIES = 256
_NARRATIONS: dict[str, tuple[float, str, str]] = {}


def _books_findings(firm_id: str, allowed: Optional[set], names: dict[str, str],
                    now: datetime) -> tuple[dict, list[str]]:
    """The books-check section, and any sentence about clients it could not cover."""
    from core.supabase_client import get_service_supabase

    db = get_service_supabase()
    cutoff = (now - timedelta(days=digest.RUN_WINDOW_DAYS)).isoformat()

    def runs_page():
        return (db.table("reconciliation_runs")
                .select("id, client_id, status, started_at")
                .eq("firm_id", firm_id).eq("status", "completed")
                .gte("started_at", cutoff))

    runs = fetch_all(runs_page, label="digest.reconciliation_runs")
    if allowed is not None:
        runs = [r for r in runs if str(r.get("client_id")) in allowed]
    latest = digest.latest_completed_run_per_client(runs)

    findings: list[dict] = []
    if latest:
        def findings_page():
            return (db.table("reconciliation_findings")
                    .select("id, client_id, run_id, severity, check_name")
                    .eq("firm_id", firm_id).is_("resolved_at", "null"))

        findings = fetch_all_in(
            findings_page, "run_id", [r["id"] for r in latest.values()],
            label="digest.reconciliation_findings")

    notes: list[str] = []
    if names and latest:
        missing = len(set(names) - set(latest))
        if missing:
            notes.append(digest.not_recently_checked(missing))
    return digest.findings_item(latest, findings, names), notes


def _visible(rows: list[dict], allowed: Optional[set]) -> list[dict]:
    """Rows of the caller's own clients. `allowed` None means firm-wide (no
    narrowing); an EMPTY set means nothing, never "no filter". A row with no
    client is firm-level and is kept — `core.authz.filter_by_client`'s rule, held
    here against the one `allowed` value the route resolved so every read in the
    digest is narrowed by the same set."""
    if allowed is None:
        return rows
    return [r for r in rows if not r.get("client_id") or str(r["client_id"]) in allowed]


def gather(current_user: dict, allowed: Optional[set], today: date,
           now: Optional[datetime] = None) -> dict:
    """Every section's engine answer for THIS caller: {items, gaps, scoped}.

    `allowed` is `effective_client_ids(current_user)`, resolved at the route where
    the scope is visible: None for a firm-wide role, the assigned ids otherwise.

    Synchronous (the engines and repositories are), and run on a thread by
    `todays_digest` so a slow read does not hold the event loop.
    """
    firm_id = current_user["firm_id"]
    now = now or datetime.now(timezone.utc)
    items: list[dict] = []
    gaps: list[str] = []
    names: dict[str, str] = {}

    # Filings: the compliance-risk engine, summed. The route's own gate (ai:read).
    try:
        from services.intelligence_service import compute_compliance_risk
        risk = compute_compliance_risk(firm_id, allowed)
        items.extend(digest.compliance_items(risk["clients"]))
        names = {c["client_id"]: c.get("client_name")
                 for c in risk["clients"] if c.get("client_id")}
    except Exception:                                           # noqa: BLE001
        _logger.warning("digest: compliance risk could not be read", exc_info=True)
        gaps.append(digest.unreadable("Compliance risk"))

    # Tasks.
    if can_user(current_user, "task", "read"):
        try:
            from repositories.task_repository import task_repo
            overdue = _visible(task_repo.find_overdue(firm_id=firm_id), allowed)
            items.append(digest.task_item(overdue, current_user.get("id"), names))
        except Exception:                                       # noqa: BLE001
            _logger.warning("digest: overdue tasks could not be read", exc_info=True)
            gaps.append(digest.unreadable("Overdue tasks"))
    else:
        gaps.append(digest.withheld("Overdue tasks", "your role does not include tasks"))

    # Books-integrity findings: Verify Books' own access.
    if can_user(current_user, "accounting", "approve"):
        try:
            item, notes = _books_findings(firm_id, allowed, names, now)
            items.append(item)
            gaps.extend(notes)
        except Exception:                                       # noqa: BLE001
            _logger.warning("digest: books findings could not be read", exc_info=True)
            gaps.append(digest.unreadable("Books-integrity findings"))
    else:
        gaps.append(digest.withheld(
            "Books-integrity findings",
            "they follow the access of the Verify Books screen, which needs approval "
            "rights on accounting"))

    return {"items": items, "gaps": gaps, "scoped": allowed is not None}


def _cache_key(firm_id: str, messages: list[dict]) -> str:
    return hashlib.sha256(
        (firm_id + "\n" + json.dumps(messages, sort_keys=True)).encode("utf-8")).hexdigest()


def _cache_get(key: str) -> Optional[tuple[str, str]]:
    hit = _NARRATIONS.get(key)
    if not hit:
        return None
    stamped, text, model = hit
    if time.monotonic() - stamped > NARRATION_TTL_S:
        _NARRATIONS.pop(key, None)
        return None
    return text, model


def _cache_put(key: str, text: str, model: str) -> None:
    if len(_NARRATIONS) >= NARRATION_MAX_ENTRIES:
        _NARRATIONS.pop(next(iter(_NARRATIONS)), None)      # the oldest insertion
    _NARRATIONS[key] = (time.monotonic(), text, model)


def reset_narration_cache() -> None:
    _NARRATIONS.clear()


async def narrate(firm_id: str, items: list[dict], today: date, *,
                  user_id: Optional[str] = None) -> Optional[tuple[str, str]]:
    """A model's wording of THESE items as (text, model), or None.

    None when there is nothing to word (no section needs attention), no key, the
    provider failed, or the reply carried a figure no engine computed — in every
    case the caller shows the plain sentence it already built.
    """
    if not any(i["status"] == digest.ATTENTION for i in items):
        return None
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None

    messages = digest.narration_messages(items, today_label=today.strftime("%d %B %Y"))
    key = _cache_key(firm_id, messages)
    cached = _cache_get(key)
    if cached:
        return cached

    try:
        text, _tokens = await groq_text.chat(
            messages, api_key=api_key, max_tokens=groq_text.NARRATION_MAX_TOKENS,
            reasoning_effort="low", feature="practice_digest", firm_id=firm_id,
            user_id=user_id)
    except groq_text.ProviderFailed as exc:
        _logger.warning("digest: no model narration (%s)", exc.sentence)
        return None
    except Exception as exc:                                    # noqa: BLE001
        _logger.warning("digest: no model narration (%s: %s)", type(exc).__name__, exc)
        return None

    text = (text or "").strip()
    if not text:
        return None
    allowed = digest.allowed_figures(items, today_day=today.day, today_year=today.year)
    if not narration.is_grounded(text, allowed):
        _logger.warning(
            "digest: the model's wording carried figures the engines did not compute (%s) "
            "— the plain sentence is shown", narration.ungrounded_numbers(text, allowed))
        return None
    model = groq_text.answered_by()
    _cache_put(key, text, model)
    return text, model


async def todays_digest(current_user: dict, allowed_client_ids: Optional[set], *,
                        today: Optional[date] = None) -> dict:
    """The caller's digest: items and gaps from the engines, a summary that is a
    model's wording of them or the plain sentence, and which of the two it is.

    `allowed_client_ids` has NO default, so a caller cannot forget it and read
    firm-wide by omission: None is spelled out at the call site and means a
    firm-wide role."""
    today = today or ist_today()
    gathered = await run_in_threadpool(gather, current_user, allowed_client_ids, today)
    items = digest.ordered(gathered["items"])

    worded = await narrate(current_user["firm_id"], items, today,
                           user_id=current_user.get("id"))
    return {
        "as_of": today.isoformat(),
        "generated_at": ist_now().isoformat(),
        "scoped": gathered["scoped"],
        "items": items,
        # What was left out is said on EVERY answer, so a short list is never
        # read as a clean one.
        "gaps": gathered["gaps"] + digest.not_included(),
        "summary": worded[0] if worded else digest.plain_summary(items),
        # "model" only when a model wrote it AND every figure in it was an
        # engine's; otherwise "rule-based", which is the label the numbers wear
        # in either case.
        "summary_source": "model" if worded else "rule-based",
        "model_used": worded[1] if worded else None,
        "basis": ("Every count comes from an existing check and equals what that "
                  "check reports; a model only words them."),
    }
