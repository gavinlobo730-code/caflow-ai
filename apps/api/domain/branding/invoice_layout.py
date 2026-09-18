"""What an invoice template may change, and what it may never change (SALES-13).

WHAT WAS WRONG

    `public.invoice_templates` (migration 126) has held a firm's chosen layout
    since the module was built — `template_type`, `logo_position`,
    `header_style`, `footer_style`, `signature_placement`, with one row per
    firm marked `is_default` — and a full Settings screen has written it,
    headed *"Choose a layout style for your invoices and engagement
    documents"*.

    **Nothing read a single one of those five columns.**
    `repositories/branding_repository.py` and `routers/branding.py` only list,
    create, update and delete; `services/invoice_pdf_service._render_tax_invoice`
    took no template argument and no module in `apps/api` mentioned
    `logo_position` or `signature_placement` at all. A Partner created a
    "Professional CA" template with the logo centred and the signature on the
    left, marked it default, and every PDF came out with the logo left and the
    signature right — the same `capital_wip` / `fx_revaluation_service` /
    §115BAC(6) shape this repository keeps finding: built, configured,
    reachable from nowhere.

THE RULE OVER ALL OF IT

    **A TEMPLATE CHANGES THE LAYOUT AND NEVER THE PARTICULARS.** CGST Rule 46
    lists what a tax invoice must contain — (a) the supplier's name, address
    and GSTIN through to (q) the signature — and a layout picker that could
    remove one would let a CA issue a document that is not a tax invoice. So
    every field here moves where something sits on the page, or how much space
    it takes, and none of them decides WHETHER a particular is printed.

    `signature_placement = 'none'` is the one that looks like an exception and
    is not: see `RULE_46_Q_NOTE`. It is honoured, because the FIRST PROVISO to
    Rule 46 dispenses with the signature where the invoice is issued with a
    digital signature under the Information Technology Act 2000, and that is a
    real way a practice bills. What it is not is silent — the note travels
    with the template so the CA is told at the point they choose, which is the
    `attachmentsReadOnly` discipline applied to a statutory condition rather
    than to a permission.

THE TEMPLATE IS THE PRACTICE'S AND REACHES ONLY THE PRACTICE'S OWN INVOICE

    The same boundary `branding` already holds. `build_invoice_pdf` renders the
    FEE invoice, where the practice is the supplier and is choosing how its own
    document looks; `build_sales_invoice_pdf` renders a CLIENT's sales invoice,
    where the practice is not a party at all — so it takes no `branding` and
    takes no `layout`, and a test asserts it never will. A firm's signature
    placement on a document its client issues to a stranger is the same
    confusion as the practice's UPI id on it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: Migration 126's own CHECK vocabularies, read from the column rather than
#: invented here — a sixth `logo_position` would be rejected by the database
#: and must be rejected by the renderer for the same reason.
TEMPLATE_TYPES = ("classic", "modern", "professional_ca", "corporate", "minimal")
LOGO_POSITIONS = ("left", "center", "right")
HEADER_STYLES = ("standard", "compact", "full")
FOOTER_STYLES = ("standard", "minimal", "detailed")
SIGNATURE_PLACEMENTS = ("left", "center", "right", "none")

#: The defaults migration 126 declares. Stated once so a firm with no template
#: renders exactly as it did before this module existed.
DEFAULT_TEMPLATE_TYPE = "classic"
DEFAULT_LOGO_POSITION = "left"
DEFAULT_HEADER_STYLE = "standard"
DEFAULT_FOOTER_STYLE = "standard"
DEFAULT_SIGNATURE_PLACEMENT = "right"

RULE_46_Q_NOTE = (
    "This template prints no signature block. CGST Rule 46(q) requires the "
    "signature or digital signature of the supplier or their authorised "
    "representative; the FIRST PROVISO to Rule 46 dispenses with it only where "
    "the invoice is issued in accordance with the Information Technology Act "
    "2000 with a digital signature. Choose this only if your invoices are "
    "digitally signed."
)

#: Said on every template, whatever it is set to. A layout picker is the most
#: natural place for somebody to expect "and this one leaves off the HSN" — it
#: does not, and cannot.
LAYOUT_NEVER_CHANGES_PARTICULARS = (
    "A template changes the layout only. Every CGST Rule 46 particular — the "
    "supplier's and recipient's names, addresses and GSTINs, the serial "
    "number and date, the HSN or SAC, the taxable value and each tax head, "
    "the place of supply and whether tax is on reverse charge — is printed on "
    "every layout."
)


@dataclass(frozen=True)
class InvoiceLayout:
    """One firm's chosen layout, normalised.

    EVERY FIELD FALLS BACK TO MIGRATION 126's OWN DEFAULT rather than raising.
    A tax invoice that renders with the logo on the left is valid under Rule
    46; one that does not render is not — the rule `_load_branding` already
    states for the same document.
    """
    template_type: str = DEFAULT_TEMPLATE_TYPE
    logo_position: str = DEFAULT_LOGO_POSITION
    header_style: str = DEFAULT_HEADER_STYLE
    footer_style: str = DEFAULT_FOOTER_STYLE
    signature_placement: str = DEFAULT_SIGNATURE_PLACEMENT

    # ── what the renderer asks it ────────────────────────────────────────────

    @property
    def logo_alignment(self) -> str:
        """reportlab's own `hAlign` for the logo flowable."""
        return {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}[
            self.logo_position]

    @property
    def signature_alignment(self) -> Optional[int]:
        """reportlab's `alignment` for the signature block, or None for
        'none' — which omits the block entirely. See RULE_46_Q_NOTE."""
        return {"left": 0, "center": 1, "right": 2}.get(self.signature_placement)

    @property
    def prints_signature_block(self) -> bool:
        return self.signature_placement != "none"

    @property
    def prints_tagline(self) -> bool:
        """`compact` drops the firm's tagline; it is not a Rule 46 particular
        and is the only thing a header style removes."""
        return self.header_style != "compact"

    @property
    def header_space_mm(self) -> float:
        return {"compact": 3.0, "standard": 6.0, "full": 9.0}[self.header_style]

    @property
    def footer_space_mm(self) -> float:
        return {"minimal": 4.0, "standard": 8.0, "detailed": 12.0}[self.footer_style]

    @property
    def prints_computer_generated_note(self) -> bool:
        """`detailed` adds the line most practices print under the footer. It
        is an addition, never a removal — see LAYOUT_NEVER_CHANGES_PARTICULARS."""
        return self.footer_style == "detailed"

    def statutory_notes(self) -> list[str]:
        """What this layout obliges the CA to be able to say, in their words.

        Always carries LAYOUT_NEVER_CHANGES_PARTICULARS, because the reassurance
        is as much the point as the warning: a CA choosing `minimal` needs to
        know it is not dropping the HSN.
        """
        notes = [LAYOUT_NEVER_CHANGES_PARTICULARS]
        if not self.prints_signature_block:
            notes.insert(0, RULE_46_Q_NOTE)
        return notes

    def to_dict(self) -> dict:
        return {
            "template_type": self.template_type,
            "logo_position": self.logo_position,
            "header_style": self.header_style,
            "footer_style": self.footer_style,
            "signature_placement": self.signature_placement,
            "statutory_notes": self.statutory_notes(),
        }


DEFAULT_LAYOUT = InvoiceLayout()


def _one_of(value, allowed: tuple[str, ...], default: str) -> str:
    """A value the vocabulary does not hold reads as the DEFAULT, silently.

    Deliberate, and the opposite of what a write door does. The row was written
    through an endpoint that validates, and behind a CHECK that validates
    again, so an unknown value here means the vocabulary has MOVED — a column
    widened by a later migration and a renderer not yet taught it. Raising
    would refuse to produce the CA's invoice over a layout preference; the
    default is the layout every invoice had before templates were read at all.
    """
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def layout_from_row(row: Optional[dict]) -> InvoiceLayout:
    """The firm's chosen layout, or migration 126's defaults where no template
    is marked default — which is every firm that has never opened the screen."""
    if not row:
        return DEFAULT_LAYOUT
    return InvoiceLayout(
        template_type=_one_of(row.get("template_type"), TEMPLATE_TYPES,
                              DEFAULT_TEMPLATE_TYPE),
        logo_position=_one_of(row.get("logo_position"), LOGO_POSITIONS,
                              DEFAULT_LOGO_POSITION),
        header_style=_one_of(row.get("header_style"), HEADER_STYLES,
                             DEFAULT_HEADER_STYLE),
        footer_style=_one_of(row.get("footer_style"), FOOTER_STYLES,
                             DEFAULT_FOOTER_STYLE),
        signature_placement=_one_of(row.get("signature_placement"),
                                    SIGNATURE_PLACEMENTS,
                                    DEFAULT_SIGNATURE_PLACEMENT),
    )
