"""An endpoint that COMPUTES something and reaches no screen is named here.

── WHY THIS IS NOT THE REACHABILITY RATCHET ─────────────────────────────────

`test_every_mounted_endpoint_has_a_way_in` already counts endpoints no screen
reaches and holds the count down. It is a good guard and it did not stop the
AS 18 related-party note being built, mounted and invisible for months —
because `/api/relationships/related-party-report` was one of SEVEN inside that
prefix's budget, and a budget is a NUMBER. Nothing about `7` said that one of
the seven was a statutory disclosure a CA cannot file without.

⚠️ THE SHAPE HAS A NAME IN THIS CODEBASE AND IT KEEPS RECURRING. `capital_wip`
was a declared year-end line nothing could reach. The AS 11 FX revaluation was
complete, idempotent, period-aware and had ZERO production importers.
`domain/income_tax/regime_election` was fully modelled and its only mention
outside its own tests was a COMMENT. `invoice_templates` and `email_templates`
were written by two full Settings screens that no backend code read.
`POST /api/itr/snapshots/{id}/review` existed from the start with no caller, so
every computation stayed permanently `draft`. Each was invisible until somebody
read the callers, and each cost a CA something real.

── THE RULE ─────────────────────────────────────────────────────────────────

A GET that serves a COMPUTED ANSWER — a report, a summary, a reconciliation, a
position, an analysis — and that no screen reaches is either wired up, deleted,
or WRITTEN DOWN HERE WITH A REASON. The list is frozen as an EQUALITY rather
than a budget, for the reason `objectWithLists`' own guard gives: a count can
absorb a new offender silently, and a fix that leaves its entry behind should
fail as loudly as a regression.

⚠️ THE WORD LIST IS A HEURISTIC AND THIS TEST SAYS SO. It triages; it does not
define. A computed answer whose path says none of these words is still one, and
the honest statement is that this catches the ones that ANNOUNCE themselves.
That is a reason to read the whole unreached list occasionally, not a reason to
skip the ones that do announce themselves.
"""
import pytest

from tests.test_every_mounted_endpoint_has_a_way_in import _pattern, _routes, _sources


#: Path fragments that mark a response as a computed ANSWER rather than a row
#: fetch or a write. A heuristic — see the module docstring.
ANSWER_WORDS = (
    "report", "compute", "summary", "preview", "register", "statement",
    "disclosure", "projection", "forecast", "working", "analysis", "analytics",
    "ageing", "aging", "reconcil", "position", "movement", "trend",
    "breakdown", "keying", "sheet",
)

#: Every computed answer no screen reaches, and WHY that is acceptable today.
#: Measured 25-09-2026. This may only shrink: wire it, delete it, or argue here.
#:
#: Three left this list on 25-09 and are recorded because the reasons differ —
#: `/relationships/related-party-report` was WIRED (the AS 18 note now has a
#: screen), `/vendors/{id}/statement` was WIRED (the AP mirror of the Sales
#: Statements tab), and `/banking/reconciliations/{id}/items` was DELETED as a
#: byte-identical duplicate of `/report`, which the screen already calls.
UNREACHED_COMPUTED_ANSWERS: dict[str, str] = {
    "/api/analytics/clients":
        "Superseded by the per-client screens and the hub, which answer the same "
        "questions at the scope a CA asks them. A candidate for D21's treatment "
        "(delete a dead endpoint that duplicates a live one) once somebody has "
        "confirmed nothing in it is unique.",
    "/api/analytics/firm":
        "Same as /analytics/clients. `/practice/profitability` and `/insights` "
        "are the live firm-level answers.",
    "/api/analytics/team":
        "Same again; `/team/workload` and `/team/work-allocation` are live.",
    "/api/banking/statements/column-mappings":
        "Its own docstring says it exists 'so a CA can see and correct what a "
        "bank taught us' — and no screen shows them. A real gap, and a small "
        "one: it belongs beside the statement import, not on a page of its own.",
    "/api/compliance-records/firm/summary":
        "The firm-level compliance roll-up. `/deadlines` and the hub's Compliance "
        "tile answer the same question from `compliance_calendar`; this reads "
        "`compliance_records`, which is a different table with a different "
        "population. Whether the two agree has not been checked.",
    "/api/customer-statements/deliveries":
        "The delivery LOG for statements the CA has emailed. The send path is "
        "live and writes it; nothing reads it back, so a CA cannot see whether a "
        "statement they sent actually went out.",
    "/api/form-26as/reconciliation":
        "The client-as-DEDUCTEE 26AS reconciliation. The client-as-DEDUCTOR one "
        "(`/tds-workspace/form26as/upload`) has a screen; this one does not. "
        "⚠️ NOT the same reconciliation — `domain/income_tax/form26as_matcher` "
        "keys on the DEDUCTOR's TAN and `domain/tds/deductor_26as` on the "
        "DEDUCTEE's PAN, and each module says so.",
    "/api/memory/year-end-reports":
        "The copilot's stored year-end summaries. The year-end pack itself is "
        "live and is the document a CA works from; this is the AI's own "
        "recollection of it and has no screen by design.",
    "/api/memory/year-end-reports/{client_id}/{financial_year}":
        "The same stored recollection, for one client and one year. Unreached "
        "for the same reason as the list above it: the year-end pack is the "
        "document a CA works from and it is live.",
    "/api/relationships/loans/section-185-report":
        "Companies Act s.185 — loans to directors. The AS 18 note now renders "
        "the same flagged loans (`section_185_loans`) through "
        "`/related-party-report`, so the fact IS on a screen; this endpoint is "
        "the firm-wide roll-up of it and is unreached. `/relationships/"
        "intelligence` filters `section_185_flagged` in the BROWSER instead, "
        "which is the 'zero business logic in the frontend' rule broken — the "
        "next thing to fix here.",
    "/api/tasks/summary/dashboard":
        "A task roll-up. `/work` and the hub's Compliance tile are the live "
        "answers; this predates both.",
    "/api/time-entries/summary/me":
        "'My time this week'. `/time` lists the entries and totals them on the "
        "screen, so the figure is visible; the endpoint is the server's version "
        "of it and nothing calls it.",
}


def _unreached_computed() -> set[str]:
    body = _sources()
    return {
        path for method, path in _routes()
        if method == "GET"
        and not _pattern(path).search(body)
        and any(w in path.lower() for w in ANSWER_WORDS)
    }


def test_the_walk_finds_routes_at_all():
    """Non-vacuity. A guard that scans nothing asserts nothing, and four in this
    repository's history went inert exactly that way."""
    routes = _routes()
    assert len(routes) > 900, f"only {len(routes)} routes walked"
    assert any(m == "GET" for m, _ in routes)


def test_the_heuristic_matches_something_that_is_reached():
    """The negative control for the word list. If NO reached endpoint matched
    it, the list would be selecting on 'unreached' rather than on 'computes an
    answer', and the reasons below would be describing the wrong population."""
    body = _sources()
    reached = [p for m, p in _routes()
               if m == "GET" and _pattern(p).search(body)
               and any(w in p.lower() for w in ANSWER_WORDS)]
    assert len(reached) > 10, (
        f"only {len(reached)} REACHED endpoints match the answer-words — the "
        "heuristic is selecting on reachability, not on shape"
    )


def test_every_computed_answer_nobody_can_open_is_named_with_a_reason():
    found = _unreached_computed()
    named = set(UNREACHED_COMPUTED_ANSWERS)

    unnamed = found - named
    assert not unnamed, (
        "these endpoints compute an answer and no screen reaches it, and they "
        "are not in UNREACHED_COMPUTED_ANSWERS. Wire one up, delete it, or add "
        "it here with the reason a CA cannot see it: " + str(sorted(unnamed))
    )

    stale = named - found
    assert not stale, (
        "these are named as unreachable and are now reached (or gone) — remove "
        "the entry in the same commit, or the next reader trusts a list that is "
        "describing the past: " + str(sorted(stale))
    )


@pytest.mark.parametrize("path", sorted(UNREACHED_COMPUTED_ANSWERS))
def test_each_reason_says_something(path):
    """A reason of 'TODO' or 'unused' is how this list stops being read."""
    reason = UNREACHED_COMPUTED_ANSWERS[path]
    assert len(reason) > 60, f"{path}'s reason is too short to be one"
    assert "TODO" not in reason and "FIXME" not in reason
