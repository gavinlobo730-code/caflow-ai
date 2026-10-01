"""What the AI has been seen to do, for the Partner who has to trust it. (ai-06)

TWO WITNESSES, AND THEY ANSWER DIFFERENT QUESTIONS.
    * THIS PROCESS (`domain/ai/gateway.last_success`): the last thing this
      server instance saw each provider do, for any firm and any feature. It is
      memory, so a restart forgets it and the honest answer after one is
      `unverified`. It is the one `/health` reports.
    * THIS FIRM'S USAGE ROWS (`ai_usage_events`, migration 465): the last time a
      call made for THIS firm was answered, and the last attempt at all. It
      survives a restart and a deploy, and it is tenant-scoped like every other
      read here — one firm's screen never shows another's calls.

    Neither says anything about a feature nobody has used, and the answer says
    so rather than reading an empty history as a clean one.

NOTHING HERE MAKES A MODEL CALL. The probe is `domain/ai/probe` behind its own
rate-limited route; reading the status is free and unlimited.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Optional

from domain.ai import gateway, gemini_vision, groq_text, probe

_logger = logging.getLogger("caflow.ai.status")

#: Said once, on every answer, so an empty section is never read as "all clear".
NOT_COVERED = (
    "This shows whether the configured key and model answered a request, not that "
    "every feature works: a long invoice, a scanned PDF or a particular prompt can "
    "still fail where a one-word request does not.",
    "The in-process view forgets everything when the server restarts; until a call is "
    "made after a restart it reads \"unverified\", which is not the same as failing.",
    "The usage history below is this firm's own; it says nothing about other firms' calls.",
)


#: What each status word is called on the screen and how the chip is toned, so the
#: browser holds neither: ready / problem / attention / neutral. `unverified` is
#: ATTENTION and not neutral, because "nobody has seen it answer" is the thing the
#: screen exists to end; `not_configured` is neutral — a deployment may
#: legitimately have no Gemini key, and that is not a fault.
PRESENTATION = {
    gateway.STATUS_OK: ("Answering", "ready"),
    gateway.STATUS_FAILING: ("Last attempt failed", "problem"),
    gateway.STATUS_UNVERIFIED: ("Not asked since this server started", "attention"),
    gateway.STATUS_NOT_CONFIGURED: ("No key set", "neutral"),
}


def _iso(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return _dt.datetime.fromtimestamp(epoch, tz=_dt.timezone.utc).isoformat()


def _seen(seen: Optional[gateway.Seen]) -> Optional[dict]:
    if seen is None:
        return None
    return {
        "model": seen.model, "outcome": seen.outcome, "at": _iso(seen.at),
        "latency_ms": seen.latency_ms, "total_tokens": seen.total_tokens,
        "http_status": seen.http_status,
    }


def health_words() -> dict[str, str]:
    """One word per provider and nothing else — the only part of this module meant
    for an unauthenticated route. No model name, no key state beyond the word,
    no time: those are configuration and belong behind a login."""
    return {p: gateway.provider_status(p, probe.configured(p)) for p in probe.PROVIDERS}


def _fallbacks(provider: str) -> list[str]:
    return groq_text.fallback_models() if provider == "groq" else gemini_vision.fallback_models()


def _row(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    return {
        "model": row.get("model"), "feature": row.get("feature"),
        "outcome": row.get("outcome"), "at": row.get("created_at"),
        "latency_ms": row.get("latency_ms"), "total_tokens": row.get("total_tokens"),
    }


def _firm_history(db: Any, firm_id: str, provider: str) -> dict:
    """The last answered call and the last attempt for this firm and provider.
    Two reads of one row each, so what crosses the wire is the size of the answer.
    The projection is a literal because the column checker reads it."""
    last_answered = (
        db.table("ai_usage_events")
        .select("model, feature, outcome, latency_ms, total_tokens, created_at")
        .eq("firm_id", firm_id).eq("provider", provider)
        .in_("outcome", sorted(gateway.ANSWERED))
        .order("created_at", desc=True).limit(1).execute().data or [])
    last_attempt = (
        db.table("ai_usage_events")
        .select("model, feature, outcome, latency_ms, total_tokens, created_at")
        .eq("firm_id", firm_id).eq("provider", provider)
        .neq("outcome", gateway.PARAM_REJECTED)
        .order("created_at", desc=True).limit(1).execute().data or [])
    return {"last_answered": _row(last_answered[0] if last_answered else None),
            "last_attempt": _row(last_attempt[0] if last_attempt else None)}


def status(db: Any, firm_id: str) -> dict:
    """Everything the Partner's screen shows. `db` may be None (no database on this
    deployment): the stored history is then `None` for every provider, said as
    such, never an empty history."""
    providers = []
    for p in probe.PROVIDERS:
        configured = probe.configured(p)
        history: Optional[dict] = None
        history_unread: Optional[str] = None
        if db is None:
            history_unread = "This server has no database, so no usage history is kept."
        else:
            try:
                history = _firm_history(db, firm_id, p)
            except Exception:                                    # noqa: BLE001
                _logger.warning("ai status: could not read the usage history", exc_info=True)
                history_unread = "The usage history could not be read just now."
        word = gateway.provider_status(p, configured)
        providers.append({
            "provider": p,
            "label": gateway.GROQ.name if p == "groq" else gateway.GEMINI.name,
            "configured": configured,
            "model": probe.configured_model(p),
            "fallback_models": _fallbacks(p),
            "status": word,
            "status_label": PRESENTATION[word][0],
            "status_tone": PRESENTATION[word][1],
            "this_process": {
                "last_attempt": _seen(gateway.last_attempt(p)),
                "last_success": _seen(gateway.last_success(p)),
            },
            "this_firm": history,
            "this_firm_unread": history_unread,
        })
    return {"providers": providers, "not_covered": list(NOT_COVERED)}
