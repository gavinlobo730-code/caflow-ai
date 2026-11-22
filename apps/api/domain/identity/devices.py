"""Which devices a login is signed in on (POST-A-486): the rule for "live", the words for a browser, and the sentence.

A person's login works on any number of devices at once and nothing caps that (the owner's decision of 18-11-2026: a CA firm's
staff legitimately use an office computer and a phone). What the product owes is that two devices can be TOLD APART: each
sign-in records the address our own proxy wrote and the browser, under the sign-in service's session id, and the Team screen and
the person's own Security page list the sessions that are still live.

"Live" is a statement about what the SERVER last heard, and it is built from the same two numbers the browser keeps (POST-A-483):
a tab signs itself out after `IDLE_LIMIT_MINUTES` without a key or a touch, and while somebody is at the keyboard it tells the
server it is still there every `SEEN_EVERY_MINUTES`. So a session the server has not heard from in the sum of the two has either
been signed out by its own idle limit or its browser has gone; it is not shown as signed in. `tests/test_devices_on_a_login.py`
holds both numbers equal to the browser's (`apps/web/lib/auth/idleTimeout.ts`, `apps/web/lib/auth/deviceSeen.ts`), so changing the
idle limit cannot leave this window describing a different product.

Pure: no database, no clock of its own. The caller passes `now`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional

#: The idle limit the browser enforces (apps/web/lib/auth/idleTimeout.ts IDLE_LIMIT_MS), in minutes.
IDLE_LIMIT_MINUTES = 30
#: How often a tab that somebody is using tells the server it is still there (apps/web/lib/auth/deviceSeen.ts SEEN_EVERY_MS).
SEEN_EVERY_MINUTES = 10
#: A session the server last heard from longer ago than this is not live.
LIVE_WINDOW = timedelta(minutes=IDLE_LIMIT_MINUTES + SEEN_EVERY_MINUTES)

#: The user agent is the browser's own text and nothing we wrote: it is capped before it is stored.
USER_AGENT_MAX = 300

SECOND_DEVICE_NOTIFICATION_TYPE = "second_device"


def instant(value: Any) -> Optional[datetime]:
    """A stored timestamp as an aware datetime, or None when it cannot be read. A naive one is read as UTC."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value.strip():
        try:
            moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            # Not a timestamp. A timestamptz column always reads back as ISO text, so a stored instant never lands here: this is an absent value or a
            # hand-built one, and None says there is no instant.
            return None
    else:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def is_live(row: Mapping[str, Any], now: datetime) -> bool:
    """A session that has not been ended and that the server heard from inside the live window. An unreadable `last_seen_at` is
    NOT live: showing a device as signed in on a stamp nobody could read would be the unknown shown as a value."""
    if row.get("ended_at"):
        return False
    seen = instant(row.get("last_seen_at"))
    if seen is None:
        return False
    return now - LIVE_WINDOW <= seen <= now + timedelta(minutes=5)


def clean_user_agent(raw: Optional[str]) -> Optional[str]:
    """What is stored of the browser's text: trimmed, control characters dropped, capped. None for nothing."""
    if not raw:
        return None
    text = "".join(ch for ch in str(raw) if ch.isprintable()).strip()
    return text[:USER_AGENT_MAX] or None


_UNKNOWN_BROWSER = "an unrecognised browser"


def browser_label(user_agent: Optional[str]) -> str:
    """"Chrome on Windows", "Safari on iPhone"… in the words a person would use, or `an unrecognised browser`.

    Order matters: Edge and Opera say "Chrome" too, and Chrome says "Safari", so the more specific names are asked first.
    This names a browser and an operating system and nothing more: it does not guess a model or a person. It reads what the browser
    SAYS it is: an iPad asking for the desktop site says it is a Mac, and that is what is shown.
    """
    ua = (user_agent or "").strip()
    if not ua:
        return _UNKNOWN_BROWSER
    low = ua.lower()
    if "edg/" in low or "edge/" in low or "edgios/" in low or "edga/" in low:
        browser = "Edge"
    elif "opr/" in low or "opera" in low or "opt/" in low:
        browser = "Opera"
    elif "samsungbrowser/" in low:
        browser = "Samsung Internet"
    elif "firefox/" in low or "fxios/" in low:
        browser = "Firefox"
    elif "chrome/" in low or "crios/" in low:
        browser = "Chrome"
    elif "safari/" in low and "version/" in low:
        browser = "Safari"
    else:
        return _UNKNOWN_BROWSER

    if "iphone" in low:
        system = "iPhone"
    elif "ipad" in low:
        system = "iPad"
    elif "android" in low:
        system = "Android"
    elif "windows" in low:
        system = "Windows"
    elif "mac os x" in low or "macintosh" in low:
        system = "a Mac"
    elif "cros" in low:
        system = "ChromeOS"
    elif "linux" in low:
        system = "Linux"
    else:
        return browser
    return f"{browser} on {system}"


def devices_sentence(count: int) -> str:
    """"Signed in on 2 devices": what the screen says about a login. Zero says so too, because a person with no live session
    is not "unknown": it is what the server has heard."""
    if count <= 0:
        return "Not signed in on any device right now"
    if count == 1:
        return "Signed in on 1 device"
    return f"Signed in on {count} devices"


def present(row: Mapping[str, Any], *, current_session_id: Optional[str] = None) -> dict:
    """One live session as the screen is served it. The sign-in service's session id is never sent: `is_current` says which one
    is the caller's own (None where the question does not apply, a Partner reading somebody else's), and `id` is the row's own."""
    sid = row.get("session_id")
    return {
        "id": row.get("id"),
        "browser": browser_label(row.get("user_agent")),
        "address": row.get("ip") or None,
        "started_at": row.get("started_at"),
        "last_seen_at": row.get("last_seen_at"),
        "is_current": (None if current_session_id is None else bool(sid) and sid == current_session_id),
    }


def summarise(rows: Iterable[Mapping[str, Any]], now: datetime, *, current_session_id: Optional[str] = None) -> dict:
    """The live sessions of ONE login, newest sighting first, with the sentence and whether there is more than one."""
    live = [r for r in rows if is_live(r, now)]
    live.sort(key=lambda r: instant(r.get("last_seen_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return {
        "devices": [present(r, current_session_id=current_session_id) for r in live],
        "count": len(live),
        "sentence": devices_sentence(len(live)),
        "more_than_one": len(live) > 1,
        # What "live" means, so a screen can say it: the server last heard from the session within this many minutes.
        "window_minutes": int(LIVE_WINDOW.total_seconds() // 60),
    }


def second_device_notice(member_name: str, browser: str, address: Optional[str], others_live: int) -> tuple[str, str]:
    """The title and body of the notice to the Partners when a login that already has a live session signs in somewhere else.

    It says what was recorded and no more: it does not say the sign-in was wrong, because it may be the same person's phone."""
    who = (member_name or "").strip() or "A team member"
    title = f"{who} is signed in on another device"
    where = f" from address {address}" if address else ""
    body = (
        f"A new sign-in{where} on {browser} while this login was already signed in on "
        f"{others_live} other session{'s' if others_live != 1 else ''} (each browser counts once, so a second browser on one computer counts too). "
        "If this is not expected, open Team, then Login history, to see who is signed in where and, as a Partner, to sign them out."
    )
    return title, body
