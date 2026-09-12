"""FA-07 and FA-20: the engine was finished and nothing reached it.

FA-07  `phase2_journal_service.journal_for_asset_acquisition` has written three
       DIFFERENT credit legs since migration 343 — `paid` credits the account
       the money actually left, `credit` credits Trade Payables, `from_bill`
       RECLASSIFIES cost out of purchases touching neither payable nor cash —
       and `FixedAssetIn` refuses each mode that names no counterparty. No
       screen collected any of it. `grep acquisition_mode apps/web` returned
       one comment. So every asset created from the product defaulted to
       `paid` with no bank account: a machine bought on credit went in as if
       cash had left the building, and one already on a purchase bill went in
       twice.

FA-20  `GET /register-integrity` has run five checks since FA-02 and FA-13, and
       only when a CA opened the Reports tab and pressed Re-check. The nightly
       sweep and "Verify Books" — the two things that tell a CA their books are
       wrong without being asked — said nothing whatever about fixed assets.

Both are the same shape as the rest of this backlog: the hard two-thirds built,
correct, and unreachable.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pydantic
import pytest

from domain.fixed_assets import integrity, schedule_ii

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
FA_PAGE = WEB / "app" / "clients" / "[id]" / "fixed-assets" / "page.tsx"


def _strip_comments(src: str) -> str:
    """`//` lines out, so a rule is never satisfied by prose describing it."""
    return "\n".join(l for l in src.splitlines() if not l.strip().startswith("//"))


def _asset(**kw) -> dict:
    base = {
        "id": "a1", "asset_code": "FA-0001", "asset_name": "Lathe",
        "asset_category": "Plant & Machinery", "depreciation_method": "WDV",
        "wdv_rate_percent": 18.10, "useful_life_years": 15,
        "purchase_cost_paise": 100_000_00, "accumulated_depreciation_paise": 0,
        "salvage_value_paise": 0, "journal_entry_id": "j1",
        "is_disposed": False, "purchase_bill_id": None,
    }
    base.update(kw)
    return base


# ═══════════════════════════════════════════════════════════════════════════
# FA-20 — one rule, and the sweep runs it
# ═══════════════════════════════════════════════════════════════════════════

def test_the_five_checks_are_one_function_now():
    kinds = {f["kind"] for f in integrity.register_findings(
        [_asset(journal_entry_id=None),
         _asset(id="a2", wdv_rate_percent=10.00),
         _asset(id="a3", useful_life_years=None, wdv_rate_percent=63.16,
                asset_category="Computer & IT Equipment"),
         _asset(id="a4", purchase_bill_id="b1"),
         _asset(id="a5", purchase_bill_id="b1")],
        live_bill_ids=set())}
    assert kinds == {
        "no_acquisition_journal",
        "depreciation_basis_departs_from_schedule_ii",
        "wdv_asset_has_no_stopping_point",
        "bill_capitalised_more_than_once",
        "capitalised_from_a_bill_that_is_gone",
    }, kinds


def test_a_clean_register_reports_nothing():
    assert integrity.register_findings([_asset()], live_bill_ids=set()) == []


def test_a_bill_that_still_exists_is_not_an_orphan():
    assert integrity.register_findings(
        [_asset(purchase_bill_id="b1")], live_bill_ids={"b1"}) == []


def test_the_nightly_sweep_runs_it():
    """The whole of FA-20. A check behind a button the CA has to know to press
    is not what `reconciliation_service` is for."""
    from services import reconciliation_service as r
    names = [c.__name__ for c in r._CHECKS]
    assert "check_fixed_asset_register" in names, (
        "the sweep and 'Verify Books' say nothing about fixed assets")


def test_the_sweep_and_the_endpoint_call_the_same_rule():
    from routers import fixed_assets as fa
    from services import reconciliation_service as r
    for fn in (fa.register_integrity, r.check_fixed_asset_register):
        src = inspect.getsource(fn)
        assert "register_findings(" in src, fn.__name__
        # …and neither reimplements it.
        for own in ('"kind": "no_acquisition_journal"', "by_bill", "schedule_ii_departure("):
            assert own not in src, (
                f"{fn.__name__} builds findings itself again ({own!r}) — the copy "
                f"nobody is looking at is the one that stops being updated")


def test_the_service_does_not_import_the_router():
    """A service reaching into a router for a statutory rule is the wrong
    direction and one refactor from an import cycle. The projection moved to
    the domain with the rule for exactly this."""
    from services import reconciliation_service as r
    src = inspect.getsource(r.check_fixed_asset_register)
    assert "from routers" not in src and "routers." not in src
    assert "fa_integrity.COLUMNS" in src


def test_both_callers_select_the_same_columns():
    """A column added to one query and not the other makes one of them quietly
    answer "clean" on a finding it could not see."""
    from routers import fixed_assets as fa
    from services import reconciliation_service as r
    assert fa._INTEGRITY_COLUMNS is integrity.COLUMNS
    assert "fa_integrity.COLUMNS" in inspect.getsource(r.check_fixed_asset_register)


@pytest.mark.parametrize("column", [
    "id",                                  # the paging cursor
    "journal_entry_id", "purchase_bill_id", "is_disposed",
    "asset_category", "depreciation_method", "wdv_rate_percent",
    "useful_life_years", "salvage_value_paise",
    "accumulated_depreciation_paise", "purchase_cost_paise",
])
def test_the_projection_carries_what_the_checks_read(column):
    assert column in integrity.COLUMNS, (
        f"{column} is read by a check and not selected — the check cannot judge "
        f"what was never fetched, and returns None for every asset")


def test_the_projection_starts_with_the_paging_cursor():
    """Both callers page on `id`, and `fetch_all`/`_paginate_all` read it off
    the last row of each page. A select list without it works perfectly until
    the thousandth asset."""
    assert integrity.COLUMNS.split(",")[0].strip() == "id"


def test_the_severities_say_which_findings_mean_money_is_missing():
    """The two Schedule II ones are WARNINGS: Part A expressly permits a
    different life or residual provided it is disclosed, so they are a prompt
    to correct or disclose rather than an assertion the books are wrong."""
    from services import reconciliation_service as r
    src = inspect.getsource(r.check_fixed_asset_register)
    block = src[src.index("severity = {"):src.index("out: list[dict] = []")]
    assert '"no_acquisition_journal": "critical"' in block
    assert '"depreciation_basis_departs_from_schedule_ii": "warning"' in block
    assert '"wdv_asset_has_no_stopping_point": "warning"' in block


def test_the_schedule_ii_table_is_in_the_domain_and_re_exported():
    """It was a router-level literal, which was fine while one endpoint served
    it. Three read it now, one of them a service."""
    from routers import fixed_assets as fa
    assert fa.SCHEDULE_II_CATEGORIES is schedule_ii.CATEGORIES
    assert fa._NOT_DEPRECIABLE is schedule_ii.NOT_DEPRECIABLE
    assert fa.schedule_ii_departure is integrity.schedule_ii_departure
    router_src = (Path(__file__).resolve().parents[1] / "routers" / "fixed_assets.py").read_text()
    assert "_SCHEDULE_II_PART_C: dict" not in router_src, (
        "the table is defined in the router again — the service would then have "
        "to import a router to read Schedule II")


# ═══════════════════════════════════════════════════════════════════════════
# FA-07 — the form collects what the journal needs
# ═══════════════════════════════════════════════════════════════════════════

_SCREEN = FA_PAGE.read_text()
_DRAWER = _strip_comments(
    _SCREEN[_SCREEN.index("function AddAssetDrawer("):_SCREEN.index("// ── Depreciation Tab")])

#: The drawer split into the two halves that mean different things. Scanning
#: the WHOLE drawer for a field name is the weakness four negative controls
#: found: `acquisition_mode:`, `igst_paise:` and `isCashMode(...)` each appear
#: in the form STATE as well, so deleting the line that SENDS one still matched
#: — the same "assert the spelling, not the rule" mistake CLAUDE.md records
#: about the money parser, inside guards written to prevent it.
_POST = 'request<ApiEnvelope>("/api/fixed-assets/"'
_PAYLOAD = _DRAWER[_DRAWER.index("const body = {"):_DRAWER.index(_POST)]
_RENDER = _DRAWER[_DRAWER.index("  return (\n    <div className=\"fixed inset-0"):]


@pytest.mark.parametrize("field", [
    "acquisition_mode", "vendor_id", "purchase_bill_id", "bank_account_id",
    "payment_mode", "igst_paise", "cgst_paise", "sgst_paise", "itc_eligible",
])
def test_the_drawer_sends_every_acquisition_fact(field):
    """`grep acquisition_mode apps/web` used to return one comment.

    Asserted on the PAYLOAD, not on the drawer: every one of these is also a
    key in the form's own state, so a field collected into state and then left
    out of the request reads identically to one that is sent.
    """
    assert f"{field}:" in _PAYLOAD, f"the Add Asset drawer never SENDS {field}"


def test_the_three_modes_are_offered_by_name():
    for mode in ('"paid"', '"credit"', '"from_bill"'):
        assert mode in _DRAWER, f"the drawer cannot select {mode}"


def test_a_vendor_is_asked_for_where_the_mode_names_one():
    assert 'form.acquisition_mode !== "paid"' in _DRAWER, (
        "credit and from_bill both name a counterparty; the model refuses "
        "either without one")


def test_the_bill_picker_is_scoped_to_the_chosen_vendor():
    """Capitalising somebody else's bill reclassifies cost out of a purchase
    the client never made, and a flat list of every bill is how that happens."""
    assert '.eq("vendor_id", form.vendor_id)' in _DRAWER


def test_a_cash_purchase_is_not_offered_a_bank_account():
    """It did not come out of a bank, and offering an account is what makes a
    CA pick one and mis-post it. `resolve_payment_account` sends a cash mode to
    Cash in Hand regardless, so a bank_account_id here would be a fact the
    entry contradicts.

    BOTH halves: the picker is not RENDERED for cash, and a stale
    `bank_account_id` left in state from before the mode changed is not SENT.
    """
    assert "!isCashMode(form.payment_mode) && (" in _RENDER, "still offered for cash"
    assert "!isCashMode(form.payment_mode)" in _PAYLOAD, "still sent for cash"


def test_the_itc_question_is_asked_only_where_there_is_tax():
    """Sending an answer with no tax asserts a §17(5) judgement about nothing;
    sending tax with no answer is refused by the model, because whether the
    credit is blocked changes both the balance sheet and the depreciable cost.

    Again both halves — the question is not RENDERED with no tax on the form,
    and an answer left in state from a tax figure since cleared is not SENT.
    """
    assert "taxTotal > 0 && form.itc_eligible" in _PAYLOAD
    assert "Number(form.igst_paise || 0)" in _RENDER, (
        "the ITC question must be gated on there being tax; asking it "
        "unconditionally makes every asset carry a §17(5) judgement")


def test_the_tax_fields_go_through_the_one_money_parser():
    """CLAUDE.md: nothing whose name ends in `_paise` may be built with a
    numeric coercion or a multiplication by 100."""
    for field in ("form.igst_paise", "form.cgst_paise", "form.sgst_paise"):
        assert f"paiseFromRupeeInput({field}" in _DRAWER, field


def test_the_payment_modes_are_not_a_third_copy():
    """There were two identical lists — the receipt form's and the importer's,
    the second of which REFUSES a row whose mode is not in it. A third would
    have agreed with both by coincidence."""
    modes = WEB / "lib" / "payments" / "modes.ts"
    assert modes.exists()
    literal = re.compile(r'\["bank",\s*"cash",\s*"cheque",\s*"upi",\s*"neft",\s*"rtgs"\]')
    offenders = [
        f.relative_to(WEB) for f in list(WEB.rglob("*.ts")) + list(WEB.rglob("*.tsx"))
        if "node_modules" not in f.parts and ".next" not in f.parts
        and f != modes and literal.search(f.read_text())
    ]
    assert not offenders, f"a second payment-mode list: {offenders}"


# ── and the backend the form is now feeding ─────────────────────────────────

_CREATE = dict(client_id="c1", asset_name="Lathe", purchase_date="2026-04-01",
               purchase_cost_paise=100_000_00)


def test_the_model_still_refuses_a_mode_that_names_no_counterparty():
    """The form's own required-field marks are an affordance; THIS is the
    rule, and it is the sentence the CA sees when they get it wrong."""
    from models.accounting import FixedAssetIn
    for kw in ({"acquisition_mode": "credit"},
               {"acquisition_mode": "from_bill"},
               {"acquisition_mode": "from_bill", "vendor_id": "v1"}):
        with pytest.raises(pydantic.ValidationError):
            FixedAssetIn(**_CREATE, **kw)
    FixedAssetIn(**_CREATE, acquisition_mode="credit", vendor_id="v1")
    FixedAssetIn(**_CREATE, acquisition_mode="from_bill", purchase_bill_id="b1")


def test_tax_with_no_itc_answer_is_still_refused():
    from models.accounting import FixedAssetIn
    with pytest.raises(pydantic.ValidationError):
        FixedAssetIn(**_CREATE, igst_paise=18_000_00)
    FixedAssetIn(**_CREATE, igst_paise=18_000_00, itc_eligible=False)


def test_blocked_tax_is_capitalised_and_claimable_tax_is_not():
    """CGST Act §17(5): the tax is still paid, so it is added to the cost and
    DEPRECIATES. That is the whole reason the question cannot be defaulted."""
    from routers.fixed_assets import capitalised_cost_paise
    assert capitalised_cost_paise(100_000_00, 18_000_00, 0, 0, itc_eligible=False) == 118_000_00
    assert capitalised_cost_paise(100_000_00, 18_000_00, 0, 0, itc_eligible=True) == 100_000_00
    assert capitalised_cost_paise(100_000_00, 18_000_00, 0, 0, itc_eligible=None) == 100_000_00
