"""POST-A-485, 497 — the sign-up links the server keeps (mock + Supabase). Migration 771.

One row per address holds the HASH of the mailed link's secret (never the secret), the firm name and the person's name typed on the
sign-up form, and when the link stops working. The table carries no firm: the person has not signed up yet. The privileged client is the
only reader and writer (the signed-in database roles hold nothing on it), and every query names the address or the hash it is about, so
there is no listing. Rules (who may ask again, how long a link lives) are `domain/firm/signup_link`; this file only stores.
"""
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from core import db_provider

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_MOCK_ROWS: dict[str, dict] = {}                       # keyed by address
_MOCK_LOCK = threading.Lock()                          # makes the mock's compare-and-set one step, as the database's statement is

_db = db_provider.service_db

#: The columns a link row carries and the service sets itself (`id` is the database's).
COLUMNS = ("email", "firm_name", "full_name", "token_hash", "expires_at", "sent_at", "send_count", "window_started_at", "created_at")


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _row(values: Mapping[str, Any]) -> dict:
    return {k: _iso(values[k]) for k in COLUMNS if k in values}


def _is_unique_violation(exc: Exception) -> bool:
    """PostgREST's answer to an insert the unique index refuses (23505), read off the code where the client gives one and its words otherwise."""
    return getattr(exc, "code", None) == "23505" or "duplicate key" in str(exc).lower()


class SignupLinkRepository:
    def find_by_email(self, email: str) -> Optional[dict]:
        """The address's one row, or None."""
        if _USE_MOCK:
            row = _MOCK_ROWS.get(email)
            return dict(row) if row else None
        res = _db().table("signup_links").select("*").eq("email", email).maybe_single().execute()
        return res.data or None

    def find_by_token_hash(self, token_hash: str) -> Optional[dict]:
        """The row a link's stored form names, whatever its expiry (the caller judges that), or None."""
        if _USE_MOCK:
            for row in _MOCK_ROWS.values():
                if row["token_hash"] == token_hash:
                    return dict(row)
            return None
        res = _db().table("signup_links").select("*").eq("token_hash", token_hash).maybe_single().execute()
        return res.data or None

    def claim(self, email: str, previous: Optional[Mapping[str, Any]], values: Mapping[str, Any]) -> Optional[dict]:
        """Write the address's next link, IF NOBODY HAS WRITTEN THE ROW SINCE `previous` WAS READ, and say whether it was written (None when it was
        not). A compare-and-set: the first request for an address inserts (a second insert meets the unique index), a later one updates only the row
        that still holds the link it read. Reading the row, judging it and writing it are three steps, and two requests that overlap would both
        pass the judging and both write: the per-address cooldown and the hourly cap would then bind nothing. The earlier link no longer names a
        row once this one is written, so it stops working. Raises if the write fails, so a link is never mailed that was not stored."""
        row = _row(values)
        if _USE_MOCK:
            with _MOCK_LOCK:
                current = _MOCK_ROWS.get(email)
                if previous is None:
                    if current is not None:
                        return None
                    _MOCK_ROWS[email] = {"id": f"sl-{uuid.uuid4().hex[:8]}", **row}
                else:
                    if current is None or current["token_hash"] != previous["token_hash"]:
                        return None
                    _MOCK_ROWS[email] = {**current, **row}
                return dict(_MOCK_ROWS[email])
        # The payloads below are written out column by column and not built from `COLUMNS`: the backend's schema guard
        # (`tests/test_backend_columns_exist_pg.py`) reads a payload only when it is a dict literal at the call, and a column a typo
        # renamed would otherwise be invisible to it.
        if previous is None:
            try:
                res = _db().table("signup_links").insert({
                    "email": email, "firm_name": values["firm_name"], "full_name": values["full_name"], "token_hash": values["token_hash"],
                    "expires_at": _iso(values["expires_at"]), "sent_at": _iso(values["sent_at"]), "send_count": values["send_count"],
                    "window_started_at": _iso(values["window_started_at"]), "created_at": _iso(values["created_at"]),
                }).execute()
            except Exception as exc:                    # noqa: BLE001 — only the unique index's refusal is "somebody was first"
                if _is_unique_violation(exc):
                    return None
                raise
            return (res.data or [row])[0]
        res = (_db().table("signup_links")
               .update({
                   "firm_name": values["firm_name"], "full_name": values["full_name"], "token_hash": values["token_hash"],
                   "expires_at": _iso(values["expires_at"]), "sent_at": _iso(values["sent_at"]), "send_count": values["send_count"],
                   "window_started_at": _iso(values["window_started_at"]), "created_at": _iso(values["created_at"]),
               })
               .eq("email", email).eq("token_hash", previous["token_hash"]).execute())
        return res.data[0] if res.data else None

    def put_back(self, email: str, previous: Optional[Mapping[str, Any]], *, replacing: str) -> bool:
        """Undo a `save` whose mail did not go: the row `previous` is restored, or the new row removed when there was none. It acts only
        while the row still holds the link THIS request wrote (`replacing` is its hash), so a newer request that landed while the mail was
        being sent is never undone. True when something was put back or removed."""
        if _USE_MOCK:
            with _MOCK_LOCK:
                current = _MOCK_ROWS.get(email)
                if not current or current["token_hash"] != replacing:
                    return False
                if previous:
                    _MOCK_ROWS[email] = {**current, **_row(previous)}
                else:
                    del _MOCK_ROWS[email]
                return True
        if previous:
            res = (_db().table("signup_links")
                   .update({
                       "firm_name": previous["firm_name"], "full_name": previous["full_name"], "token_hash": previous["token_hash"],
                       "expires_at": _iso(previous["expires_at"]), "sent_at": _iso(previous["sent_at"]),
                       "send_count": previous["send_count"], "window_started_at": _iso(previous["window_started_at"]),
                       "created_at": _iso(previous["created_at"]),
                   })
                   .eq("email", email).eq("token_hash", replacing).execute())
        else:
            res = _db().table("signup_links").delete().eq("email", email).eq("token_hash", replacing).execute()
        return bool(res.data)

    def delete_by_email(self, email: str) -> None:
        """The practice was created (or the person gave up): the address's link is of no further use."""
        if _USE_MOCK:
            _MOCK_ROWS.pop(email, None)
            return
        _db().table("signup_links").delete().eq("email", email).execute()

    def delete_expired_before(self, cutoff: datetime) -> None:
        """Remove links that expired before `cutoff`. Housekeeping: nothing reads an expired row but the page that says it is gone."""
        if _USE_MOCK:
            for email in [e for e, r in _MOCK_ROWS.items() if str(r["expires_at"]) < _iso(cutoff)]:
                del _MOCK_ROWS[email]
            return
        _db().table("signup_links").delete().lt("expires_at", _iso(cutoff)).execute()

    @staticmethod
    def reset_mock() -> None:
        """For tests: forget every mock row."""
        _MOCK_ROWS.clear()


signup_link_repo = SignupLinkRepository()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
