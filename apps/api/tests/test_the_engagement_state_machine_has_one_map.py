"""The engagement state machine has one map, and the browser mirrors it.

G2. `routers/engagements.ENGAGEMENT_TRANSITIONS` is the authority — the
transition endpoint validates against it and answers 422 naming the permitted
set. `apps/web/lib/api/index.ts` carries a copy so the billing screen can offer
the buttons that will WORK rather than a dropdown of seven, six of which the
server refuses.

Pinned from the PYTHON side deliberately: the Schedule III caption lesson. A
guard written in `apps/web` would assert the browser against a copy of itself
and pass whenever both drifted together.

The second test is the one that would have caught the original defect: the
billing screen's own TypeScript declared `status: "Active" | "Paused"`, and
"Paused" is not a value `fee_engagements` can hold — migration 108's CHECK
allows seven and that is not one of them.
"""
import json
import re
from pathlib import Path

from routers.engagements import ENGAGEMENT_TRANSITIONS

WEB = Path(__file__).resolve().parents[2] / "web"
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _browser_map() -> dict[str, list[str]]:
    src = (WEB / "lib" / "api" / "index.ts").read_text(encoding="utf-8")
    m = re.search(
        r"export const ENGAGEMENT_TRANSITIONS:[^=]*=\s*\{(.*?)\n\};",
        src, re.S)
    assert m, "the browser mirror of ENGAGEMENT_TRANSITIONS is gone"
    body = m.group(1)
    out: dict[str, list[str]] = {}
    for line in body.splitlines():
        row = re.match(r'\s*"([^"]+)":\s*\[(.*?)\],\s*$', line)
        if not row:
            continue
        out[row.group(1)] = re.findall(r'"([^"]+)"', row.group(2))
    return out


def test_the_browser_mirrors_the_state_machine_exactly():
    assert _browser_map() == ENGAGEMENT_TRANSITIONS


def test_the_parser_is_not_vacuous():
    mirror = _browser_map()
    assert len(mirror) >= 7, f"parsed only {len(mirror)} statuses"
    assert mirror.get("Closed") == [], "a terminal status parsed wrongly"
    assert "In Progress" in mirror.get("Active", []), "a transition parsed wrongly"


def _check_statuses() -> set[str]:
    """The statuses migration 108's CHECK allows."""
    sql = (MIGRATIONS / "108_compliance_engagement.sql").read_text(encoding="utf-8")
    m = re.search(r"fee_engagements_status_check\s*\n?\s*CHECK \(status IN \((.*?)\)\)",
                  sql, re.S)
    assert m, "migration 108's status CHECK could not be read"
    return set(re.findall(r"'([^']+)'", m.group(1)))


def test_every_status_the_machine_names_is_one_the_column_allows():
    allowed = _check_statuses()
    assert len(allowed) >= 7, f"parsed only {allowed} from the CHECK"
    named = set(ENGAGEMENT_TRANSITIONS) | {
        s for v in ENGAGEMENT_TRANSITIONS.values() for s in v}
    assert named <= allowed, (
        "the state machine names a status the column refuses: "
        f"{sorted(named - allowed)}")


def test_the_billing_screen_declares_no_status_the_column_refuses():
    allowed = _check_statuses()
    src = (WEB / "app" / "billing" / "page.tsx").read_text(encoding="utf-8")
    badge = re.search(r"ENGAGEMENT_STATUS_BADGE:[^=]*=\s*\{(.*?)\n\};", src, re.S)
    assert badge, "the billing screen's status badge map is gone"
    keys = set(re.findall(r'"([^"]+)":', badge.group(1)))
    assert keys == allowed, (
        f"the badge map and the CHECK disagree: only-in-screen "
        f"{sorted(keys - allowed)}, only-in-column {sorted(allowed - keys)}")


def test_the_billing_screen_no_longer_writes_fee_engagements_over_postgrest():
    """`rbac()` and the state machine only run on the API path."""
    src = (WEB / "app" / "billing" / "page.tsx").read_text(encoding="utf-8")
    assert 'from("fee_engagements")' not in src, (
        "the billing screen is writing or reading fee_engagements straight over "
        "PostgREST again. `billing:read` is Partner-only and the SELECT policy "
        "is firm-scoped with no role test, so that path shows every role every "
        "fee; and an INSERT there runs neither rbac() nor the state machine.")
    assert "api.engagements." in src, "the screen no longer calls the API at all"
