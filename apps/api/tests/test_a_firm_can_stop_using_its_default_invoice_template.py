"""A firm can delete its default invoice template, or stop using it, and the
invoices go back to the built-in layout (sweep-settings-hub-1-06).

WHAT WAS WRONG

`DELETE /api/settings/invoice-templates/{id}` refused the default with "Set
another template as default first", `set-default` could only MOVE the default,
and the Settings screen hid Delete on the default card. So a firm with a single
template could neither delete it nor stop using it — the sweep had to create a
second template to escape the first, and left it behind in production.

The premise was that a firm must always have a default. It need not, and never
had to: `branding_repo.get_default_invoice_template` answers None for a firm
with none marked, and `layout_from_row(None)` is migration 126's own built-in
layout — the one every firm renders with before it opens the screen.

Every test here CALLS the router functions (mock mode), because the defect was
a refusal in behaviour, not a missing string.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

import routers.branding as br
from domain.branding import invoice_layout as il
from repositories.branding_repository import branding_repo


@pytest.fixture
def user():
    # A firm of its own per test: the mock store is module-global.
    return {"id": "u-tpl", "auth_user_id": "u-tpl", "email": "p@example.com",
            "role": "Partner", "firm_id": f"firm-tpl-{uuid.uuid4()}"}


def _create(user, name="Only template", default=True) -> dict:
    res = br.create_invoice_template(
        br.InvoiceTemplateCreate(name=name, is_default=default), current_user=user)
    assert res["success"]
    return res["data"]["template"]


def test_the_only_template_can_be_deleted_while_it_is_the_default(user):
    t = _create(user)
    assert branding_repo.get_default_invoice_template(user["firm_id"])["id"] == t["id"]

    res = br.delete_invoice_template(t["id"], current_user=user)

    assert res["success"] and res["data"]["deleted"] is True
    assert res["data"]["was_default"] is True
    assert res["data"]["layout_now"] == il.NO_DEFAULT_TEMPLATE_NOTE
    assert branding_repo.list_invoice_templates(user["firm_id"]) == []
    # …and the renderer falls back exactly as for a firm that never chose one.
    assert branding_repo.get_default_invoice_template(user["firm_id"]) is None
    assert il.layout_from_row(None) == il.DEFAULT_LAYOUT


def test_deleting_a_template_that_is_not_the_default_names_no_layout_change(user):
    _create(user, "Kept default")
    other = _create(user, "Spare", default=False)

    res = br.delete_invoice_template(other["id"], current_user=user)

    assert res["data"]["was_default"] is False
    assert res["data"]["layout_now"] is None
    assert branding_repo.get_default_invoice_template(user["firm_id"])["name"] == "Kept default"


def test_the_default_can_be_unmarked_and_the_template_is_kept(user):
    t = _create(user)

    res = br.unset_default_template(t["id"], current_user=user)

    assert res["success"] and res["data"]["was_default"] is True
    assert res["data"]["layout_now"] == il.NO_DEFAULT_TEMPLATE_NOTE
    assert branding_repo.get_default_invoice_template(user["firm_id"]) is None
    kept = branding_repo.list_invoice_templates(user["firm_id"])
    assert [k["id"] for k in kept] == [t["id"]] and kept[0]["is_default"] is False


def test_unmarking_a_template_that_is_not_the_default_changes_nothing(user):
    default = _create(user, "Default")
    spare = _create(user, "Spare", default=False)

    res = br.unset_default_template(spare["id"], current_user=user)

    assert res["success"] and res["data"]["was_default"] is False
    assert res["data"]["layout_now"] is None
    assert branding_repo.get_default_invoice_template(user["firm_id"])["id"] == default["id"]


def test_another_firms_template_cannot_be_unmarked(user):
    t = _create(user)
    stranger = {**user, "firm_id": f"firm-other-{uuid.uuid4()}"}
    with pytest.raises(HTTPException) as e:
        br.unset_default_template(t["id"], current_user=stranger)
    assert e.value.status_code == 404
    assert branding_repo.get_default_invoice_template(user["firm_id"])["id"] == t["id"]


def test_the_list_serves_what_applies_when_nothing_is_default(user):
    res = br.list_invoice_templates(current_user=user)
    assert res["data"]["no_default_note"] == il.NO_DEFAULT_TEMPLATE_NOTE


def test_the_note_describes_the_layout_the_renderer_actually_falls_back_to():
    """The sentence names the built-in layout; if migration 126's defaults ever
    move, this fails rather than the screen describing a layout nobody gets."""
    d = il.DEFAULT_LAYOUT
    assert (d.template_type, d.logo_position, d.header_style,
            d.footer_style, d.signature_placement) == (
        "classic", "left", "standard", "standard", "right")
    note = il.NO_DEFAULT_TEMPLATE_NOTE
    for word in ("Classic", "logo on the left", "standard header and footer",
                 "signature on the right"):
        assert word in note


def test_the_screen_offers_both_ways_out_on_the_default_card():
    """The screen half: Delete is no longer gated on `!template.is_default`,
    and the default card can reach the new door."""
    import pathlib
    import re
    src = (pathlib.Path(__file__).resolve().parents[2] / "web" / "app" / "settings"
           / "invoice-templates" / "page.tsx").read_text(encoding="utf-8")
    assert not re.search(r"!template\.is_default\s*&&\s*\(\s*<button onClick=\{onDelete\}", src)
    assert "api.invoiceTemplates.unsetDefault(" in src
    assert "onClick={onUnsetDefault}" in src
    # What applies with no default is the SERVER's sentence, never one spelled here.
    assert "no_default_note" in src and "built-in layout:" not in src
