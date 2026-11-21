"""Write the permission maps the browser drive's stub serves: the Partner map, and one map per staff role.

The money-editor drive (`apps/web/scripts/driveMoneyEditors.mjs`) answers
`GET /api/identity/permissions` from `apps/web/scripts/drive/partner-permissions.json`
whenever a scenario has not routed that endpoint itself. That file is this
module's output and nothing else: `core/permissions.get_accessible_resources`
for a Partner with no overrides, each action list sorted so the file is stable
(the matrix holds sets). `tests/test_the_drive_serves_the_partner_map_core_permissions_gives.py`
fails when the two differ; rerun this from `apps/api` to bring the file back.

`role-permissions.json`, beside it, holds the same map for each staff role (Partner, Manager, Executive, Reviewer), for a
scenario that signs in as somebody else (`stub.signInAs(role)`). Before it existed a "Manager" scenario changed the role
on the person's row and still served the Partner's map, so a screen that asks the map (a button, an access gate) was
driven as nobody the product has. The same test holds it:

    python3 scripts/write_drive_permission_fixture.py
"""
from __future__ import annotations

import json
import pathlib
import sys

API = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))

from core.permissions import get_accessible_resources  # noqa: E402

FIXTURE = API.parent / "web" / "scripts" / "drive" / "partner-permissions.json"


def partner_map() -> dict[str, list[str]]:
    resources = get_accessible_resources("Partner")
    return {resource: sorted(actions) for resource, actions in sorted(resources.items())}


ROLE_FIXTURE = FIXTURE.with_name("role-permissions.json")
STAFF_ROLES = ("Partner", "Manager", "Executive", "Reviewer")


def role_maps() -> dict[str, dict[str, list[str]]]:
    """Each staff role's map with no overrides, in the shape `GET /api/identity/permissions` serves."""
    return {
        role: {resource: sorted(actions) for resource, actions in sorted(get_accessible_resources(role).items())}
        for role in STAFF_ROLES
    }


def main() -> None:
    FIXTURE.write_text(json.dumps(partner_map(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE.relative_to(API.parents[1])}")
    ROLE_FIXTURE.write_text(json.dumps(role_maps(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {ROLE_FIXTURE.relative_to(API.parents[1])}")


if __name__ == "__main__":
    main()
