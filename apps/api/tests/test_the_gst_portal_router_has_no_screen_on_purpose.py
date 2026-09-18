"""GST-13's last half: `/api/gst-portal` reaches no screen, and that is right.

WHAT THE FINDING ASKED FOR

    GST-13 named five GST capabilities with engines and no screens. Four were
    built (amendments, the ITC register, GSTR-9, the advances working) and the
    fifth — `routers/gst_portal.py`, mounted at `/api/gst-portal` — was left
    with no frontend caller, which the repo's own reachability ratchet keeps
    reporting.

WHY IT IS NOT A GAP

    Every method of the ONLY provider is a stub. `ManualGSTProvider` is what
    `get_provider()` returns, and it answers `{"status": "manual"}` or `[]` to
    all six questions, because reaching the real portal needs GSP empanelment —
    a commercial registration, not code (docs/compliance/02-gst.md).

    A screen over it would be a DEAD CONTROL: a Sync button that fetches
    nothing and a snapshot list that is empty by construction, on a tab headed
    "GST Portal". This codebase refuses those by name — the filing demo's
    capability probe exists for it, and `SALES-19` records the rule as "a
    screen must never invite a CA to type something the server will refuse".

    So the answer is a RECORDED REFUSAL rather than a screen, the same shape as
    SALES-23's cadence and BANK-11's step 3.

WHAT MAKES IT STRUCTURAL RATHER THAN A NOTE

    This test. It holds the refusal to its own PREMISE: the moment a real
    provider exists, the premise is false and this test fails, so whoever wires
    a GSP in has to come here and delete it deliberately. A comment would not
    do that.

NEGATIVE CONTROL: add a non-stub provider to `get_provider`'s registry and
`test_the_refusal_rests_on_its_premise` fails, which is the point.
"""
from __future__ import annotations

import pathlib
import re

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"

#: Why no screen exists. Quoted in `findings-status.json` under GST-13.
REFUSAL = (
    "/api/gst-portal is deliberately unreachable from any screen. Its only "
    "provider is ManualGSTProvider, whose every method returns a "
    "`status: \"manual\"` stub or an empty list pending GSP empanelment, so a "
    "screen over it would be a Sync button that fetches nothing and a snapshot "
    "list empty by construction. Build the screen in the same change as the "
    "real provider, not before it."
)


def test_no_screen_calls_the_gst_portal_router():
    hits = []
    for path in WEB.rglob("*.ts*"):
        if "node_modules" in str(path):
            continue
        if "gst-portal" in path.read_text(encoding="utf-8", errors="ignore"):
            hits.append(str(path.relative_to(WEB)))
    # This file's own name is not a hit; nothing under apps/web should mention
    # the prefix at all until a real provider exists.
    assert hits == [], f"{REFUSAL}\nFound: {hits}"


def test_the_refusal_rests_on_its_premise():
    """THE GUARD THAT MAKES THIS DELIBERATE RATHER THAN NEGLECT.

    The refusal is true only while every provider is a stub. A real one makes
    it false, and this fails — so the screen gets built in the same change as
    the provider, which is the only order that cannot ship a dead control.
    """
    from domain.gst import portal_service as ps

    provider = ps.get_provider()
    assert isinstance(provider, ps.ManualGSTProvider), (
        "a real GST portal provider exists now, so GST-13's refusal no longer "
        "holds: build the screen in this same change and delete this test.")

    # Every answer is a stub, checked rather than assumed — a provider that
    # started returning real rows while keeping its class name would otherwise
    # pass the isinstance check above.
    assert provider.fetch_return_history("27AAAAA0000A1Z5", "2025-26") == []
    for answer in (provider.fetch_profile("27AAAAA0000A1Z5"),
                   provider.fetch_filing_status("27AAAAA0000A1Z5", "2025-26"),
                   provider.fetch_liability_summary("27AAAAA0000A1Z5", "062025"),
                   provider.fetch_gstr1_status("27AAAAA0000A1Z5", "062025"),
                   provider.fetch_gstr3b_status("27AAAAA0000A1Z5", "062025")):
        assert answer.get("status") == "manual", answer


def test_the_router_is_still_mounted_and_scoped():
    """Unreachable from a screen is NOT unmounted. The endpoints exist, they
    are assignment-scoped, and a CA's own tooling or a later screen can use
    them — what is refused is shipping a control that does nothing."""
    import main
    paths = {r.path for r in main.app.routes if hasattr(r, "path")}
    assert any(p.startswith("/api/gst-portal") for p in paths)

    src = (pathlib.Path(__file__).resolve().parents[1]
           / "routers" / "gst_portal.py").read_text(encoding="utf-8")
    assert "assert_client_access" in src
    assert "_assert_job_scope" in src


def test_the_reachability_budget_still_counts_it():
    """It stays ON the unreachable list rather than being allowlisted away.

    An endpoint excused from the ratchet is an endpoint nobody notices when the
    reason for excusing it expires. It is counted, and the budget for its
    module absorbs it.
    """
    src = (pathlib.Path(__file__).resolve().parent
           / "test_every_mounted_endpoint_has_a_way_in.py").read_text(encoding="utf-8")
    assert not re.search(r'"/api/gst-portal[^"]*"\s*:\s*#?\s*allow', src), (
        "gst-portal must not be allowlisted out of the reachability ratchet")
