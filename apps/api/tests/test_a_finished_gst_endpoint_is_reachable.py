"""GST-13 — a finished GST endpoint has a way in, or says why not.

WHAT WAS WRONG
    Sixteen endpoints across three GST routers were built, mounted, tested and
    unreachable — including the whole §37 amendment path, whose own route
    docstring records that the amendment service and the payload merger had
    both existed for a long time and that "NOTHING CONNECTED THE TWO".

WHY THIS GUARD STATES THE RULE
    Same reason as its payroll twin: the defect is not "these sixteen", it is
    that nothing noticed. An endpoint can be written, reviewed, tested and
    merged with no part of the product calling it, and every test in this suite
    passes — because every test in this suite calls it directly.

    So: every endpoint on /api/gst, /api/gst-workspace and /api/gst-portal is
    called from apps/web, or is registered below with a reason. Two of the
    registrations are product decisions rather than backlog, and both would be
    ACTIVELY WRONG to build.
"""
from __future__ import annotations

import pathlib
import re

import pytest

import routers.gst as gst
import routers.gst_portal as portal
import routers.gst_workspace as gw


WEB = pathlib.Path(__file__).resolve().parents[3] / "apps" / "web"

# THE PORTAL SYNC CANNOT REACH THE PORTAL, so it must not have a screen.
_PORTAL = (
    "domain/gst/portal_service.get_provider has exactly ONE provider — manual "
    "— because reading returns from the GST portal needs an empanelled GSP, "
    "and there is no direct-to-GSTN route at any turnover. A sync therefore "
    "returns empty return lists and status 'manual'. A screen for it would "
    "show a CA 'the portal says this return is not filed' for every return "
    "they have ever filed, which is the exact failure that function's own "
    "docstring names. Wire the provider first; the screen is the second half "
    "of that commit, not this one.")

# THE RAW BUILDERS take invoice ROWS in the request body, and the product's
# path is books-driven.
_RAW = (
    "Takes invoice ROWS in the request body. The product's path is "
    "books-driven — gstr1/from-books and gstr1/with-amendments read the posted "
    "ledger — and a screen for this one would ask a CA to key invoices into a "
    "form to build a return. That is browser-side return assembly, which this "
    "codebase has deleted twice: generateTds24QData wrote 'PAN NOT AVAILABLE' "
    "into a 24Q, and the browser-side filing demo bypassed its own kill "
    "switch. Kept as a library entry point for callers that genuinely hold the "
    "rows; not offered as a screen.")

# Endpoints with deliberately no way in. An entry here is a claim somebody made
# on purpose — never a way to quiet the test.
UNREACHED: dict[tuple[str, str], str] = {
    ("GET", "/api/gst-portal/snapshots"): _PORTAL,
    ("POST", "/api/gst-portal/snapshots"): _PORTAL,
    ("GET", "/api/gst-portal/sync-jobs"): _PORTAL,
    ("POST", "/api/gst-portal/sync-jobs"): _PORTAL,
    ("POST", "/api/gst-portal/sync-jobs/{job_id}/run"): _PORTAL,
    ("POST", "/api/gst/gstr1/build"): _RAW,
    ("POST", "/api/gst/gstr3b/compute"): _RAW,
    ("POST", "/api/gst/validate/gstr1"): _RAW,
    ("POST", "/api/gst/validate/gstr3b"): _RAW,
}


def _sources() -> str:
    """Every .ts/.tsx in the product, minus its own tests — a test that merely
    NAMES an endpoint must not make it look reachable."""
    out = []
    for folder in ("app", "lib", "components"):
        for path in (WEB / folder).rglob("*"):
            if path.suffix in (".ts", ".tsx") and ".test." not in path.name:
                out.append(path.read_text(errors="ignore"))
    return "\n".join(out)


BLOB = _sources()


def _pattern(path: str) -> re.Pattern:
    chunks = re.split(r"\{[^}]+\}", path)
    return re.compile(r"[^\s\"'`]*?".join(re.escape(c) for c in chunks))


def _routes() -> list[tuple[str, str]]:
    out = set()
    for module in (gst, gw, portal):
        for route in module.router.routes:
            for method in getattr(route, "methods", ()) or ():
                if method not in ("HEAD", "OPTIONS"):
                    out.add((method, route.path))
    return sorted(out)


ROUTES = _routes()


def test_the_web_tree_was_actually_read():
    assert WEB.is_dir(), WEB
    assert len(BLOB) > 500_000, f"only {len(BLOB)} chars of frontend source found"
    assert "/api/gst-workspace/returns" in BLOB


def test_there_are_enough_routes_to_be_worth_sweeping():
    """A prefix typo or a failed import would enumerate nothing and pass."""
    assert len(ROUTES) >= 35, len(ROUTES)


@pytest.mark.parametrize("method,path", ROUTES, ids=lambda v: str(v))
def test_every_gst_endpoint_is_reachable_from_the_product(method, path):
    if (method, path) in UNREACHED:
        pytest.skip(UNREACHED[(method, path)])
    assert _pattern(path).search(BLOB), (
        f"{method} {path} is finished and mounted and NOTHING in apps/web calls "
        f"it. Give it a screen, or register it in UNREACHED with the reason — "
        f"an endpoint nobody can reach is work that was done and cannot be used."
    )


def test_every_registered_exception_is_still_a_real_endpoint():
    for key in UNREACHED:
        assert key in ROUTES, f"{key} is registered as unreached but is not a route"


def test_a_registered_exception_carries_a_real_reason():
    for key, reason in UNREACHED.items():
        assert len(reason) > 120, f"{key} needs a reason, not a note"


# ─────────── the ones GST-13 named, pinned individually ───────────

@pytest.mark.parametrize("method,path", [
    ("GET", "/api/gst-workspace/gstr1/amendments"),
    ("GET", "/api/gst-workspace/gstr1/exceptions"),
    ("GET", "/api/gst-workspace/gstr1/advances"),
    ("GET", "/api/gst-workspace/itc/register"),
    ("POST", "/api/gst-workspace/itc/register/reversal"),
    ("POST", "/api/gst-workspace/itc/register/reclaim"),
    ("POST", "/api/gst/gstr1/with-amendments"),
])
def test_the_named_orphans_now_have_a_screen(method, path):
    """Named as well as swept, because the sweep keeps passing if one of these
    is deleted — and a deleted amendment endpoint is not a fixed finding."""
    assert (method, path) in ROUTES, f"{method} {path} no longer exists"
    assert _pattern(path).search(BLOB), f"{method} {path} is orphaned again"


@pytest.mark.parametrize("path", [
    "/api/gst-workspace/gstr9",
    "/api/gst-workspace/itc/rule37",
])
def test_two_that_the_finding_wrongly_called_orphaned(path):
    """GST-13 lists POST /gstr9 and itc/rule37 as having no screen. Both were
    already wired when the finding was written. Recorded so the correction is
    not lost the next time the finding is read."""
    assert _pattern(path).search(BLOB)


# ─────────── what must NOT be registered as a reclaimable reversal ───────────

def test_only_reclaimable_reasons_are_offered():
    """Rules 38, 42, 43 and §17(5) are PERMANENT reversals — Table 4(B)(1) —
    derived from the documents themselves. Registering one in this register
    would declare it twice: once from the document and once from the row."""
    from services.itc_register_service import RECLAIMABLE_REASONS
    assert set(RECLAIMABLE_REASONS) == {
        "rule_37", "rule_37a", "section_16_2b", "section_16_2c", "other"}
    for permanent in ("rule_38", "rule_42", "rule_43", "section_17_5"):
        assert permanent not in RECLAIMABLE_REASONS

    # …and the screen offers exactly those and no others. A reason the picker
    # offers that the server rejects is a form that fails on submit; one the
    # server takes and the picker hides is a figure a CA cannot record.
    tab = (WEB / "components" / "gst" / "ItcRegisterTab.tsx").read_text()
    offered = set(re.findall(r'code: "([a-z0-9_]+)"', tab))
    assert offered == set(RECLAIMABLE_REASONS), offered


def test_table_11_computed_is_the_clients_own_flag_not_a_constant():
    """It WAS a constant, and the constant went stale under it.

    `advances_report` returned `"table_11_computed": False` unconditionally,
    and the ITC Register tab renders an amber banner on exactly that field. By
    the time `table_11_sections` was declaring real 11A rows into the GSTR-1
    payload, the screen was telling every CA the platform does not compute
    Table 11 while their filed return carried it.

    Asserted as the RULE — the value is read from `advance_tax_applicable`, the
    one reader of `clients.gst_advance_tax_applicable` — rather than as either
    literal, because either literal is a constant and a constant is what was
    wrong. The behaviour itself is exercised in
    tests/test_gstr1_advances_are_surfaced.py, both ways round.
    """
    import inspect
    from services import gst_advance_service
    body = inspect.getsource(gst_advance_service.advances_report)
    assert '"table_11_computed": computed' in body, body
    assert "computed = advance_tax_applicable(db, firm_id, client_id)" in body
    assert '"table_11_computed": False' not in body
    assert '"table_11_computed": True' not in body

    # The one reader is firm-scoped. The service-role key bypasses RLS, so a
    # read keyed on a bare uuid is not an isolation control (CLAUDE.md).
    reader = inspect.getsource(gst_advance_service.advance_tax_applicable)
    assert '.eq("firm_id", firm_id)' in reader, reader

    # The mock branch keeps a literal, and that is correct there — mock mode
    # has no clients table to read. It must stay the OFF one: a mock that
    # claimed Table 11 was computed would be inventing a client setting.
    src = inspect.getsource(gw.gstr1_advances)
    assert '"table_11_computed": False' in src
    assert '"table_11_computed": True' not in src


def test_the_screen_states_which_kind_of_empty_table_11_it_is_showing():
    """The banner is the whole reason the field exists, and it was one-sided.

    `{!advances.table_11_computed && (` rendered an amber "Table 11 is not
    computed here" and rendered NOTHING otherwise — so the only two states a CA
    ever saw were a false warning and silence. It must speak in both
    directions, off the server's field, and only the OFF one may be amber: an
    amber banner on a working feature is a warning about nothing.
    """
    tab = (WEB / "components" / "gst" / "ItcRegisterTab.tsx").read_text()
    code = re.sub(r"/\*.*?\*/", "", tab, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)

    # Scoped to the Table 11 panel: the tab is long and carries amber elsewhere
    # for reasons of its own, so a whole-file scan would assert nothing here and
    # break on an unrelated edit there.
    start = code.index("Advances against no invoice")
    end = code.index("No unadjusted advances in", start)
    panel = code[start:end]

    assert "{!advances.table_11_computed && (" not in panel, (
        "the banner is one-sided again — a CA whose Table 11 IS computed sees "
        "nothing at all about it")
    assert "advances.table_11_computed" in panel, (
        "the screen must render the server's answer, not decide for itself")
    assert "{advances.why}" in panel, (
        "the sentence explaining which kind of empty this is comes from the "
        "server; a copy in the screen is a second thing to keep in step")
    assert "Table 11 is computed for this client" in panel
    assert "Table 11 is not computed for this client" in panel
    # Amber is the WARNING colour and belongs to the off branch only. Every
    # amber token in this panel has to be on the false arm of a ternary the
    # field itself chooses — an amber banner on a working feature is a warning
    # about nothing, which is what this whole test is here to have removed.
    for line in panel.splitlines():
        if "amber" in line:
            assert "table_11_computed ?" in line or ': "text-amber' in line \
                or ': "rounded-lg border border-amber' in line, line
