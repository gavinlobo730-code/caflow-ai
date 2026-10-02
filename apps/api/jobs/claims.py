"""The lock a scheduled job takes before it runs (ops-14).

WHAT WAS WRONG
    `jobs/scheduler.py` kept a job from running twice with a SELECT: read
    `scheduler_runs` for today's success and, finding none, run the job and write
    its row afterwards. `scheduler_runs` has no unique key, so nothing refused a
    second writer, and the window between the read and the write is as wide as the
    job. The per-minute workflow tick had no guard at all and said so ("NOT safe
    for multi-worker deployments"). With one instance that is a latent fact; with
    two — a rolling deploy overlapping the old process, or any standby — both run
    every job and fire every schedule, which for this product is every reminder
    and every recurring invoice twice.

WHAT THIS IS
    A claim row per (job, IST day, firm, claim key), taken by one SQL statement
    (migration 471, `claim_scheduler_job`) so exactly one claimant gets it, with a
    LEASE that expires. This module is the Python side of that and nothing more:
    it asks the database, it never decides who wins.

    * LEASE_SECONDS (10 minutes) is how long a DEAD instance can block a job. A
      claim whose holder has crashed is `running` with an expiry, and the next
      claimant after the expiry takes it over.
    * HEARTBEAT_SECONDS (3 minutes) is how often a LIVE holder renews, so a job
      that takes an hour is not stolen from at minute eleven. A holder that cannot
      renew (the database was away for a whole lease) finds out on `finish` — it
      is told the claim was no longer its own — and says so loudly, because the
      job it just ran has by then run twice.
    * The database's clock decides expiry, never this process's: two instances'
      clocks disagree and the database's does not.

THE TWO STORES
    `PostgrestClaimStore` is production. `MemoryClaimStore` models the same state
    machine in a dict and is what mock mode and the suite use. They are held to
    each other by `tests/_claim_scenarios.py`, run through both, because two
    implementations of one rule are two rules unless something says otherwise
    (CLAUDE.md, the reporting-performance parity rule). The memory store used by
    mock mode keeps NO HISTORY of finished claims (`persist_finished=False`):
    mock mode's history is `scheduler._MOCK_RUNS`, which a number of tests clear,
    and a success remembered here after they cleared it would make the next
    test's job skip itself.

WHEN THE CLAIM STORE IS NOT THERE
    Code and migration deploy on separate tracks (core/schema_guard.py's header
    is the history), so there is a window in which the API is live and migration
    471 is not. A missing function or table is the ONE failure treated as "behave
    as before this change": the job runs under the old select-then-run check, with
    an ERROR in the log, once per process. Every OTHER failure (the database
    unreachable, a timeout) refuses the claim and the job waits for the next
    trigger, because a lock that opens whenever it cannot be checked is not a
    lock.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from core import db_errors

logger = logging.getLogger("caflow.jobs.claims")

#: How long a DEAD holder can block a job. Also the lease a renewal grants.
LEASE_SECONDS = 600
#: How often a LIVE holder renews: a third of the lease, so two renewals can be
#: missed before the claim is lost.
HEARTBEAT_SECONDS = 180
#: How many days of claims `prune` keeps. A per-minute schedule leaves a row per
#: occurrence.
RETENTION_DAYS = 30

#: Who this process is: host, pid and a per-process random suffix. Two processes
#: on one host (a rolling deploy) differ by pid, a restarted one by the suffix.
INSTANCE_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

CLAIMED = "claimed"
ALREADY_SUCCEEDED = "already_succeeded"
HELD_BY_ANOTHER = "held_by_another"
RETRY_LATER = "retry_later"
STORE_UNAVAILABLE = "store_unavailable"
#: The database has no claim store yet (migration 471 not applied): run as before.
UNMANAGED = "unmanaged"

#: What a run's result says for each refusal. "already ran today" is the sentence
#: the sweep has always used and tests and screens read it.
SKIP_TEXT = {
    ALREADY_SUCCEEDED: "already ran today",
    HELD_BY_ANOTHER: "another instance is running it",
    RETRY_LATER: "failed recently and will be retried later",
    STORE_UNAVAILABLE: "could not take the claim, so it was not run; it will be retried",
}


@dataclass(frozen=True)
class Decision:
    """The answer to "may I run this?". `claim` is None unless it was taken, and
    also when the claim store does not exist yet (`reason == UNMANAGED`)."""
    claimed: bool
    claim: Optional["Claim"]
    reason: str

    @property
    def skip_text(self) -> str:
        return SKIP_TEXT.get(self.reason, self.reason)


# ── the stores ───────────────────────────────────────────────────────────────

class MemoryClaimStore:
    """The claim state machine in a dict. Mirrors `claim_scheduler_job` clause
    for clause; `tests/_claim_scenarios.py` runs the same table through both."""

    def __init__(self, *, clock: Callable[[], float] = time.time,
                 persist_finished: bool = True) -> None:
        self._clock = clock
        self._persist_finished = persist_finished
        self._lock = threading.Lock()
        self._rows: dict[tuple, dict] = {}

    # -- the contract every store keeps ----------------------------------------
    def claim(self, job_name: str, run_date, firm_id: str, claim_key: str, *, owner: str,
              lease_seconds: int, force: bool, retry_failed_after_seconds: int) -> dict:
        if lease_seconds < 30 or lease_seconds > 86400:
            raise ValueError("a lease is between 30 seconds and a day")
        key = (job_name, str(run_date), str(firm_id), claim_key or "")
        now = self._clock()
        with self._lock:
            row = self._rows.get(key)
            if row is None:
                row = {"id": str(uuid.uuid4()), "owner": owner, "status": "running",
                       "attempt": 1, "expires_at": now + lease_seconds, "finished_at": None,
                       "run_date": str(run_date)}
                self._rows[key] = row
                return {"claimed": True, "id": row["id"], "attempt": 1}
            may_take = (
                (row["status"] == "running" and row["expires_at"] <= now)
                or (row["status"] == "failed"
                    and (retry_failed_after_seconds <= 0 or row["finished_at"] is None
                         or row["finished_at"] <= now - retry_failed_after_seconds))
                or (row["status"] == "success" and force)
            )
            if not may_take:
                return {"claimed": False, "status": row["status"], "owner": row["owner"],
                        "expires_at": row["expires_at"]}
            row.update(owner=owner, status="running", attempt=row["attempt"] + 1,
                       expires_at=now + lease_seconds, finished_at=None)
            return {"claimed": True, "id": row["id"], "attempt": row["attempt"]}

    def renew(self, claim_id: str, owner: str, lease_seconds: int) -> bool:
        now = self._clock()
        with self._lock:
            for row in self._rows.values():
                if row["id"] == claim_id and row["owner"] == owner and row["status"] == "running":
                    row["expires_at"] = now + lease_seconds
                    return True
        return False

    def finish(self, claim_id: str, owner: str, status: str) -> bool:
        if status not in ("success", "failed"):
            raise ValueError("a claim finishes as success or failed")
        now = self._clock()
        with self._lock:
            for key, row in list(self._rows.items()):
                if row["id"] == claim_id and row["owner"] == owner and row["status"] == "running":
                    if self._persist_finished:
                        row.update(status=status, finished_at=now)
                    else:
                        del self._rows[key]
                    return True
        return False

    def prune(self, older_than_days: int) -> int:
        if older_than_days < 2:
            raise ValueError("keep at least two days")
        from core.ist_clock import ist_today
        cutoff = (ist_today() - timedelta(days=older_than_days)).isoformat()
        with self._lock:
            stale = [k for k, r in self._rows.items() if r["run_date"] < cutoff]
            for k in stale:
                del self._rows[k]
        return len(stale)

    # -- for tests ----------------------------------------------------------------
    def expire(self, job_name: str, run_date, firm_id: str, claim_key: str = "") -> None:
        """Make the live lease lapse, as if the holder had died a lease ago."""
        key = (job_name, str(run_date), str(firm_id), claim_key or "")
        with self._lock:
            self._rows[key]["expires_at"] = self._clock() - 1

    def rows(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._rows.values()]


class PostgrestClaimStore:
    """Production: the four functions of migration 471, over PostgREST, as the
    service role. `db` is a zero-argument callable returning the client, so the
    scheduler's own `_get_db` (which tests replace) stays the one seam."""

    def __init__(self, db: Callable[[], object]) -> None:
        self._db = db

    @staticmethod
    def _one(data):
        if isinstance(data, list):
            data = data[0] if data else None
        return data

    def claim(self, job_name: str, run_date, firm_id: str, claim_key: str, *, owner: str,
              lease_seconds: int, force: bool, retry_failed_after_seconds: int) -> dict:
        res = self._db().rpc("claim_scheduler_job", {
            "p_job_name": job_name,
            "p_run_date": str(run_date),
            "p_firm_id": str(firm_id),
            "p_owner": owner,
            "p_claim_key": claim_key or "",
            "p_lease_seconds": int(lease_seconds),
            "p_force": bool(force),
            "p_retry_failed_after_seconds": int(retry_failed_after_seconds),
        }).execute()
        data = self._one(res.data)
        if not isinstance(data, dict) or "claimed" not in data:
            raise RuntimeError("claim_scheduler_job answered something that is not a claim result")
        return data

    def renew(self, claim_id: str, owner: str, lease_seconds: int) -> bool:
        res = self._db().rpc("renew_scheduler_claim", {
            "p_id": str(claim_id), "p_owner": owner, "p_lease_seconds": int(lease_seconds),
        }).execute()
        return bool(self._one(res.data))

    def finish(self, claim_id: str, owner: str, status: str) -> bool:
        res = self._db().rpc("finish_scheduler_claim", {
            "p_id": str(claim_id), "p_owner": owner, "p_status": status,
        }).execute()
        return bool(self._one(res.data))

    def prune(self, older_than_days: int) -> int:
        res = self._db().rpc("prune_scheduler_claims", {
            "p_older_than_days": int(older_than_days)}).execute()
        got = self._one(res.data)
        return int(got) if isinstance(got, (int, float)) else 0


# ── which store ──────────────────────────────────────────────────────────────

_override = None
_shared_memory = MemoryClaimStore(persist_finished=False)


def set_store(store) -> None:
    """Tests: use this store whatever the mode. `None` puts the default back."""
    global _override
    _override = store


def memory_store() -> MemoryClaimStore:
    """The shared in-process store mock mode uses (no history; see the header)."""
    return _shared_memory


def store_for(*, mock: bool, db: Callable[[], object]):
    """The store a caller should use: a test's override, else memory in mock mode,
    else the database. The CALLER says whether it is in mock mode, because the
    scheduler's own `_USE_MOCK` is what the suite flips."""
    if _override is not None:
        return _override
    return memory_store() if mock else PostgrestClaimStore(db)


# ── a held claim ─────────────────────────────────────────────────────────────

class Claim:
    """A claim this process holds. `finish` it exactly once."""

    def __init__(self, store, claim_id: str, *, job_name: str, firm_id: str, claim_key: str,
                 run_date, attempt: int, owner: str, lease_seconds: int) -> None:
        self.store = store
        self.id = str(claim_id)
        self.job_name = job_name
        self.firm_id = str(firm_id)
        self.claim_key = claim_key
        self.run_date = str(run_date)
        self.attempt = attempt
        self.owner = owner
        self.lease_seconds = lease_seconds
        #: True once the database has told us the claim is no longer ours.
        self.lost = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start_heartbeat(self, interval: float = HEARTBEAT_SECONDS) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._beat, args=(interval,), name=f"claim-heartbeat-{self.job_name}",
            daemon=True)
        self._thread.start()

    def _beat(self, interval: float) -> None:
        while not self._stop.wait(interval):
            try:
                ok = self.store.renew(self.id, self.owner, self.lease_seconds)
            except Exception:                                       # noqa: BLE001
                # One missed renewal is survivable (the lease is three beats long);
                # the next beat tries again.
                logger.warning("claim heartbeat for %s (firm %s) could not renew",
                               self.job_name, self.firm_id, exc_info=True)
                continue
            if self._stop.is_set():
                return                      # finished while we were asking: not a loss
            if not ok:
                self.lost = True
                logger.error(
                    "scheduler claim for %s (firm %s) is no longer this instance's: its lease "
                    "lapsed and another instance took it over, so this job is now running twice",
                    self.job_name, self.firm_id)
                return

    def finish(self, ok: bool) -> bool:
        """Say how the job ended. False if the claim was no longer ours."""
        self._stop.set()
        try:
            held = bool(self.store.finish(self.id, self.owner, "success" if ok else "failed"))
        except Exception:                                           # noqa: BLE001
            logger.warning("could not record the end of the claim for %s (firm %s); its lease "
                           "will expire on its own", self.job_name, self.firm_id, exc_info=True)
            return False
        if not held:
            self.lost = True
            logger.error(
                "scheduler claim for %s (firm %s) was no longer this instance's when the job "
                "finished: another instance had taken it over and ran it as well",
                self.job_name, self.firm_id)
        return held


# ── asking ───────────────────────────────────────────────────────────────────

_unmanaged_warned = False


def _is_missing_store(exc: Exception) -> bool:
    """True for "the function or table is not in this database" and nothing else."""
    return db_errors.is_missing_store(exc, name="claim_scheduler_job")


def claim(job_name: str, firm_id: str, *, run_date, claim_key: str = "", force: bool = False,
          heartbeat: bool = False, lease_seconds: int = LEASE_SECONDS,
          retry_failed_after_seconds: int = 0, store, owner: Optional[str] = None) -> Decision:
    """May this process run (job, day, firm, key)? Never raises."""
    global _unmanaged_warned
    owner = owner or INSTANCE_ID
    try:
        raw = store.claim(job_name, run_date, firm_id, claim_key, owner=owner,
                          lease_seconds=lease_seconds, force=force,
                          retry_failed_after_seconds=retry_failed_after_seconds)
    except Exception as exc:                                        # noqa: BLE001
        if _is_missing_store(exc):
            if not _unmanaged_warned:
                _unmanaged_warned = True
                logger.error(
                    "scheduler claims are NOT in force: this database has no claim_scheduler_job "
                    "(migration 471 has not been applied). Jobs run under the old select-then-run "
                    "check, which is not safe for two instances. %s", exc)
            return Decision(True, None, UNMANAGED)
        logger.error("could not take the scheduler claim for %s (firm %s): %s: %s",
                     job_name, firm_id, type(exc).__name__, exc)
        return Decision(False, None, STORE_UNAVAILABLE)

    if raw.get("claimed"):
        held = Claim(store, raw["id"], job_name=job_name, firm_id=firm_id, claim_key=claim_key,
                     run_date=run_date, attempt=int(raw.get("attempt") or 1), owner=owner,
                     lease_seconds=lease_seconds)
        if heartbeat:
            held.start_heartbeat()
        return Decision(True, held, CLAIMED)
    reason = {"success": ALREADY_SUCCEEDED, "running": HELD_BY_ANOTHER,
              "failed": RETRY_LATER}.get(raw.get("status"), HELD_BY_ANOTHER)
    return Decision(False, None, reason)


def prune(store, days: int = RETENTION_DAYS) -> int:
    """Forget old days. Best effort: a claim table that cannot be pruned is a
    bigger table, not a failed sweep."""
    try:
        return int(store.prune(days))
    except Exception:                                               # noqa: BLE001
        logger.warning("could not prune scheduler claims", exc_info=True)
        return 0


def ist_date_of(instant: object, fallback: date) -> date:
    """The IST calendar day of an ISO timestamp, or `fallback` where it does not
    parse. A workflow occurrence is keyed on the day it is DUE, not the day it
    happens to be read, so its key does not change across midnight."""
    from core.ist_clock import IST
    try:
        text = str(instant).strip()
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            from datetime import timezone
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(IST).date()
    except (ValueError, TypeError):
        return fallback
