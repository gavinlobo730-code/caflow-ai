"""
GST-compliant invoice PDF generation.

TWO documents are rendered here, and their SUPPLIERS are different parties:

  * the practice's own FEE invoice (`fee_invoices`) — the CA firm supplies and
    the client receives.  build_invoice_pdf() / get_invoice_pdf()
  * the client's own SALES invoice (`client_sales_invoices`) — the CLIENT
    supplies and the client's CUSTOMER receives.  build_sales_invoice_pdf() /
    get_sales_invoice_pdf()

One builder used to render both, and it named the FIRM as supplier. Every
client sales invoice therefore went out under the CA practice's name, GSTIN and
PAN — on four paths (the Download PDF button, the invoice email, the dunning
chasers in collections_service, and the client portal). The customer then held
a tax invoice whose stated supplier never made the supply: input tax credit
claimed against that GSTIN has nothing to match in GSTR-2B, and the claim
fails — while the same invoice was reported to GSTR-1 under the CLIENT's GSTIN
(`_client_gstin` in routers/gst.py), so the printed document and the filed
return disagreed about who made the supply.

The two documents are separated here. The fee invoice keeps its layout, its SAC
998211 default and its synthetic engagement row; it changes in exactly two
ways, both shared with the fix and neither a behaviour it relied on: the party
blocks now print the city/state/pincode the rows already carried (Rule 46(a),
(e)), and the printed tax rate is derived rather than the constant 18 — which
for a fee invoice at 18% renders identically.

Mandatory tax invoice particulars per Rule 46, CGST Rules 2017 (under
Section 31, CGST Act 2017), and where each one comes from:

  (a)     supplier name, address, GSTIN   fee: firms row / sale: clients row
  (b)     consecutive serial number       invoice_no
  (c)     date of issue                   invoice_date
  (e)(f)  recipient name, address, GSTIN  fee: clients row / sale: customers row
  (g)     HSN or SAC                      the LINE's own hsn_sac
  (h)     quantity and unit               the line's quantity and unit
  (i)(j)  taxable value                   the line's taxable_amount_paise
  (l)     rate and amount of tax per head the line's gst_rate_bps, else derived
                                          from the stored heads — never a constant
  (n)     place of supply (inter-State)   supply_state_code
  (p)     reverse-charge statement        is_reverse_charge
  (q)     signature of the SUPPLIER       "For <supplier>"
  (r)     QR code with embedded IRN       einvoice_records.irn / qr_data, and
                                          ONLY where status == "generated" —
                                          see _einvoice_particulars()

Nothing is invented. A particular that is not held is left blank and named in a
"Not recorded" note under the table — the house style used elsewhere for
statutory data a human has to supply (payroll `statutory_gaps`, vendor
`msme_status`). A plausible substitute on a tax invoice is not a cosmetic
defect: it is a wrong statutory document in the recipient's hands.

All monetary values arrive as integer paise and are formatted for display only
— no float arithmetic is performed on amounts. Tax RATES are held in basis
points and are likewise formatted by integer arithmetic.
"""
import io
import logging
import re
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing

logger = logging.getLogger("caflow.services")

# SAC 998211 is "legal and accounting services" — the PRACTICE's own supply.
# It is the default only on the practice's fee invoice. It is never printed on
# a client's sales invoice: what the client sells is not what the CA sells.
SAC_CODE = "998211"


def _paise_to_rupee_str(paise: int) -> str:
    """Format integer paise as rupees string, e.g. 123456 -> '1,234.56'."""
    rupees = paise // 100
    fraction = paise % 100
    return f"{rupees:,}.{fraction:02d}"


# The amount in words MOVED to domain/reporting/amount_words.py when the
# payslip came to need the same sentence — one implementation, imported here,
# rather than two that drift. Re-exported under this name because the invoice
# tests and this module's own callers import it from here.
#
# The move also fixed the crore group: it was read by a three-digit renderer,
# so an invoice over ₹999 crore read "Ten Hundred Crore" and one over ₹20,000
# crore raised IndexError out of the PDF builder.
from domain.branding import image_source  # noqa: E402
from domain.reporting.amount_words import amount_in_words  # noqa: E402,F401


def _state_code(gstin: Optional[str]) -> Optional[str]:
    if gstin and len(gstin) >= 2 and gstin[:2].isdigit():
        return gstin[:2]
    return None


# ── Rates: basis points in, a percentage label out (integer arithmetic only) ──
#
# A rate is stored in basis points (gst_rate_bps: 1800 = 18.00%). Internally we
# carry thousandths of a percent ("millipct") so that halving an odd rate for
# the CGST/SGST split stays exact: 0.25% = 250 millipct, half = 125 = 0.125%.

_MILLIPCT_PER_BPS = 10


def _pct_label(millipct: int) -> str:
    """18000 -> '18', 2500 -> '2.5', 125 -> '0.125'. Display only."""
    whole, frac = divmod(int(millipct), 1000)
    if frac == 0:
        return str(whole)
    return f"{whole}.{frac:03d}".rstrip("0")


def _rate_from_amounts(taxable_paise: int, tax_paise: int) -> Optional[int]:
    """The rate ACTUALLY charged, in millipct, derived from the stored amounts.

    CGST Rule 46(l) requires the rate of tax charged — so where no stored rate
    is held, it is computed from the money that was charged rather than assumed.
    Integer arithmetic, rounded half up. None when it cannot be computed.
    """
    taxable_paise = int(taxable_paise or 0)
    tax_paise = int(tax_paise or 0)
    if taxable_paise <= 0 or tax_paise <= 0:
        return None
    return (tax_paise * 100_000 + taxable_paise // 2) // taxable_paise


def _line_rate(line: dict) -> Optional[int]:
    """A single line's GST rate in millipct: its stored gst_rate_bps where it has
    one, otherwise the rate its own tax heads work out to. None when neither is
    available (a nil-rated or exempt line carries no rate to print)."""
    bps = line.get("gst_rate_bps")
    # gst_rate_bps is INTEGER NOT NULL on client_sales_invoice_lines (migration
    # 050). Anything else — absent, or a legacy row that predates the column —
    # falls through to the rate this line's own tax works out to, which is an
    # answer rather than a guess, so there is nothing here to swallow.
    if isinstance(bps, int) and not isinstance(bps, bool):
        return bps * _MILLIPCT_PER_BPS
    return _rate_from_amounts(
        line.get("taxable_amount_paise", 0),
        (int(line.get("cgst_paise", 0) or 0)
         + int(line.get("sgst_paise", 0) or 0)
         + int(line.get("igst_paise", 0) or 0)),
    )


def _document_rate(lines: list, taxable_paise: int, gst_paise: int) -> Optional[int]:
    """The ONE rate the summary rows may state, in millipct, or None.

    Rule 46(l) is the rate of tax charged. A mixed-rate invoice has no single
    rate: blending 5% and 18% into "5.75%" states a rate nobody charged, so the
    summary rows drop the rate entirely and each LINE states its own instead.
    Where the lines say nothing about their rate, the rate the stored heads work
    out to is the rate charged, and that is what is printed.
    """
    known = {r for r in (_line_rate(line) for line in (lines or [])) if r is not None}
    if len(known) > 1:
        return None
    header = _rate_from_amounts(taxable_paise, gst_paise)
    if len(known) == 1:
        rate = known.pop()
        # A stored rate that contradicts the money charged is not printed either.
        return rate if (header is None or rate == header) else None
    return header


def _qty_label(value) -> str:
    """quantity is NUMERIC(10,3): '2.500' -> '2.5', 1 -> '1', None -> ''."""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


# ── Parties ──────────────────────────────────────────────────────────────────

_STATE_NAMES: dict[str, str] = {}


def _state_name(code: Optional[str]) -> Optional[str]:
    """State name for a 2-digit GST state code (Rule 46(n) wants the name of the
    State alongside its code). Derived from the canonical map in core.validators
    — the first name for a code is the canonical one, the rest are aliases."""
    if not code:
        return None
    if not _STATE_NAMES:
        from core.validators import INDIAN_STATE_CODES
        for name, c in INDIAN_STATE_CODES.items():
            _STATE_NAMES.setdefault(c, " ".join(
                w if w in ("and", "&") else w.capitalize() for w in name.split()))
    return _STATE_NAMES.get(str(code).strip())


# ── Rule 46(r): the IRN and its signed QR ────────────────────────────────────
#
# WHAT MAY BE PRINTED, AND WHAT MAY NEVER BE
#     An IRN is minted by the Invoice Registration Portal and nothing else. This
#     application PREPARES e-invoices (CLAUDE.md: "prepare-only e-invoice/e-way/
#     XBRL rails"); domain/income_tax/einvoice_service.record_irn_generated
#     exists to record that "CA has generated IRN on the government portal", and
#     it is the only writer of `irn`, `ack_number`, `ack_date` and `qr_data`. It
#     sets status "generated".
#
#     So a record at status "generated" carries a REAL IRN the CA obtained from
#     the IRP, and printing it is Rule 46(r). A record at any other status
#     carries none, and inventing or simulating one would put a fabricated
#     statutory particular on a document that goes to the recipient — the same
#     line the filing demo holds, for the same reason.
#
#     The QR is rendered from the IRP's own signed payload, verbatim. It is not
#     built from the invoice's fields: the whole value of the QR is that it
#     carries the portal's signature, and a QR this application composed would
#     scan and verify as nothing.
_EINVOICE_GENERATED = "generated"


def _einvoice_particulars(record: Optional[dict]) -> dict:
    """The Rule 46(r) fields, or {} when there is no real IRN to print."""
    if not record or record.get("status") != _EINVOICE_GENERATED:
        return {}
    if not record.get("irn"):
        # "generated" with no IRN is a contradiction, and the safe reading is
        # that nothing was generated.
        return {}
    return {
        "irn": str(record["irn"]).strip(),
        "ack_number": (record.get("ack_number") or "") and str(record["ack_number"]).strip(),
        "ack_date": str(record.get("ack_date") or "")[:10],
        "qr_data": record.get("qr_data") or None,
    }


def _qr_flowable(qr_data: Optional[str]):
    """The IRP's signed QR payload as a drawing, or None.

    Returns None rather than raising: a PDF that fails to render is worse than
    one missing a QR, and the IRN itself is printed either way.
    """
    if not qr_data:
        return None
    try:
        widget = qr.QrCodeWidget(str(qr_data))
        bounds = widget.getBounds()
        w, h = bounds[2] - bounds[0], bounds[3] - bounds[1]
        side = 28 * mm
        d = Drawing(side, side, transform=[side / w, 0, 0, side / h, 0, 0])
        d.add(widget)
        return d
    except Exception:                       # pragma: no cover - defensive
        logger.warning("caflow.invoice_pdf: could not render the e-invoice QR")
        return None


def _accent_colour(value: Optional[str]):
    """A branding colour as reportlab understands it, or None.

    The router validates #RRGGBB on the way in; this refuses anything else on
    the way out rather than trusting a row written before that validation, or
    by a migration. A bad colour is no colour — never a raised exception in a
    document builder.
    """
    text = str(value or "").strip()
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", text):
        return None
    try:
        return colors.HexColor(text)
    except Exception:                       # pragma: no cover - defensive
        return None


# How long the PDF will wait for a branding image before giving up on it.
#
# THIS IS A NETWORK CALL INSIDE A DOCUMENT BUILDER, which is why the budget is
# small and the failure is silent. The API runs in Singapore and the asset is
# in Supabase storage; a logo that does not answer must cost an invoice a
# second, not a timeout. An invoice without a logo is still a valid Rule 46 tax
# invoice — one that never renders is not.
_IMAGE_TIMEOUT_SECONDS = 3.0
_MAX_IMAGE_BYTES = 2_000_000
#: How many redirects to follow by hand. Three is more than a storage bucket or
#: a CDN needs and few enough that a loop cannot burn the request budget.
_MAX_IMAGE_REDIRECTS = 3


def _remote_image(url: Optional[str], *, max_width_mm: float, max_height_mm: float):
    """A branding image as a flowable, or None. Never raises.

    Used for the firm's logo and for an uploaded UPI QR. Both are the
    SUPPLIER's own and both are optional, so every failure — no URL, a bad
    scheme, a slow host, an oversized file, an unreadable image — is None.
    """
    text = str(url or "").strip()
    problem = image_source.refusal(text)
    if problem:
        # A SERVER-SIDE FETCH OF A URL A USER TYPED, so where it points is a
        # decision and not a detail. `domain/branding/image_source.py` refuses a
        # private, loopback, link-local or metadata address, by literal and by
        # what the name resolves to; this used to fetch anything beginning
        # http(s), from a Singapore host inside a provider network.
        logger.warning("caflow.invoice_pdf: branding image refused — %s", problem)
        return None
    try:
        import httpx
        # REDIRECTS ARE FOLLOWED BY HAND, one hop at a time, re-asking the rule
        # before each. `follow_redirects=True` performs the next request before
        # anything can inspect where it went — which is the whole vector: a
        # perfectly public URL that 302s to 169.254.169.254.
        with httpx.Client(timeout=_IMAGE_TIMEOUT_SECONDS, follow_redirects=False) as client:
            res = client.get(text)
            for _hop in range(_MAX_IMAGE_REDIRECTS):
                if res.status_code not in (301, 302, 303, 307, 308):
                    break
                nxt = str(res.headers.get("location") or "").strip()
                if not nxt:
                    return None
                nxt = str(res.url.join(nxt))
                hop_problem = image_source.refusal(nxt)
                if hop_problem:
                    logger.warning(
                        "caflow.invoice_pdf: branding image redirect refused — %s",
                        hop_problem)
                    return None
                res = client.get(nxt)
            else:
                logger.warning("caflow.invoice_pdf: branding image redirected too many times")
                return None
        res.raise_for_status()
        blob = res.content
        if not blob or len(blob) > _MAX_IMAGE_BYTES:
            logger.warning("caflow.invoice_pdf: branding image is empty or too large")
            return None
        img = Image(io.BytesIO(blob))
        # Scale to fit the box, never up: a 64px logo blown up to 40mm is worse
        # than a small one.
        scale = min(max_width_mm * mm / img.imageWidth,
                    max_height_mm * mm / img.imageHeight, 1.0)
        img.drawWidth = img.imageWidth * scale
        img.drawHeight = img.imageHeight * scale
        return img
    except Exception:                       # noqa: BLE001 — see the docstring
        logger.warning("caflow.invoice_pdf: could not load the branding image")
        return None


def _logo(url: Optional[str]):
    return _remote_image(url, max_width_mm=45, max_height_mm=18)


def _place_of_supply_label(code: Optional[str]) -> Optional[str]:
    code = (str(code).strip() if code else "")
    if not code:
        return None
    name = _state_name(code)
    return f"{code} — {name}" if name else code


def _address_lines(row: dict) -> list[str]:
    """Address lines from whichever address columns the row carries: a single
    `address` (firms, customers) and/or address_line1/2 + city/state/pincode
    (clients). Rule 46(a)/(e) — address of the supplier and of the recipient."""
    lines: list[str] = []
    if row.get("address"):
        lines.append(str(row["address"]))
    for key in ("address_line1", "address_line2"):
        if row.get(key):
            lines.append(str(row[key]))
    tail = ", ".join(str(row[k]) for k in ("city", "state") if row.get(k))
    if row.get("pincode"):
        tail = f"{tail} - {row['pincode']}" if tail else str(row["pincode"])
    if tail:
        lines.append(tail)
    return lines


def _firm_party(firm: dict) -> dict:
    """The CA practice as a party — supplier of a FEE invoice, and nothing else."""
    return {
        "name": firm.get("name") or firm.get("firm_name") or "Chartered Accountants",
        "address": _address_lines(firm),
        "gstin": firm.get("gstin"),
        "pan": firm.get("pan"),
    }


def _client_party(client: dict, *, legal_name_first: bool = False) -> dict:
    """A `clients` row as a party — the recipient of a fee invoice, and the
    SUPPLIER of that client's own sales invoice.

    legal_name_first is set for the supplier: Rule 46(b) wants the name the GST
    registration is held in, which is `legal_name` where one is recorded. The
    recipient block keeps the display name it has always shown.
    """
    if legal_name_first:
        name = (client.get("legal_name") or client.get("client_name")
                or client.get("name") or "Client")
    else:
        name = client.get("client_name") or client.get("name") or "Client"
    return {
        "name": name,
        "address": _address_lines(client),
        "gstin": client.get("gstin"),
        "pan": client.get("pan"),
    }


def _customer_party(customer: dict) -> dict:
    """A `customers` row as a party — the recipient of a client's sales invoice."""
    return {
        "name": customer.get("name") or customer.get("client_name") or "Customer",
        "address": _address_lines(customer),
        "gstin": customer.get("gstin"),
        "pan": customer.get("pan"),
    }


def _party_lines(party: dict) -> list[str]:
    out = [f"<b>{party['name']}</b>"]
    out.extend(party["address"])
    if party.get("gstin"):
        out.append(f"GSTIN: {party['gstin']}")
    if party.get("pan"):
        out.append(f"PAN: {party['pan']}")
    return out


def _compute_tax_splits(
    invoice: dict, firm: dict, client: dict
) -> tuple[int, int, int, int, int]:
    """
    Resolve CGST/SGST/IGST paise from the invoice dict.

    Prefers stored per-head values (cgst_paise, sgst_paise, igst_paise) so
    B2C invoices (no customer GSTIN) render correctly — geography-based
    derivation would see client_state=None → intra_state=False → wrongly
    render IGST on an intra-state supply (CGST Act §8; CGST Rule 46).

    Falls back to GSTIN state-code comparison when no stored values are present.
    `firm` here is whichever party is the SUPPLIER of this document.

    Returns: (cgst_paise, sgst_paise, igst_paise, gst_paise, total_paise)
    """
    amount_paise = invoice.get("amount_paise", 0)
    stored_cgst = invoice.get("cgst_paise")
    stored_sgst = invoice.get("sgst_paise")
    stored_igst = invoice.get("igst_paise")

    if stored_cgst is not None or stored_sgst is not None or stored_igst is not None:
        cgst_paise = stored_cgst or 0
        sgst_paise = stored_sgst or 0
        igst_paise = stored_igst or 0
        gst_paise = cgst_paise + sgst_paise + igst_paise
        total_paise = invoice.get("total_paise") or (amount_paise + gst_paise)
    else:
        # Fallback: derive from GSTIN geography (Section 12, IGST Act 2017).
        gst_paise = invoice.get("gst_paise", 0)
        total_paise = invoice.get("total_paise", amount_paise + gst_paise)
        firm_state = _state_code(firm.get("gstin"))
        client_state = _state_code(client.get("gstin"))
        intra_state = firm_state is not None and firm_state == client_state
        if intra_state:
            cgst_paise = gst_paise // 2
            sgst_paise = gst_paise - cgst_paise
            igst_paise = 0
        else:
            cgst_paise = 0
            sgst_paise = 0
            igst_paise = gst_paise

    return cgst_paise, sgst_paise, igst_paise, gst_paise, total_paise


# ── The shared renderer ──────────────────────────────────────────────────────

# Fee invoice: description + SAC + taxable value, as it has always been.
# "Rs.", matching _DETAIL_HEADER below and for the same reason. This one was
# left with the glyph, so the SIMPLE invoice layout — the one used when a
# line breakdown is not shown — printed an unmapped box in its column head.
_PLAIN_HEADER = ["#", "Description", "SAC", "Taxable Value (Rs.)"]
_PLAIN_WIDTHS = [10 * mm, 95 * mm, 25 * mm, 50 * mm]
# Sales invoice: Rule 46(g)/(h)/(l) — HSN/SAC, quantity, unit, rate and the tax
# on each line, none of which the plain layout has room for.
#
# "Rs." and not "₹": the built-in Helvetica has no rupee glyph, and reportlab
# encodes U+20B9 to the WinAnsi byte for "n" — the fee invoice's own header has
# rendered "Taxable Value (n)" since it was written. Fixing that one needs an
# embedded font and would change the other document, so the new columns simply
# do not add three more of the same artefact.
_DETAIL_HEADER = ["#", "Description", "HSN/SAC", "Qty", "Unit",
                  "Rate (Rs.)", "Taxable Value (Rs.)", "GST Rate", "Tax (Rs.)"]
_DETAIL_WIDTHS = [7 * mm, 45 * mm, 19 * mm, 13 * mm, 12 * mm,
                  22 * mm, 26 * mm, 14 * mm, 22 * mm]


def _summary_row(n_cols: int, label: str, value: str) -> list:
    row = [""] * n_cols
    row[1] = label
    row[-1] = value
    return row


def summary_lines(invoice: dict, lines: list, amount_paise: int, gst_paise: int,
                  cgst_paise: int, sgst_paise: int, igst_paise: int,
                  total_paise: int) -> list[tuple[str, str]]:
    """The invoice's summary block, as (label, value) pairs.

    EXTRACTED SO IT CAN BE TESTED. What goes in this block is statutory — Rule
    46(l) governs the rate labels and CGST §15(3)(a) makes a discount's relief
    conditional on the invoice RECORDING it — and none of it was assertable
    while it was built inline into a reportlab Table: the rendered PDF writes
    text as positioned glyphs, so "is the discount line on the document" had no
    answer a test could give. It does now.
    """
    out: list[tuple[str, str]] = []

    # The invoice-level rate label. Never a constant — an "18%" label beside a
    # 5% amount breaches Rule 46(l) even though the amount itself is right.
    invoice_rate = _document_rate(lines, amount_paise, gst_paise)

    def _head_label(name: str, halved: bool) -> str:
        if invoice_rate is None:
            return name
        # CGST and SGST are each half of the rate (CGST Act §9(1) with the
        # corresponding SGST Act); IGST is the whole of it (IGST Act §5(1)).
        rate = invoice_rate // 2 if halved else invoice_rate
        return f"{name} @ {_pct_label(rate)}%"

    # CGST §15(3)(a): a discount is excluded from the value of supply only "if
    # such discount has been DULY RECORDED IN THE INVOICE". So the customer's
    # copy shows the gross and the deduction, and the taxable value is what is
    # left — the relief is conditional on these lines being here. Printing only
    # the net would satisfy the arithmetic and not the section.
    #
    # Shown only when there is one, so an ordinary invoice keeps the layout it
    # has always had.
    discount_paise = int(invoice.get("discount_paise", 0) or 0)
    if discount_paise:
        out.append(("Gross Value", _paise_to_rupee_str(amount_paise + discount_paise)))
        pct = invoice.get("discount_percent_bps")
        # _pct_label takes MILLI-percent (18000 = 18%), and discount_percent_bps
        # is basis points (500 = 5%) — x10, or a 5% discount prints as 0.5%.
        label = ("Less: Discount" if pct in (None, "")
                 else f"Less: Discount @ {_pct_label(int(pct) * 10)}%")
        out.append((label, f"-{_paise_to_rupee_str(discount_paise)}"))

    out.append(("Taxable Value", _paise_to_rupee_str(amount_paise)))
    if cgst_paise or sgst_paise:
        out.append((_head_label("CGST", True), _paise_to_rupee_str(cgst_paise)))
        out.append((_head_label("SGST", True), _paise_to_rupee_str(sgst_paise)))
    if igst_paise:
        out.append((_head_label("IGST", False), _paise_to_rupee_str(igst_paise)))

    # Invoice-level round-off line (nearest ₹1) — shown only when non-zero so the
    # taxable + GST rows still reconcile to the printed Total. CGST Act §15.
    round_off_paise = int(invoice.get("round_off_paise", 0) or 0)
    if round_off_paise:
        # _paise_to_rupee_str uses floor division, so format the sign explicitly
        # (a −30 paise round-off must render "-0.30", not "-1.70").
        _sign = "-" if round_off_paise < 0 else ""
        out.append(("Round Off", f"{_sign}{_paise_to_rupee_str(abs(round_off_paise))}"))

    out.append(("Total", _paise_to_rupee_str(total_paise)))
    return out


def _render_tax_invoice(
    invoice: dict,
    supplier: dict,
    recipient: dict,
    *,
    line_detail: bool,
    hsn_sac_fallback: Optional[str],
    fallback_line_label: Optional[str],
    report_gaps: bool,
    branding: Optional[dict] = None,
) -> bytes:
    """Render a Rule 46 tax invoice. `supplier` and `recipient` are already
    normalised party dicts — this function never decides who the supplier is.

    `branding` IS THE SUPPLIER'S OWN, and it is optional for a reason. The
    practice's logo, accent colour, bank account and footer belong on the
    practice's FEE invoice, where the practice is the supplier. They belong
    NOWHERE on a client's sales invoice: the CA is not a party to that supply,
    and putting their bank details on it would ask the client's customer to pay
    the accountant. That is the same confusion the supplier line, the customer
    statement and the payslip employer each had, so this argument is passed by
    build_invoice_pdf and deliberately not by build_sales_invoice_pdf.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Tax Invoice {invoice.get('invoice_no', '')}",
    )
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    bold = ParagraphStyle("bold", parent=styles["Normal"], fontName="Helvetica-Bold")
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=10)

    brand = branding or {}
    accent = _accent_colour(brand.get("primary_color"))

    story = []
    # The supplier's own logo, above their name. Fetched over the network, so
    # a slow or dead URL must not take the invoice down with it — see _logo.
    logo = _logo(brand.get("logo_url"))
    if logo is not None:
        story.append(logo)
        story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("TAX INVOICE", ParagraphStyle(
        "title", parent=styles["Title"], fontSize=16, spaceAfter=2,
        textColor=accent or colors.black)))
    story.append(Paragraph("(Issued under Section 31, CGST Act 2017 read with Rule 46, CGST Rules 2017)", small))
    if brand.get("tagline"):
        story.append(Paragraph(str(brand["tagline"]), small))
    story.append(Spacer(1, 6 * mm))

    meta_lines = [
        f"<b>Invoice No:</b> {invoice.get('invoice_no', '')}",
        f"<b>Invoice Date:</b> {str(invoice.get('invoice_date', ''))[:10]}",
    ]
    if invoice.get("due_date"):
        meta_lines.append(f"<b>Due Date:</b> {str(invoice['due_date'])[:10]}")
    meta_lines.append(f"<b>Status:</b> {invoice.get('status', '')}")
    # Rule 46(n): place of supply, with the name of the State, on an inter-State
    # supply. Printed whenever it is recorded; flagged below when it is not.
    place_of_supply = _place_of_supply_label(invoice.get("supply_state_code"))
    if place_of_supply:
        meta_lines.append(f"<b>Place of Supply:</b> {place_of_supply}")
    # Rule 46(r). Present only where the CA has recorded an IRN obtained from
    # the IRP — see _einvoice_particulars. Never simulated.
    if invoice.get("irn"):
        meta_lines.append(f"<b>IRN:</b> {invoice['irn']}")
        if invoice.get("ack_number"):
            ack = f"<b>Ack No:</b> {invoice['ack_number']}"
            if invoice.get("ack_date"):
                ack += f" &nbsp;<b>Ack Date:</b> {invoice['ack_date']}"
            meta_lines.append(ack)

    qr_drawing = _qr_flowable(invoice.get("qr_data"))
    header = Table(
        [[Paragraph("<br/>".join(_party_lines(supplier)), styles["Normal"]),
          Paragraph("<br/>".join(meta_lines), styles["Normal"]),
          qr_drawing or ""],
         [Paragraph("<b>Bill To:</b><br/>" + "<br/>".join(_party_lines(recipient)), styles["Normal"]), "", ""]],
        colWidths=[80 * mm, 68 * mm, 32 * mm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
    ]))
    story.append(header)
    story.append(Spacer(1, 6 * mm))

    amount_paise = invoice.get("amount_paise", 0)
    cgst_paise, sgst_paise, igst_paise, gst_paise, total_paise = _compute_tax_splits(
        invoice, supplier, recipient
    )

    lines = invoice.get("lines") or []
    gaps: list[str] = []
    missing_hsn: list[str] = []
    no_lines = False

    header_row = list(_DETAIL_HEADER if line_detail else _PLAIN_HEADER)
    widths = _DETAIL_WIDTHS if line_detail else _PLAIN_WIDTHS
    n_cols = len(header_row)
    rows: list[list] = [header_row]

    if lines:
        for i, line in enumerate(lines, start=1):
            # Rule 46(g): the HSN/SAC of THIS line. A missing code is reported,
            # never filled in with the practice's own SAC.
            hsn_sac = line.get("hsn_sac") or hsn_sac_fallback or ""
            if not hsn_sac:
                missing_hsn.append(str(i))
            description = Paragraph(line.get("description") or "", cell if line_detail else styles["Normal"])
            if not line_detail:
                rows.append([str(i), description, hsn_sac,
                             _paise_to_rupee_str(line.get("taxable_amount_paise", 0))])
                continue
            line_taxable = int(line.get("taxable_amount_paise", 0) or 0)
            line_tax = (int(line.get("cgst_paise", 0) or 0)
                        + int(line.get("sgst_paise", 0) or 0)
                        + int(line.get("igst_paise", 0) or 0))
            # Rule 46(l): the rate charged on this line — its stored rate where
            # there is one, otherwise the rate its own tax works out to.
            line_rate = _line_rate(line)
            rows.append([
                str(i),
                description,
                hsn_sac,
                _qty_label(line.get("quantity")),          # Rule 46(h): quantity
                str(line.get("unit") or ""),               # Rule 46(h): unit
                _paise_to_rupee_str(int(line.get("rate_paise", 0) or 0)),
                _paise_to_rupee_str(line_taxable),
                f"{_pct_label(line_rate)}%" if line_rate is not None else "",
                _paise_to_rupee_str(line_tax),
            ])
    else:
        # Legacy engagement-based fee invoices carry no line-items concept — a
        # single synthetic row describing the engagement is all there is. A
        # client's SALES invoice has no such row: describing somebody else's
        # sale as professional services is the same invention as stamping the
        # CA's SAC on it, so the row is blank and the absence is reported.
        row = _summary_row(n_cols, "", _paise_to_rupee_str(amount_paise))
        row[0] = "1"
        row[1] = Paragraph(fallback_line_label or "", cell if line_detail else styles["Normal"])
        row[2] = hsn_sac_fallback or ""
        if not row[2]:
            missing_hsn.append("1")
        if fallback_line_label is None:
            no_lines = True
        rows.append(row)

    summary_from = len(rows)
    for label, value in summary_lines(invoice, lines, amount_paise, gst_paise,
                                      cgst_paise, sgst_paise, igst_paise, total_paise):
        rows.append(_summary_row(n_cols, label, value))

    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (1, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if line_detail:
        style.append(("FONTSIZE", (0, 0), (-1, -1), 8))
        style.append(("ALIGN", (3, 1), (3, -1), "RIGHT"))    # Qty
        style.append(("ALIGN", (4, 1), (4, -1), "CENTER"))   # Unit
        style.append(("ALIGN", (5, 1), (7, -1), "RIGHT"))    # Rate, Taxable, GST rate
        for r in range(summary_from, len(rows)):
            style.append(("SPAN", (1, r), (-2, r)))

    table = Table(rows, colWidths=widths)
    table.setStyle(TableStyle(style))
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"<b>Amount in words:</b> {amount_in_words(total_paise)}", styles["Normal"]))
    story.append(Spacer(1, 10 * mm))
    # Rule 46(p): the reverse-charge statement is a fact about THIS supply
    # (CGST §9(3)/(4)), not a constant. client_sales_invoices.is_reverse_charge
    # carries it; a document that does not hold the flag reads as "No", which is
    # what it has always printed.
    reverse_charge = bool(invoice.get("is_reverse_charge"))
    story.append(Paragraph(
        f"Whether tax is payable on reverse charge basis: {'Yes' if reverse_charge else 'No'}",
        styles["Normal"]))

    if report_gaps:
        # Rule 46 particulars that are simply not held. Named, never guessed.
        if not supplier.get("gstin"):
            gaps.append(
                "Supplier GSTIN — Rule 46(b). An unregistered supplier may not issue a "
                "tax invoice at all (CGST §31(3)(c) read with Rule 49: a bill of supply).")
        if not supplier.get("address"):
            gaps.append("Supplier address — Rule 46(b).")
        if no_lines:
            gaps.append(
                "Line items — Rule 46(g)/(h)/(i): this invoice has no recorded lines, "
                "so it states only its total.")
        elif missing_hsn:
            gaps.append(f"HSN/SAC for line(s) {', '.join(missing_hsn)} — Rule 46(g).")
        # Inter-State is IGST on the face of it, or the invoice's own stored
        # flag — a zero-rated export under LUT carries no IGST and is still an
        # inter-State supply (IGST Act §7(5), §16).
        if (igst_paise or invoice.get("is_interstate")) and not place_of_supply:
            gaps.append("Place of supply — Rule 46(n) requires it on an inter-State supply.")
        if gaps:
            story.append(Spacer(1, 4 * mm))
            story.append(Paragraph(
                "<b>Not recorded</b> (required particulars this invoice does not hold):", small))
            for gap in gaps:
                story.append(Paragraph(f"• {gap}", small))

    # ─── How to pay the supplier ────────────────────────────────────────────
    #
    # NOT a Rule 46 particular — the rule says nothing about a bank account —
    # but it is the reason an invoice gets paid, and it is the supplier's own.
    # Rendered only where `branding` was passed, which is the fee invoice: the
    # practice's account on a client's sales invoice would ask the client's
    # customer to pay the accountant.
    pay_lines = []
    if brand.get("bank_name") or brand.get("account_number"):
        holder = brand.get("account_holder") or supplier.get("name") or ""
        if holder:
            pay_lines.append(f"<b>Account Name:</b> {holder}")
        if brand.get("bank_name"):
            pay_lines.append(f"<b>Bank:</b> {brand['bank_name']}")
        if brand.get("account_number"):
            pay_lines.append(f"<b>A/c No:</b> {brand['account_number']}")
        if brand.get("ifsc_code"):
            pay_lines.append(f"<b>IFSC:</b> {brand['ifsc_code']}")
    if brand.get("upi_id"):
        pay_lines.append(f"<b>UPI:</b> {brand['upi_id']}")
    if pay_lines:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Payment Details", bold))
        # An uploaded IMAGE, not QR data: _qr_flowable would ENCODE the URL,
        # and scanning that opens a web page instead of a payment.
        qr_img = _remote_image(brand.get("upi_qr_url"), max_width_mm=32, max_height_mm=32)
        block = Table(
            [[Paragraph("<br/>".join(pay_lines), styles["Normal"]), qr_img or ""]],
            colWidths=[135 * mm, 45 * mm],
        )
        block.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(block)

    story.append(Spacer(1, 14 * mm))
    # Rule 46(q): the signature is the SUPPLIER's.
    story.append(Paragraph(f"For {supplier['name']}", bold))
    story.append(Spacer(1, 14 * mm))
    story.append(Paragraph("Authorised Signatory", styles["Normal"]))

    if brand.get("footer_text"):
        story.append(Spacer(1, 8 * mm))
        story.append(Paragraph(str(brand["footer_text"]), small))

    doc.build(story)
    return buf.getvalue()


def build_invoice_pdf(invoice: dict, firm: dict, client: dict,
                      engagement: Optional[dict] = None,
                      branding: Optional[dict] = None) -> bytes:
    """Render the PRACTICE's own fee invoice: the firm supplies, the client
    receives. Do not use this for a client's sales invoice — see
    build_sales_invoice_pdf().

    `branding` is the FIRM's — logo, accent colour, tagline, bank account, UPI
    and footer, from firm_branding + invoice_settings. This is the document
    those settings were always for, and it is the only invoice they belong on.
    """
    label = "Professional Services — Chartered Accountancy"
    if engagement and engagement.get("service_type"):
        label = f"Professional Services — {engagement['service_type']}"
    return _render_tax_invoice(
        invoice,
        _firm_party(firm),
        _client_party(client),
        branding=branding,
        line_detail=False,
        # The practice's own supply genuinely is SAC 998211 (legal and
        # accounting services), so it remains this document's default.
        hsn_sac_fallback=SAC_CODE,
        fallback_line_label=label,
        # Unchanged document: the same particulars are missing here when they
        # are missing, and naming them belongs with a fix to THIS document.
        report_gaps=False,
    )


def build_sales_invoice_pdf(invoice: dict, client: dict, customer: dict) -> bytes:
    """Render a CLIENT's own sales invoice: the client supplies, the client's
    customer receives. The CA practice is not a party to this supply and appears
    nowhere on it.

    NO `branding` ARGUMENT, DELIBERATELY. firm_branding and invoice_settings are
    the PRACTICE's, and the practice's logo, bank account and UPI on this
    document would ask the client's customer to pay the accountant. It is the
    same confusion the supplier line, the customer statement and the payslip
    employer each had. A client's own branding would be a different store —
    `clients` has no logo, bank, UPI or footer column at all — and adding one is
    a migration, not a wiring job.
    """
    return _render_tax_invoice(
        invoice,
        _client_party(client, legal_name_first=True),
        _customer_party(customer),
        line_detail=True,
        # Rule 46(g) is about what the CLIENT sold. There is no sensible default
        # for that, so a line with no code prints none and is reported instead.
        hsn_sac_fallback=None,
        fallback_line_label=None,
        report_gaps=True,
    )


def get_invoice_pdf(invoice_id: str) -> tuple[bytes, str]:
    """
    Load a FEE invoice with its firm, client and engagement records and render
    the PDF. The supplier is the practice.

    Returns:
        (pdf_bytes, suggested_filename)
    """
    from repositories.invoice_repository import invoice_repo
    from repositories.client_repository import client_repo

    invoice = invoice_repo.find_by_id_or_raise(invoice_id)

    client = {}
    try:
        client = client_repo.find_by_id(invoice.get("client_id")) or {}
    except Exception as e:
        logger.warning(f"Could not load client for invoice {invoice_id}: {e}")

    firm = _load_firm(invoice.get("firm_id"))

    engagement = None
    if invoice.get("engagement_id"):
        try:
            from repositories.engagement_repository import engagement_repo
            engagement = engagement_repo.find_by_id(invoice["engagement_id"])
        except Exception:
            engagement = None

    pdf = build_invoice_pdf(invoice, firm, client, engagement,
                            branding=_load_branding(invoice.get("firm_id")))
    filename = f"invoice-{invoice.get('invoice_no', invoice_id)}.pdf"
    return pdf, filename


def _load_branding(firm_id: Optional[str]) -> dict:
    """The firm's own branding and payment details, as one dict.

    TWO ROWS, ONE ARGUMENT. `firm_branding` holds the look (logo, colours,
    tagline) and `invoice_settings` holds how to pay (bank, IFSC, UPI, footer);
    they are separate tables because they are edited on separate screens, and
    the renderer has no reason to know that.

    A full Settings UI has written both of these since the module existed and
    NOTHING EVER READ THEM: `grep -rn "branding" apps/api/services apps/api/
    routers apps/api/domain` returned only routers/branding.py itself. A CA
    could upload a logo, set an accent colour, record their bank account and
    write a footer, and every invoice came out with a fixed #1f2937 header and
    no way to be paid.

    Returns {} on any failure, and that is the rule for this whole feature: a
    tax invoice that renders without a logo is valid under Rule 46; one that
    does not render is not.
    """
    if not firm_id:
        return {}
    out: dict = {}
    try:
        from repositories.branding_repository import branding_repo
        out.update(branding_repo.get_branding(firm_id) or {})
        out.update(branding_repo.get_invoice_settings(firm_id) or {})
    except Exception:                       # noqa: BLE001 — see the docstring
        logger.warning("caflow.invoice_pdf: could not load branding for firm %s", firm_id)
        return {}
    return out


def _load_firm(firm_id: Optional[str]) -> dict:
    if not firm_id:
        return {}
    try:
        from core.supabase_client import get_supabase
        result = get_supabase().table("firms").select("*").eq("id", firm_id).maybe_single().execute()
        return result.data or {}
    except Exception as e:
        logger.warning(f"Could not load firm {firm_id}: {e}")
        return {}


# The supplier's own particulars (Rule 46(a)/(b)). legal_name is the name the
# GST registration is held in; state_code backs the place-of-supply label.
_SUPPLIER_COLUMNS = (
    "id,client_name,legal_name,trade_name,gstin,pan,"
    "address_line1,address_line2,city,state,pincode,state_code"
)


def _einvoice_record_for(db, firm_id: str, invoice_id: str) -> Optional[dict]:
    """The e-invoice record for this invoice, or None.

    Firm-scoped like every other query here. A failure to read is None rather
    than an exception: a PDF that will not render is worse than one without the
    Rule 46(r) block, and the CA can see the IRN on the e-invoice screen either
    way.
    """
    try:
        res = (db.table("einvoice_records")
               .select("irn, ack_number, ack_date, qr_data, status")
               .eq("firm_id", firm_id).eq("sales_invoice_id", invoice_id)
               .limit(1).execute())
        return (getattr(res, "data", None) or [None])[0]
    except Exception:                       # pragma: no cover - defensive
        logger.warning("caflow.invoice_pdf: could not read einvoice_records for %s",
                       invoice_id)
        return None


def get_sales_invoice_pdf(invoice_id: str, firm_id: str) -> tuple[bytes, str]:
    """
    Load a client_sales_invoice and render the client's own GST tax invoice.

    The SUPPLIER is the `clients` row that raised the invoice, not the CA firm:
    this is the client's sale to the client's customer, and the practice is not
    a party to it. (On the client-portal path the invoice's client_id is the
    firm's own internal practice client — migration 074 — so the same lookup
    correctly renders the practice there, from its own clients row.)

    Normalises the column names from client_sales_invoices
    (taxable_amount_paise) to the keys the renderer expects (amount_paise), and
    passes the stored tax heads and per-line rows through unchanged.

    Returns (pdf_bytes, suggested_filename).
    """
    from core.supabase_client import get_supabase
    db = get_supabase()
    row = (
        db.table("client_sales_invoices")
        .select("*, customers(id,name,gstin,pan,address,state_code,city,state,pincode)")
        .eq("id", invoice_id)
        .eq("firm_id", firm_id)
        .maybe_single()
        .execute()
    )
    if not row.data:
        raise ValueError(f"Invoice {invoice_id} not found for firm {firm_id}")
    data = row.data
    customer = data.get("customers") or {}
    # The selling client — firm-scoped, like every other query in this codebase.
    client_row = (
        db.table("clients")
        .select(_SUPPLIER_COLUMNS)
        .eq("id", data.get("client_id"))
        .eq("firm_id", firm_id)
        .maybe_single()
        .execute()
    )
    client = getattr(client_row, "data", None) or {}
    if not client:
        # Refuse rather than fall back to the firm: a tax invoice naming the
        # wrong supplier is worse than no PDF — the recipient cannot match the
        # credit in GSTR-2B and claims it against a GSTIN that made no supply.
        raise ValueError(
            f"Supplier record not found for invoice {invoice_id} — a tax invoice "
            "cannot be issued without the supplier's own particulars (Rule 46(b))."
        )
    lines_resp = (
        db.table("client_sales_invoice_lines")
        .select("*")
        .eq("sales_invoice_id", invoice_id)
        .order("sort_order")
        .execute()
    )
    invoice_dict = {
        "invoice_no":   data["invoice_no"],
        "invoice_date": data["invoice_date"],
        "due_date":     data.get("due_date"),
        "status":       data["status"],
        "amount_paise": data.get("taxable_amount_paise", 0),
        # Pass stored tax heads directly — _compute_tax_splits() uses these to
        # render correct CGST/SGST/IGST lines without re-deriving from geography.
        "cgst_paise":   data.get("cgst_paise", 0),
        "sgst_paise":   data.get("sgst_paise", 0),
        "igst_paise":   data.get("igst_paise", 0),
        "round_off_paise": data.get("round_off_paise", 0),
        "total_paise":  data.get("total_paise", 0),
        # Rule 46(n) and 46(p) — all three are facts stored on the invoice
        # (migrations 050 and 268), none of them a constant.
        "supply_state_code": data.get("supply_state_code"),
        "is_interstate": data.get("is_interstate"),
        "is_reverse_charge": data.get("is_reverse_charge"),
        "lines":        lines_resp.data or [],
        # Rule 46(r) — the IRN and the IRP's own signed QR, where the CA has
        # recorded one. einvoice_records is read here rather than joined above
        # because a missing record is the normal case (e-invoicing applies by
        # turnover) and must not cost the invoice its PDF.
        **_einvoice_particulars(_einvoice_record_for(db, firm_id, invoice_id)),
    }
    pdf = build_sales_invoice_pdf(invoice_dict, client, customer)
    filename = f"invoice-{data.get('invoice_no', invoice_id)}.pdf"
    return pdf, filename
