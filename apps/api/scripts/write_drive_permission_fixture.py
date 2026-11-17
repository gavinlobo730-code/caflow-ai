"""Write the Partner permission map the browser drive's stub serves.

The money-editor drive (`apps/web/scripts/driveMoneyEditors.mjs`) answers
`GET /api/identity/permissions` from `apps/web/scripts/drive/partner-permissions.json`
whenever a scenario has not routed that endpoint itself. That file is this
module's output and nothing else: `core/permissions.get_accessible_resources`
for a Partner with no overrides, each action list sorted so the file is stable
(the matrix holds sets). `tests/test_the_drive_serves_the_partner_map_core_permissions_gives.py`
fails when the two differ; rerun this from `apps/api` to bring the file back:

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


def main() -> None:
    FIXTURE.write_text(json.dumps(partner_map(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE.relative_to(API.parents[1])}")


if __name__ == "__main__":
    main()
