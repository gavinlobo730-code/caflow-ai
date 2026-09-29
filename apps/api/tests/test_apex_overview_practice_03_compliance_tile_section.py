"""
apex-overview-practice-03: the Compliance hub tile's client_section pointed at
"tasks", so clicking it from a client's hub landed on the Tasks tab instead of
that client's actual Compliance Calendar (a real, existing section at
/clients/{id}/compliance/).

`test_a_hub_tile_shows_what_is_outstanding.py::test_every_client_section_is_a_
real_section` only checks that SOME page.tsx exists at the named section — it
would have passed with "tasks" just as happily as with "compliance", since
both are real pages. This file pins the actual VALUE, which is what the bug
was.
"""
from pathlib import Path

from domain.hub.tiles import BY_ID

WEB_APP = Path(__file__).resolve().parents[2] / "web" / "app"


def test_the_compliance_tile_points_at_the_compliance_section():
    tile = BY_ID["compliance"]
    assert tile.client_section == "compliance", (
        f"the Compliance Calendar tile points at "
        f"{tile.client_section!r}, not the client's own compliance section")
    assert tile.href_for("CLIENT-1") == "/clients/CLIENT-1/compliance/"


def test_the_compliance_tile_no_longer_points_at_tasks():
    """Negative control naming the exact old (wrong) value, so a regression
    back to it is caught even if a future refactor removes the positive
    assertion above."""
    tile = BY_ID["compliance"]
    assert tile.client_section != "tasks"


def test_the_compliance_client_section_page_exists():
    if not WEB_APP.exists():
        import pytest
        pytest.skip("apps/web is not present in this checkout")
    tile = BY_ID["compliance"]
    page = WEB_APP / "clients" / "[id]" / tile.client_section / "page.tsx"
    assert page.exists(), (
        f"the compliance tile points at {tile.client_section!r}, which has "
        f"no page under apps/web/app/clients/[id]/")
