"""The firm's invoice and email templates, which nothing read (SALES-13).

WHAT WAS WRONG

    `public.invoice_templates` and `public.email_templates` (migration 126)
    have been written by two full Settings screens since the module was built,
    and no module in `apps/api` read a single column of either. A Partner
    created a "Professional CA" template with the logo centred and the
    signature on the left, marked it default, and every PDF came out logo-left
    signature-right; rewrote the engagement email in their own words and
    watched the product send the stock one.

WHAT THIS MODULE HOLDS

    The rule over the layout half — A TEMPLATE CHANGES THE LAYOUT AND NEVER THE
    PARTICULARS — and the boundary that keeps the practice's template on the
    practice's own document. For the email half: which merge fields each kind
    can fill, MEASURED at the sender; that an unfillable field is refused where
    it is typed rather than blanked where it is sent; and that three of the
    four kinds have no live mail and each says why in its own words.
"""
from __future__ import annotations

import inspect
import pathlib

import pytest

from domain.branding import email_template as et
from domain.branding import invoice_layout as il


def _code_only(src: str) -> str:
    """Python source with its docstrings and comments removed.

    A guard about what the CODE does must not read the prose explaining it.
    """
    import ast
    tree = ast.parse(src.strip())
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef, ast.Module))
                and ast.get_docstring(node) is not None):
            node.body = node.body[1:]
    return ast.unparse(tree)


def _tsx_code_only(src: str) -> str:
    """TSX with `//` lines and `/* */` blocks removed, the same rule as above
    stated for the other language — `a-financial-year-choice-comes-from-the-
    clock` had to learn this too."""
    import re as _re
    src = _re.sub(r"/\*.*?\*/", "", src, flags=_re.S)
    return _re.sub(r"^\s*//.*$", "", src, flags=_re.M)


# ── the layout, and what it may not do ───────────────────────────────────────

def test_a_firm_with_no_template_renders_exactly_as_before():
    """Migration 126's own defaults, so nothing moved on the day this landed."""
    lay = il.layout_from_row(None)
    assert lay == il.DEFAULT_LAYOUT
    assert lay.logo_position == "left" and lay.signature_placement == "right"
    assert lay.header_style == "standard" and lay.footer_style == "standard"


@pytest.mark.parametrize("position,expected", [
    ("left", "LEFT"), ("center", "CENTER"), ("right", "RIGHT")])
def test_the_logo_goes_where_the_template_says(position, expected):
    assert il.layout_from_row({"logo_position": position}).logo_alignment == expected


@pytest.mark.parametrize("placement,expected", [
    ("left", 0), ("center", 1), ("right", 2), ("none", None)])
def test_the_signature_goes_where_the_template_says(placement, expected):
    lay = il.layout_from_row({"signature_placement": placement})
    assert lay.signature_alignment == expected
    assert lay.prints_signature_block is (placement != "none")


def test_omitting_the_signature_names_rule_46_q_and_its_proviso():
    """Rule 46(q) is a PARTICULAR, so the one layout that removes it has to say
    what makes that lawful — the first proviso, for a digitally signed
    invoice — where the CA is choosing, not on the customer's paper."""
    notes = il.layout_from_row({"signature_placement": "none"}).statutory_notes()
    assert "Rule 46(q)" in notes[0]
    assert "FIRST PROVISO" in notes[0]
    assert "Information Technology Act 2000" in notes[0]


def test_every_layout_says_it_changes_no_particular():
    """The reassurance is as much the point as the warning: a CA choosing
    `minimal` needs to know it is not dropping the HSN."""
    for placement in il.SIGNATURE_PLACEMENTS:
        notes = il.layout_from_row({"signature_placement": placement}).statutory_notes()
        assert il.LAYOUT_NEVER_CHANGES_PARTICULARS in notes
    assert "HSN" in il.LAYOUT_NEVER_CHANGES_PARTICULARS
    assert "place of supply" in il.LAYOUT_NEVER_CHANGES_PARTICULARS


def test_a_value_the_vocabulary_does_not_hold_falls_back_and_never_raises():
    """The row was written through a validating endpoint behind a CHECK, so an
    unknown value means the vocabulary MOVED. Refusing to produce a CA's
    invoice over a layout preference is the wrong direction."""
    lay = il.layout_from_row({"logo_position": "diagonal",
                              "signature_placement": "", "header_style": None})
    assert lay.logo_position == il.DEFAULT_LOGO_POSITION
    assert lay.signature_placement == il.DEFAULT_SIGNATURE_PLACEMENT
    assert lay.header_style == il.DEFAULT_HEADER_STYLE


def test_only_the_tagline_is_ever_removed_by_a_header_style():
    """A tagline is not a Rule 46 particular. Nothing else is conditional."""
    assert il.layout_from_row({"header_style": "compact"}).prints_tagline is False
    for style in ("standard", "full"):
        assert il.layout_from_row({"header_style": style}).prints_tagline is True


def test_the_detailed_footer_adds_and_never_removes():
    assert il.layout_from_row({"footer_style": "detailed"}).prints_computer_generated_note
    for style in ("standard", "minimal"):
        assert not il.layout_from_row({"footer_style": style}).prints_computer_generated_note


def test_the_vocabularies_are_migration_126s_own_checks():
    sql = (pathlib.Path(__file__).resolve().parents[1]
           / "migrations" / "126_firm_branding.sql").read_text(encoding="utf-8")
    for value in (il.TEMPLATE_TYPES + il.LOGO_POSITIONS + il.HEADER_STYLES
                  + il.FOOTER_STYLES + il.SIGNATURE_PLACEMENTS):
        assert f"'{value}'" in sql, value


# ── the renderer actually honours it ─────────────────────────────────────────

_INVOICE = {"invoice_no": "INV/2026-27/001", "invoice_date": "2026-07-01",
            "status": "sent", "subtotal_paise": 1_00_000, "cgst_paise": 9_000,
            "sgst_paise": 9_000, "igst_paise": 0, "total_paise": 1_18_000}
_FIRM = {"id": "f1", "name": "Sharma & Co", "gstin": "27AAACT2727Q1ZW",
         "address": "Mumbai", "state_code": "27"}
_CLIENT = {"id": "c1", "client_name": "Acme Traders",
           "gstin": "27AABCU9603R1ZX", "state_code": "27"}
_BRAND = {"tagline": "Chartered Accountants", "footer_text": "Thank you"}


def _pdf(layout=None):
    """Render the practice's fee invoice DETERMINISTICALLY.

    `reportlab.rl_config.invariant` stamps a fixed creation date and document
    id. Without it every render differs in those bytes — so `_pdf() != _pdf()`
    is true of IDENTICAL renders, and the assertion below, which is the whole
    finding in one line, passed against a renderer that ignored the layout
    entirely. It did, when the negative control was run.
    """
    import reportlab.rl_config as rl_config
    from services.invoice_pdf_service import build_invoice_pdf
    was = rl_config.invariant
    rl_config.invariant = 1
    try:
        return build_invoice_pdf(dict(_INVOICE), dict(_FIRM), dict(_CLIENT),
                                 branding=dict(_BRAND), layout=layout)
    finally:
        rl_config.invariant = was


def test_two_identical_renders_are_byte_identical():
    """The premise the assertion below rests on. Without this the comparison
    is vacuous and cannot fail, which is exactly what it did."""
    assert _pdf() == _pdf()


def test_the_pdf_changes_when_the_template_does():
    """The whole finding in one assertion: a configured layout used to change
    nothing at all."""
    assert _pdf() != _pdf(il.layout_from_row({"signature_placement": "none"}))
    assert _pdf() != _pdf(il.layout_from_row({"footer_style": "detailed"}))
    assert _pdf() != _pdf(il.layout_from_row({"header_style": "compact"}))
    assert _pdf() != _pdf(il.layout_from_row({"signature_placement": "left"}))
    # NOT `logo_position`, and the reason is worth stating: the logo is a
    # REMOTE FETCH, `domain/branding/image_source` refuses every host a test
    # could stand one up on, and with no logo there is no flowable to align —
    # so a byte comparison here would pass whatever the renderer did with the
    # value. It is asserted where it can be: `logo_alignment` has its own unit
    # test above, and `test_the_renderer_reads_the_layout_rather_than_a_column`
    # holds the renderer to asking for it.


def test_the_renderer_reads_the_layout_rather_than_a_column():
    """Every branch asks the `InvoiceLayout`, so the vocabulary has one home.

    Scanned with the PROSE STRIPPED. The docstring explains what
    `signature_placement = 'none'` means and the comments name the columns
    they are about — a guard that reads those is failing on an explanation,
    which is the "a guard states a spelling of its own rule" shape this
    repository keeps having to fix. What it asserts is the CODE."""
    from services import invoice_pdf_service as pdf
    src = _code_only(inspect.getsource(pdf._render_tax_invoice))
    for column in ("logo_position", "header_style", "footer_style",
                   "signature_placement", "template_type"):
        assert column not in src, column
    for asked in ("lay.logo_alignment", "lay.prints_signature_block",
                  "lay.header_space_mm", "lay.footer_space_mm"):
        assert asked in src, asked


def test_a_clients_own_sales_invoice_gets_no_template_and_no_branding():
    """The practice's signature placement on a document its client issues to a
    stranger is the same confusion as the practice's UPI id on it."""
    from services import invoice_pdf_service as pdf
    src = inspect.getsource(pdf.build_sales_invoice_pdf)
    assert "layout=" not in src and "branding=" not in src
    sig = inspect.signature(pdf.build_sales_invoice_pdf)
    assert "layout" not in sig.parameters and "branding" not in sig.parameters


def test_the_fee_invoice_door_loads_the_firms_template():
    from services import invoice_pdf_service as pdf
    src = inspect.getsource(pdf.get_invoice_pdf)
    assert "_load_layout" in src and "_load_branding" in src


def test_a_template_that_cannot_be_read_still_renders_the_invoice():
    """A tax invoice that renders with the logo on the left is valid under
    Rule 46; one that does not render is not."""
    from services import invoice_pdf_service as pdf
    assert pdf._load_layout(None) == il.DEFAULT_LAYOUT


def test_the_repository_reads_the_default_and_the_active_one():
    """`is_default` alone would render a layout the CA has deactivated."""
    from repositories.branding_repository import branding_repo
    src = inspect.getsource(branding_repo.get_default_invoice_template)
    assert '"is_default"' in src and '"is_active"' in src


# ── the email templates ──────────────────────────────────────────────────────

def test_the_merge_field_vocabulary_is_the_backends():
    """The browser held this list and the backend did not, which is how a
    field for a kind that cannot fill it came to be offered."""
    vocab = et.merge_field_vocabulary()
    assert {f["name"] for f in vocab["fields"]} == set(et.MERGE_FIELDS)
    assert vocab["kinds"] == list(et.TEMPLATE_KINDS)


def test_an_unknown_placeholder_is_refused_where_it_is_typed():
    problem = et.problem_with("engagement", "Hi", "Dear {{clientname}}")
    assert problem and "is not a merge field" in problem
    assert "{{client_name}}" in problem


def test_a_field_the_mail_cannot_fill_is_refused_with_its_own_sentence():
    """An unknown field is a typo; an unfillable one is a real field in the
    wrong template. The two sentences are different and a test says so."""
    unfillable = et.problem_with("engagement", "Hi", "For {{financial_year}}")
    unknown = et.problem_with("engagement", "Hi", "For {{fy}}")
    assert unfillable and unknown and unfillable != unknown
    assert "cannot be filled in" in unfillable
    assert "is not a merge field" in unknown


def test_the_engagement_contract_is_measured_and_excludes_the_financial_year():
    """`public.engagements` (migration 115) has no financial-year column, so
    the mail has no value to put there and guessing one from the clock would
    state a year nobody recorded."""
    assert "financial_year" not in et.FIELDS_BY_KIND["engagement"]
    sql = (pathlib.Path(__file__).resolve().parents[1]
           / "migrations" / "115_engagement_letter_management.sql"
           ).read_text(encoding="utf-8")
    table = sql[sql.index("CREATE TABLE IF NOT EXISTS public.engagements"):]
    assert "financial_year" not in table[:table.index(");")]


def test_a_kind_with_no_live_mail_refuses_no_field_and_says_why_instead():
    """There is nothing to be unfilled by a mail nobody sends, and refusing on
    a contract nobody has measured is a guess wearing a validator's clothes."""
    for kind in ("invoice", "reminder", "document_request"):
        assert kind not in et.FIELDS_BY_KIND
        assert et.unfillable_fields(kind, "x", "{{invoice_amount}}") == []
        status = et.kind_status(kind)
        assert status["is_applied"] is False and status["reason"]


def test_the_three_not_applied_reasons_are_different():
    """One kind has no mail at all, one has a mail nothing calls, and one's
    only mail is sent on the CLIENT's behalf. A shared sentence would say the
    wrong thing about two of them."""
    reasons = [et.kind_status(k)["reason"]
               for k in ("invoice", "reminder", "document_request")]
    assert len(set(reasons)) == 3


def test_exactly_one_kind_is_live_and_it_is_the_engagement_letter():
    live = [k for k, v in et.KIND_IS_LIVE.items() if v]
    assert live == ["engagement"]
    assert et.kind_status("engagement")["reason"] is None


def test_a_render_refuses_rather_than_leaving_a_hole():
    """A mail with a gap in it is worse than a mail in the stock wording: the
    stock wording is correct and merely impersonal."""
    assert et.render("Dear {{client_name}}", {"client_name": "Acme"}) == "Dear Acme"
    assert et.render("Dear {{client_name}}", {"client_name": ""}) is None
    assert et.render("Dear {{client_name}}", {}) is None
    assert et.render("Dear {{nope}}", {"nope": "x"}) is None


def test_a_body_is_escaped_on_its_way_into_the_mail():
    assert et.as_html("Fees & taxes\nLine 2") == "Fees &amp; taxes<br/>Line 2"
    assert "<b>" not in et.as_html("<b>bold</b>")


# ── the senders ──────────────────────────────────────────────────────────────

def test_the_engagement_mail_asks_for_the_firms_wording():
    from services import email_service as es
    src = inspect.getsource(es.send_engagement_letter)
    assert '_firm_wording("engagement"' in src
    assert "firm_id" in inspect.signature(es.send_engagement_letter).parameters


def test_what_the_firms_wording_returned_actually_reaches_the_mail():
    """THE RULE, NOT A NAME. The guard above asserts the CALL is there, and
    the negative control that deleted the two lines using its result PASSED —
    the call survived with its value dropped on the floor.

    That is the fifth time in two days. This walks the AST and asserts the
    name bound from `_firm_wording` is READ somewhere after it."""
    import ast
    from services import email_service as es

    fn = ast.parse(inspect.getsource(es.send_engagement_letter).strip()).body[0]
    bound: set[str] = set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "_firm_wording"):
            bound |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    assert bound, "the firm's wording is never resolved"
    loads = {n.id for n in ast.walk(fn)
             if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    assert bound & loads, (
        f"{bound} is resolved and never read — the stock wording always wins")


def test_the_sender_supplies_every_field_its_kind_promises():
    """FIELDS_BY_KIND is a CONTRACT. A sender that stops supplying one of these
    breaks the template silently — the render refuses and the stock wording
    goes out, with nobody told."""
    from services import email_service as es
    src = inspect.getsource(es.send_engagement_letter)
    block = src[src.index('_firm_wording("engagement"'):]
    for field in et.FIELDS_BY_KIND["engagement"]:
        assert f'"{field}"' in block, field


def test_the_engagement_router_passes_the_firm():
    import routers.engagement_letters as r
    assert "firm_id=firm_id" in inspect.getsource(r._deliver_engagement_email)


def test_no_firm_wording_reaches_a_mail_sent_on_the_clients_behalf():
    """`email_templates` is the PRACTICE's, and these two go from the client to
    the client's customer — the same boundary `build_sales_invoice_pdf` holds
    for branding and layout."""
    from services import email_service as es
    for fn in (es.send_invoice_to_customer, es.send_payment_reminder_to_customer):
        assert "_firm_wording" not in inspect.getsource(fn), fn.__name__
        assert "firm_id" not in inspect.signature(fn).parameters, fn.__name__


def test_a_customer_mail_names_the_client_and_not_the_practice():
    """No finding; found building this. `build_sales_invoice_pdf` has refused
    the practice's name on this document since it was written, and the EMAIL
    carrying that PDF still said "Invoice INV/001 from Sharma & Co" to somebody
    who bought goods from Acme Traders."""
    import routers.sales_invoices as si
    from services import collections_service as cs
    sales = inspect.getsource(si._do_send_invoice)
    assert '.table("clients")' in sales and "legal_name" in sales
    assert 'db.table("firms").select("name")' not in sales
    reminder = inspect.getsource(cs._dispatch_invoice_reminder)
    assert "_client_supplier_name" in reminder
    assert "_load_firm" not in reminder


def test_the_client_name_falls_back_to_a_neutral_word_never_to_the_practice():
    from services import collections_service as cs
    src = inspect.getsource(cs._client_supplier_name)
    assert '"Your supplier"' in src
    assert "Chartered Accountant" not in src


def test_a_firm_that_saved_no_template_gets_the_built_in_wording():
    from services import email_service as es
    assert es._firm_wording("engagement", None, {"firm_name": "X"}) is None


# ── the doors ────────────────────────────────────────────────────────────────

def test_both_email_doors_ask_the_one_validator():
    """A validator on create alone is one PATCH from being none, and the PATCH
    is the door reached SECOND — after the template already looks saved."""
    import routers.branding as b
    for fn in (b.upsert_email_template, b.update_email_template):
        assert "_et.problem_with" in inspect.getsource(fn), fn.__name__


def test_the_router_serves_the_vocabulary_rather_than_holding_one():
    import routers.branding as b
    assert "merge_field_vocabulary" in inspect.getsource(b.list_email_templates)
    assert "statutory_notes" in inspect.getsource(b.list_invoice_templates)
    # The two local sets are the domain module's, not second copies.
    assert b._VALID_EMAIL_TYPES == set(et.TEMPLATE_KINDS)
    assert b._VALID_TEMPLATE_TYPES == set(il.TEMPLATE_TYPES)


# ── the screens ──────────────────────────────────────────────────────────────

def _screen(path: str) -> str:
    return (pathlib.Path(__file__).resolve().parents[2] / path
            ).read_text(encoding="utf-8")


def test_the_email_screen_says_which_wordings_are_actually_sent():
    src = _screen("web/app/settings/email-templates/page.tsx")
    assert "status_by_kind" in src
    assert "activeStatus" in src and "is_applied" in src


def test_the_shipped_engagement_default_is_one_the_server_will_accept():
    """It used {{financial_year}}, which the engagement mail cannot fill — so
    a CA pressing Reset to default then Save would have been refused by the
    door this change adds."""
    src = _screen("web/app/settings/email-templates/page.tsx")
    engagement = src[src.index("  engagement: {"):src.index("  document_request: {")]
    assert "{{financial_year}}" not in engagement
    problem = et.problem_with(
        "engagement",
        engagement[engagement.index('subject: "') + 10:engagement.index('",\n')],
        engagement)
    assert problem is None or "not a merge field" not in problem


def test_the_invoice_template_screen_renders_the_served_notes():
    """And spells no statute of its own — the Schedule III caption mistake."""
    src = _screen("web/app/settings/invoice-templates/page.tsx")
    assert "statutory_notes" in src
    rendered = _tsx_code_only(src)
    assert "Rule 46(q)" not in rendered
    assert "first proviso" not in rendered.lower()
    assert "Information Technology Act" not in rendered
