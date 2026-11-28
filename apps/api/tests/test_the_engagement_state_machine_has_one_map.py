"""A fee engagement has no state machine of its own to keep in step, and the billing screen's statuses are the column's.

G2 (history). The engagement lifecycle (Draft, Active, In Progress, Review, Completed, Closed) was a map on the server that the
transition route validated against, with a copy in the browser so the billing screen could offer the buttons that would work.
The screen is a record since 21-11-2026 and the buttons, the browser's copy and then the route and its map were deleted
(ledger POST-A-572), so the first test holds that neither side carries the map again.

The other two are the ones that would have caught the original defect: the billing screen's own TypeScript declared
`status: "Active" | "Paused"`, and "Paused" is not a value `fee_engagements` can hold: migration 108's CHECK allows seven and
that is not one of them.
"""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def test_no_second_state_machine_for_a_fee_engagement_exists():
    """A map nothing asks is a map to keep in step. The server's route is gone, and so is the browser's copy."""
    API = Path(__file__).resolve().parents[1]
    for path in [*(WEB / "lib" / "api").glob("*.ts"), WEB / "app" / "billing" / "page.tsx", API / "routers" / "engagements.py"]:
        assert "ENGAGEMENT_TRANSITIONS" not in path.read_text(encoding="utf-8"), (
            f"{path.name} carries a state machine for fee engagements again")
    assert '"/{engagement_id}/transition"' not in (API / "routers" / "engagements.py").read_text(encoding="utf-8")


def _check_statuses() -> set[str]:
    """The statuses migration 108's CHECK allows."""
    sql = (MIGRATIONS / "108_compliance_engagement.sql").read_text(encoding="utf-8")
    m = re.search(r"fee_engagements_status_check\s*\n?\s*CHECK \(status IN \((.*?)\)\)",
                  sql, re.S)
    assert m, "migration 108's status CHECK could not be read"
    return set(re.findall(r"'([^']+)'", m.group(1)))


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
