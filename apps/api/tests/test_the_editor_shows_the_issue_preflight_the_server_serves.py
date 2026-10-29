"""The invoice editor shows the server's issue pre-flight, and every action the server can name is one the browser can do (POST-A-125).

The server's vocabulary (`domain/sales/issue_readiness`: the action kinds and the editor fields) is the contract; the browser maps each
to something it does. A guard written in `apps/web` would assert the browser against a copy of itself, so this reads the vocabulary
from the side that owns it and the browser from the side that uses it. Adding an action kind or an editor field to the domain without
teaching the panel and the editor is a red test here, and so is the editor losing the hold on Save & Issue.

It reads `apps/web/components/invoices/` and `apps/web/lib/`, so the `browser contract` CI job selects it for a pull request that
touches only the web app (`scripts/ci/tests_reading_the_browser.py`).
"""
from __future__ import annotations

import pathlib
import re

from domain.sales import issue_readiness as ir

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"
PANEL = WEB / "components" / "invoices" / "IssueReadinessPanel.tsx"
EDITOR = WEB / "components" / "invoices" / "InvoiceEditor.tsx"
READER = WEB / "lib" / "invoices" / "issueReadiness.ts"
CLIENT = WEB / "lib" / "api" / "index.ts"


def _strip(path: pathlib.Path) -> str:
    text = path.read_text()
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//[^\n]*$", "", text)


def test_the_browser_reads_every_action_kind_and_editor_field_the_server_can_name():
    reader = _strip(READER)
    for kind in ir.ACTION_KINDS:
        assert f'"{kind}"' in reader, f"lib/invoices/issueReadiness does not read the action kind {kind}"
    for field in ir.EDITOR_FIELDS:
        assert f'"{field}"' in reader, f"lib/invoices/issueReadiness does not read the editor field {field}"


def test_the_panel_does_something_for_every_action_kind():
    panel = _strip(PANEL)
    for kind in ir.ACTION_KINDS:
        assert f'b.action?.kind === "{kind}"' in panel, f"the panel offers nothing for the action kind {kind}"
    assert "api.account.seedCoa()" in panel, "the chart of accounts action must call the existing idempotent seeder"
    assert "flight={flight}" in panel, "the one button that writes must ignore a second click"


def test_the_editor_can_take_the_clerk_to_every_field_an_action_names():
    editor = _strip(EDITOR)
    focus = editor[editor.index("function focusField"):]
    focus = focus[:focus.index("\n  }\n") + 5]
    ids = {"invoice_no": "inv-invoice-no", "supply_state": "inv-supply-state"}
    assert set(ids) == set(ir.EDITOR_FIELDS), "a field the server can name has no target in this test, and so none in the editor"
    assert 'field === "invoice_no"' in focus and 'field: "invoice_no" | "supply_state"' in editor
    for field, element in ids.items():
        assert f'id="{element}"' in editor, f"the editor has no element with id {element} for the field {field}"
        assert element in focus, f"focusField does not look for {element}"


def test_save_and_issue_and_save_and_send_are_held_by_the_servers_answer_and_by_nothing_the_browser_decides():
    editor = _strip(EDITOR)
    assert "holdsTheIssue(readiness, dirty)" in editor
    assert editor.count("disabled={busy || issueHeld}") == 2, "both buttons that issue must be held, and Save Draft must not be"
    # The draft button is the way to save a fix, so it must stay enabled.
    draft = editor[editor.index('onClick={() => save("draft")}'):]
    assert "issueHeld" not in draft[:draft.index("</Button>")]


def test_a_draft_that_was_created_and_refused_is_saved_again_and_not_created_twice():
    """Without the created id the editor stayed in 'new' mode after a refusal at the issue, and the next click created a second
    invoice with the same number."""
    editor = _strip(EDITOR)
    assert "const patchId = existing?.id ?? createdDraftId;" in editor
    assert "setCreatedDraftId(invoiceId)" in editor
    assert "if (patchId) {" in editor
    assert "api/sales-invoices/${existing.id}" not in editor, "a save of a draft must go to the id it was created under"


def test_what_belongs_to_the_new_invoice_follows_the_draft_that_exists_and_not_only_an_invoice_opened_for_editing():
    """A new invoice that was created and refused at the issue is a draft on the server. The update takes no currency or rate, so a
    rate corrected on the screen after the refusal was ignored by the save and the issue posted at the old one; and the series
    suggestion, which counts that draft, replaced its number and left a hole in the series. Both follow `lib/invoices/editorMode`."""
    editor = _strip(EDITOR)
    assert "const mode = editorMode(isEdit, createdDraftId);" in editor
    assert "{!mode.currencyIsFrozen && mcActive && (" in editor and "{mode.currencyIsFrozen && isForeign && (" in editor
    assert "mode.mayFillTheNumber && !numberTouched.current" in editor and "mode.mayFillTheNumber]" in editor
    assert "!isLocked && mode.mayFillTheNumber && !numberSeries" in editor
    assert "{!isEdit && mcActive" not in editor and "!isEdit && !numberTouched" not in editor


def test_a_blocked_or_ready_answer_can_be_asked_again_because_it_can_go_stale_while_it_holds_the_buttons():
    panel = _strip(PANEL)
    assert 'state.status === "blocked" || state.status === "ready"' in panel and "Check again" in panel


def test_the_panel_is_shown_for_a_draft_only_and_the_client_names_the_route():
    editor = _strip(EDITOR)
    assert re.search(r"\{!isLocked && \(\s*<IssueReadinessPanel", editor), "an issued invoice has nothing to pre-flight"
    client = _strip(CLIENT)
    assert "issuePreflight: (id: string)" in client and "/api/sales-invoices/${id}/issue-preflight" in client


def test_the_browser_decides_no_rule_about_what_blocks_an_issue():
    """The sentences and the codes are the server's. The panel and the reader name no code and carry no statutory sentence."""
    for path in (PANEL, READER):
        text = _strip(path)
        for code in ir.CODES:
            assert code not in text, f"{path.name} branches on the code {code}: the browser acts on the action, not on the reason"
        assert "Rule 46" not in text and "CGST" not in text, f"{path.name} carries a statutory sentence of its own"
