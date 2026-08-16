"""
What the books say now, against what the return actually said.

THE PROBLEM THIS SOLVES
    A GSTR-1 is filed. Then somebody edits an invoice in that period, or raises
    one they forgot, or cancels one. The books move; the filed return cannot.
    Nothing then connects the two, and the difference is invisible until a
    notice arrives or the annual return refuses to reconcile.

    India gives no way to revise a filed GSTR-1 (CGST Act §37). The only route
    is to declare the correction in a LATER period's amendment tables. So the
    job here is not to fix anything — it is to find the drift and name the table
    it has to be declared in.

WHY IT COMPARES PAYLOADS RATHER THAN INVOICES
    The frozen side is `gstr1_returns.payload_json`: the GSTN JSON as at
    submission. That is the only record of what was filed, so it is the only
    honest thing to compare against. Re-deriving "what we would have filed" from
    today's invoices would compare the books to themselves.

TWO SHAPES, DELIBERATELY TREATED DIFFERENTLY
    Most tables identify documents: b2b, b2cl, exp carry `inum`; cdnr and cdnur
    carry `nt_num`. Those are compared document by document.

    b2cs does not. GSTR-1 reports B2C-others as totals grouped by supply type,
    rate and place of supply — an invoice number never appears. A per-invoice
    diff there is not merely hard, it is meaningless, and amendment table 10
    amends B2CS at exactly that same aggregate grain. So b2cs is compared as
    aggregate rows, and the report says so rather than pretending otherwise.

MONEY
    The payload holds rupees to two decimals; everything here converts back to
    integer paise before any arithmetic, and every figure reported is paise
    (CLAUDE.md). Both sides go through the same conversion, so a rounding quirk
    cannot masquerade as a difference.

IT REPORTS. IT CHANGES NOTHING.
    No amendment is drafted, no invoice is touched, no return is altered. The
    figures go in front of the CA, who decides — the same posture as everything
    else here that would move a filed number.
"""
from __future__ import annotations

from typing import Any, Optional

# ── Where a correction has to be declared (CGST Act §37) ─────────────────────
# GSTR-1's own amendment tables. A CA reads these numbers, so they are the
# labels rather than our own vocabulary.
AMEND_INVOICE = "9A"   # amended B2B / B2CL / export invoices (tables 4, 5, 6)
AMEND_NOTE = "9C"      # amended credit / debit notes (table 9B originals)
AMEND_B2CS = "10"      # amended B2C others (table 7 originals)

# A document that was never filed at all is not an amendment of anything. It is
# declared in the CURRENT period's ordinary table — amending table 9A would be
# amending an entry that does not exist.
DECLARE_CURRENT = "current period"

# Sections that identify individual documents, and the keys they use.
_INVOICE_SECTIONS = {
    # section: (group key holding the list, document-number field)
    "b2b": ("inv", "inum"),
    "b2cl": ("inv", "inum"),
    "exp": ("inv", "inum"),
    "cdnr": ("nt", "nt_num"),
}
# cdnur is flat — the notes are not grouped by counterparty.
_FLAT_NOTE_SECTION = "cdnur"

_HEADS = ("taxable_paise", "cgst_paise", "sgst_paise", "igst_paise", "cess_paise")


def rupees_to_paise(value: Any) -> int:
    """Rupees (as the payload stores them) back to integer paise.

    domain/gst/money.paise_to_rupees_2dp writes round(paise / 100, 2), so this
    is its inverse.

    round() rather than int(), and the difference is real rather than
    theoretical: 8.29 * 100 is 828.9999999999999 in binary floating point, so
    int() returns 828 and silently loses a paisa on a figure that was exact
    going in. Which rupee values do this is not guessable — 1234.56 * 100 is
    exactly 123456.0 — so the test pins one that genuinely truncates.
    """
    if value is None:
        return 0
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return 0


def _item_totals(itms: Any) -> dict:
    """Sum a document's `itms` array into integer paise, head by head.

    GSTR-1 splits a document into one itm_det per GST rate, so the document's
    own figures are the sum across rates. Reading the header `val` instead would
    fold tax and round-off into one number and lose the per-head split that
    GSTR-3B table 3.1 and every amendment needs.
    """
    out = {h: 0 for h in _HEADS}
    for item in itms or []:
        det = (item or {}).get("itm_det") or {}
        out["taxable_paise"] += rupees_to_paise(det.get("txval"))
        out["cgst_paise"] += rupees_to_paise(det.get("camt"))
        out["sgst_paise"] += rupees_to_paise(det.get("samt"))
        out["igst_paise"] += rupees_to_paise(det.get("iamt"))
        out["cess_paise"] += rupees_to_paise(det.get("csamt"))
    return out


def _doc_key(kind: str, doc_no: Any) -> str:
    """Identity of a document across the two payloads.

    Keyed by kind as well as number because an invoice and a credit note may
    legitimately share a serial — they are separate series (CGST Rule 46 / 53) —
    and colliding them would report a phantom change on both.
    """
    return f"{kind}:{str(doc_no or '').strip().upper()}"


def index_documents(payload: Optional[dict]) -> dict:
    """Every document-identified entry in a GSTR-1 payload, by key.

    Used on BOTH the filed payload and the from-books one, so any quirk of this
    parsing applies identically to each side and cannot show up as drift.
    """
    out: dict = {}
    payload = payload or {}

    for section, (list_key, num_key) in _INVOICE_SECTIONS.items():
        kind = "note" if section == "cdnr" else "invoice"
        for group in payload.get(section) or []:
            group = group or {}
            # The group header carries the counterparty: GSTIN for b2b/cdnr,
            # place of supply for b2cl, with/without payment for exports.
            counterparty = group.get("ctin") or group.get("pos") or group.get("exp_typ") or ""
            for doc in group.get(list_key) or []:
                doc = doc or {}
                out[_doc_key(kind, doc.get(num_key))] = {
                    "kind": kind,
                    "doc_no": str(doc.get(num_key) or "").strip(),
                    "doc_date": doc.get("idt") or doc.get("nt_dt") or "",
                    "section": section,
                    "counterparty": counterparty,
                    **_item_totals(doc.get("itms")),
                }

    for doc in payload.get(_FLAT_NOTE_SECTION) or []:
        doc = doc or {}
        out[_doc_key("note", doc.get("nt_num"))] = {
            "kind": "note",
            "doc_no": str(doc.get("nt_num") or "").strip(),
            "doc_date": doc.get("nt_dt") or "",
            "section": _FLAT_NOTE_SECTION,
            "counterparty": doc.get("pos") or "",
            **_item_totals(doc.get("itms")),
        }

    return out


def index_b2cs(payload: Optional[dict]) -> dict:
    """B2C-others rows, keyed the way GSTR-1 itself groups them.

    (supply type, rate, place of supply) — no document number exists in this
    table, so this is the finest grain the return has and therefore the finest
    grain a correction can be declared at (amendment table 10).
    """
    out: dict = {}
    for row in (payload or {}).get("b2cs") or []:
        row = row or {}
        key = f"{row.get('sply_tp') or ''}|{row.get('rt')}|{row.get('pos') or ''}"
        bucket = out.setdefault(key, {
            "supply_type": row.get("sply_tp") or "",
            "rate": row.get("rt"),
            "place_of_supply": row.get("pos") or "",
            **{h: 0 for h in _HEADS},
        })
        bucket["taxable_paise"] += rupees_to_paise(row.get("txval"))
        bucket["cgst_paise"] += rupees_to_paise(row.get("camt"))
        bucket["sgst_paise"] += rupees_to_paise(row.get("samt"))
        bucket["igst_paise"] += rupees_to_paise(row.get("iamt"))
        bucket["cess_paise"] += rupees_to_paise(row.get("csamt"))
    return out


def _delta(books: dict, filed: dict) -> dict:
    """books minus filed, per head. Positive = the books now carry more."""
    return {h: int(books.get(h, 0)) - int(filed.get(h, 0)) for h in _HEADS}


def _is_zero(amounts: dict) -> bool:
    return all(int(amounts.get(h, 0)) == 0 for h in _HEADS)


def _totals(index: dict) -> dict:
    out = {h: 0 for h in _HEADS}
    for entry in index.values():
        for h in _HEADS:
            out[h] += int(entry.get(h, 0))
    return out


def _amendment_table(kind: str) -> str:
    return AMEND_NOTE if kind == "note" else AMEND_INVOICE


def compare_payloads(filed: Optional[dict], books: Optional[dict]) -> dict:
    """Everything that has moved since the return was filed.

    Four kinds of finding, because they need four different actions:

      * missing_from_return — in the books, never filed. Declared in the CURRENT
        period's ordinary table; there is no filed entry to amend.
      * missing_from_books  — filed, and no longer in the books. The most serious
        of the four: a document was deleted or cancelled after it was declared,
        and a filed return cannot simply drop it.
      * amount_changed      — filed and still present, with different figures.
      * reclassified        — filed and still present, but now belongs to a
        different GSTR-1 table (an SEZ supply that was declared B2B, say).
        Amending the value alone would leave it in the wrong table.
    """
    filed_docs = index_documents(filed)
    books_docs = index_documents(books)

    missing_from_return: list[dict] = []
    missing_from_books: list[dict] = []
    amount_changed: list[dict] = []
    reclassified: list[dict] = []

    for key, doc in books_docs.items():
        if key not in filed_docs:
            missing_from_return.append({**doc, "declare_in": DECLARE_CURRENT})

    for key, was in filed_docs.items():
        now = books_docs.get(key)
        if now is None:
            missing_from_books.append({**was, "declare_in": _amendment_table(was["kind"])})
            continue

        if now["section"] != was["section"]:
            reclassified.append({
                "doc_no": was["doc_no"], "kind": was["kind"],
                "filed_section": was["section"], "books_section": now["section"],
                "delta": _delta(now, was),
                "declare_in": _amendment_table(was["kind"]),
            })
            # A reclassified document is reported once, under the heading that
            # describes the bigger problem. Listing it again under
            # amount_changed would double-count it in any total.
            continue

        delta = _delta(now, was)
        if not _is_zero(delta):
            amount_changed.append({
                "doc_no": was["doc_no"], "kind": was["kind"],
                "section": was["section"], "counterparty": was["counterparty"],
                "doc_date": was["doc_date"],
                "filed": {h: was[h] for h in _HEADS},
                "books": {h: now[h] for h in _HEADS},
                "delta": delta,
                "declare_in": _amendment_table(was["kind"]),
            })

    # B2CS, at the only grain it has.
    filed_b2cs = index_b2cs(filed)
    books_b2cs = index_b2cs(books)
    b2cs_changed: list[dict] = []
    for key in sorted(set(filed_b2cs) | set(books_b2cs)):
        was = filed_b2cs.get(key, {})
        now = books_b2cs.get(key, {})
        delta = _delta(now, was)
        if _is_zero(delta):
            continue
        shape = now or was
        b2cs_changed.append({
            "supply_type": shape.get("supply_type", ""),
            "rate": shape.get("rate"),
            "place_of_supply": shape.get("place_of_supply", ""),
            "filed": {h: int(was.get(h, 0)) for h in _HEADS},
            "books": {h: int(now.get(h, 0)) for h in _HEADS},
            "delta": delta,
            "declare_in": AMEND_B2CS,
        })

    # Longest-standing readability rule from the Rule 37 report: biggest money
    # first, because that is what the CA acts on.
    def _size(f: dict) -> int:
        d = f.get("delta") or {h: f.get(h, 0) for h in _HEADS}
        return sum(abs(int(v)) for v in d.values())

    for bucket in (missing_from_return, missing_from_books, amount_changed, reclassified, b2cs_changed):
        bucket.sort(key=lambda f: (-_size(f), str(f.get("doc_no") or f.get("place_of_supply") or "")))

    filed_totals = _totals(filed_docs)
    books_totals = _totals(books_docs)
    for h in _HEADS:
        filed_totals[h] += sum(int(r["filed"][h]) for r in b2cs_changed)
        books_totals[h] += sum(int(r["books"][h]) for r in b2cs_changed)

    findings = (len(missing_from_return) + len(missing_from_books)
                + len(amount_changed) + len(reclassified) + len(b2cs_changed))

    return {
        "clean": findings == 0,
        "finding_count": findings,
        "documents": {
            "missing_from_return": missing_from_return,
            "missing_from_books": missing_from_books,
            "amount_changed": amount_changed,
            "reclassified": reclassified,
        },
        # Named rather than folded in with the documents, so nobody reads an
        # empty per-document list as "B2CS is unchanged".
        "b2cs": {
            "changed": b2cs_changed,
            "note": "GSTR-1 reports B2C-others as totals by supply type, rate and "
                    "place of supply. No invoice number is declared, so a change "
                    "can only be shown at that grain — which is also the grain "
                    "amendment table 10 corrects it at.",
        },
        "totals": {
            "filed": filed_totals,
            "books": books_totals,
            "delta": _delta(books_totals, filed_totals),
        },
        "rule": "CGST Act §37 — a filed GSTR-1 cannot be revised; corrections are "
                "declared in a later period's amendment tables.",
        # CA REVIEW REQUIRED — this reports drift. It drafts no amendment and
        # changes nothing.
        "ca_review_required": True,
    }
