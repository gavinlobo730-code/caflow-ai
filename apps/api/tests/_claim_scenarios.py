"""The claim state machine as a TABLE, so two implementations are held to it (ops-14).

`jobs/claims.MemoryClaimStore` (mock mode, the suite) and the SQL functions of migration 471
(`claim_scheduler_job` and friends, production) are one rule written twice. CLAUDE.md's
reporting-performance rule for exactly this: "Adding the second implementation without the
parity test is the thing not to do." This module is that parity test's content. Each scenario
is a list of steps; `run` drives a step list through an ADAPTER and asserts what every step
expected, and the same scenarios run against the in-memory store in the mock-mode suite
(`test_a_scheduled_job_is_claimed_before_it_runs.py`) and against real Postgres
(`test_471_a_scheduled_job_is_claimed_before_it_runs_pg.py`).

An adapter has four methods:

    claim(job, date, firm, key, owner, force, retry_after) -> dict   # claimed/id/attempt | status
    finish(claim_id, owner, status) -> bool
    renew(claim_id, owner) -> bool
    expire(job, date, firm, key) -> None        # make the live lease lapse
"""
from __future__ import annotations

FIRM_A = "47100000-0000-0000-0000-0000000000a1"
FIRM_B = "47100000-0000-0000-0000-0000000000b2"
D1 = "2026-10-01"
D2 = "2026-10-02"
JOB = "recurring_generation"


def claim(label, owner, *, claimed, attempt=None, status=None, firm=FIRM_A, date=D1, key="",
          job=JOB, force=False, retry_after=0):
    return ("claim", dict(label=label, owner=owner, claimed=claimed, attempt=attempt,
                          status=status, firm=firm, date=date, key=key, job=job, force=force,
                          retry_after=retry_after))


def finish(label, owner, as_, *, held):
    return ("finish", dict(label=label, owner=owner, status=as_, held=held))


def renew(label, owner, *, held):
    return ("renew", dict(label=label, owner=owner, held=held))


def expire(label):
    return ("expire", dict(label=label))


SCENARIOS: dict[str, list] = {
    "a second claimant is refused while the first is running": [
        claim("a", "inst-A", claimed=True, attempt=1),
        claim("b", "inst-B", claimed=False, status="running"),
    ],
    "a success is final for the day and force retakes it": [
        claim("a", "inst-A", claimed=True, attempt=1),
        finish("a", "inst-A", "success", held=True),
        claim("b", "inst-B", claimed=False, status="success"),
        claim("c", "inst-B", claimed=True, attempt=2, force=True),
    ],
    "force never takes a claim that is live": [
        claim("a", "inst-A", claimed=True, attempt=1),
        claim("b", "inst-B", claimed=False, status="running", force=True),
    ],
    "a failed run is retaken by the next claimant": [
        claim("a", "inst-A", claimed=True, attempt=1),
        finish("a", "inst-A", "failed", held=True),
        claim("b", "inst-B", claimed=True, attempt=2),
    ],
    "a failed run can be held back by a cooldown": [
        claim("a", "inst-A", claimed=True, attempt=1),
        finish("a", "inst-A", "failed", held=True),
        claim("b", "inst-B", claimed=False, status="failed", retry_after=3600),
        claim("c", "inst-B", claimed=True, attempt=2, retry_after=0),
    ],
    "a dead holder's claim is taken over after its lease and it can no longer end or renew it": [
        claim("a", "inst-A", claimed=True, attempt=1),
        expire("a"),
        claim("b", "inst-B", claimed=True, attempt=2),
        finish("a", "inst-A", "success", held=False),
        renew("a", "inst-A", held=False),
        finish("b", "inst-B", "success", held=True),
    ],
    "a live holder renews its own claim": [
        claim("a", "inst-A", claimed=True, attempt=1),
        renew("a", "inst-A", held=True),
        claim("b", "inst-B", claimed=False, status="running"),
    ],
    "another owner cannot end a claim it does not hold": [
        claim("a", "inst-A", claimed=True, attempt=1),
        finish("a", "inst-B", "success", held=False),
        claim("c", "inst-C", claimed=False, status="running"),
    ],
    "a claim for another day, firm or key is independent": [
        claim("a", "inst-A", claimed=True, attempt=1),
        claim("b", "inst-B", claimed=True, attempt=1, date=D2),
        claim("c", "inst-B", claimed=True, attempt=1, firm=FIRM_B),
        claim("d", "inst-B", claimed=True, attempt=1, key="sched-1@2026-10-01T00:30:00+00:00"),
        claim("e", "inst-B", claimed=True, attempt=1, job="escalations"),
        claim("f", "inst-B", claimed=False, status="running"),
    ],
}


def run(adapter, steps: list) -> None:
    held: dict[str, dict] = {}
    for kind, p in steps:
        if kind == "claim":
            got = adapter.claim(p["job"], p["date"], p["firm"], p["key"], p["owner"],
                                p["force"], p["retry_after"])
            assert bool(got["claimed"]) is p["claimed"], (p, got)
            if p["claimed"]:
                assert got["attempt"] == p["attempt"], (p, got)
                held[p["label"]] = {**p, "id": got["id"]}
            else:
                assert got["status"] == p["status"], (p, got)
        elif kind == "finish":
            ref = held[p["label"]]
            assert adapter.finish(ref["id"], p["owner"], p["status"]) is p["held"], p
        elif kind == "renew":
            ref = held[p["label"]]
            assert adapter.renew(ref["id"], p["owner"]) is p["held"], p
        elif kind == "expire":
            ref = held[p["label"]]
            adapter.expire(ref["job"], ref["date"], ref["firm"], ref["key"])
        else:  # pragma: no cover
            raise AssertionError(kind)
