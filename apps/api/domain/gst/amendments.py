"""
GSTR-1 amendment tables — declaring a correction to a return already filed.

THE RULE
    CGST Act §37: a filed GSTR-1 cannot be revised. A mistake in it is corrected
    by declaring an amended entry in a LATER period's return, in that return's
    amendment tables. The original entry stays as filed, for ever; the amendment
    supersedes it.

    Every amended entry therefore has to carry the identity of the entry it
    replaces — the ORIGINAL document number and date, or for B2C-others the
    original month. Without that, GSTN has nothing to match the amendment
    against and rejects it.

WHICH TABLES THIS BUILDS
    9A  b2ba   amended B2B invoices
        b2cla  amended B2CL invoices
        expa   amended export invoices
    9C  cdnra  amended credit/debit notes to registered persons
        cdnura amended credit/debit notes to unregistered persons
    10  b2csa  amended B2C-others, at the (month, rate, place of supply) grain
               that table 7 declares and no finer

WHICH IT DOES NOT
    Table 11 is advances received and adjusted (`at` / `txpd`). It is not an
    amendment table at all — it reports advance money against which no invoice
    has yet been raised, sourced from receipts rather than from any correction.
    Building it is a separate feature with a separate data source.

    Table 9B (cdnr / cdnur) is the ORIGINAL credit/debit note table, and
    gstr1_builder.py already produces it.

THE CASE THAT IS NOT AN AMENDMENT AT ALL
    An invoice dated inside a filed period but raised after that period was
    filed was never declared. There is nothing to amend — 9A supersedes an
    entry, and no entry exists. It is declared in the CURRENT period's ORDINARY
    table, carrying its own original date.

    That matters more than it sounds: gstr1_from_books selects by date range, so
    such an invoice falls outside the current period's window too. Left to the
    ordinary machinery it would be declared in no return, ever. It has to be
    carried forward deliberately, which is what `missed_documents` does.

NOTHING HERE DECIDES ANYTHING
    A cancellation after filing has no single correct treatment — amend the
    entry to nil, or raise a credit note — and the choice changes what the
    client owes. Those are surfaced as needing a decision rather than resolved.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
"""
from __future__ import annotations

from typing import Any, Optional

from domain.gst.money import paise_to_rupees_2dp as _rupees

# Which amendment section corrects which original table.
_AMEND_SECTION = {
    "b2b": "b2ba",
    "b2cl": "b2cla",
    "exp": "expa",
    "cdnr": "cdnra",
    "cdnur": "cdnura",
}

# The GSTR-1 table number each section belongs to, for the CA reading the
# proposal rather than the JSON.
SECTION_TABLE = {
    "b2ba": "9A", "b2cla": "9A", "expa": "9A",
    "cdnra": "9C", "cdnura": "9C",
    "b2csa": "10",
}

_HEADS = ("taxable_paise", "cgst_paise", "sgst_paise", "igst_paise", "cess_paise")


def amendment_section_for(original_section: str) -> Optional[str]:
    """The amendment table that corrects an entry originally filed in `section`."""
    return _AMEND_SECTION.get(original_section)


def _gstn_date(iso_or_gstn: str) -> str:
    """Dates in a payload are already DD-MM-YYYY; an ISO date is converted.

    Amendments are built from two sources — a frozen payload (GSTN format) and
    the books (ISO) — and sending the wrong one is the kind of error GSTN
    rejects the whole return for.
    """
    s = str(iso_or_gstn or "").strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return f"{s[8:10]}-{s[5:7]}-{s[0:4]}"
    return s


def _items(amounts: dict, rate: Any = None) -> list[dict]:
    """One itm_det carrying the corrected figures.

    The amendment declares the document's corrected totals; the per-rate split
    is rebuilt from the document itself when it has one, so a single group here
    is the honest shape for a header-level correction.
    """
    return [{"num": 1, "itm_det": {
        "txval": _rupees(int(amounts.get("taxable_paise", 0))),
        "rt": rate if rate is not None else 0.0,
        "iamt": _rupees(int(amounts.get("igst_paise", 0))),
        "camt": _rupees(int(amounts.get("cgst_paise", 0))),
        "samt": _rupees(int(amounts.get("sgst_paise", 0))),
        "csamt": _rupees(int(amounts.get("cess_paise", 0))),
    }}]


def _doc_value(amounts: dict) -> float:
    total = sum(int(amounts.get(h, 0)) for h in _HEADS)
    return _rupees(total)


def build_invoice_amendment(
    *, original_no: str, original_date: str, section: str,
    corrected: dict, counterparty: str = "", doc_no: Optional[str] = None,
    doc_date: Optional[str] = None, place_of_supply: str = "",
    reverse_charge: bool = False, invoice_type: str = "R", rate: Any = None,
) -> dict:
    """One amended invoice entry, for b2ba / b2cla / expa.

    `oinum` / `oidt` identify the entry being superseded and are what GSTN
    matches on. They are the ORIGINAL values even when the correction changed
    the invoice number itself — which is precisely the case where getting this
    wrong silently creates a second invoice instead of amending the first.
    """
    node = {
        "oinum": original_no,
        "oidt": _gstn_date(original_date),
        "inum": doc_no or original_no,
        "idt": _gstn_date(doc_date or original_date),
        "val": _doc_value(corrected),
        "itms": _items(corrected, rate),
    }
    if section == "b2ba":
        node.update({"pos": place_of_supply, "rchrg": "Y" if reverse_charge else "N",
                     "inv_typ": invoice_type})
    elif section == "expa":
        node.update({"sbpcode": "", "sbnum": "", "sbdt": ""})
    return node


def build_note_amendment(
    *, original_no: str, original_date: str, note_type: str = "C",
    corrected: dict, doc_no: Optional[str] = None, doc_date: Optional[str] = None,
    place_of_supply: str = "", reverse_charge: bool = False,
    unregistered_type: Optional[str] = None, rate: Any = None,
) -> dict:
    """One amended credit/debit note, for cdnra / cdnura.

    Notes use ont_num / ont_dt for the original reference rather than
    oinum / oidt — a different key for the same idea, and one GSTN will not
    accept the other spelling of.
    """
    node = {
        "ntty": note_type,
        "ont_num": original_no,
        "ont_dt": _gstn_date(original_date),
        "nt_num": doc_no or original_no,
        "nt_dt": _gstn_date(doc_date or original_date),
        "val": _doc_value(corrected),
        "pos": place_of_supply,
        "itms": _items(corrected, rate),
    }
    if unregistered_type:
        node["typ"] = unregistered_type
    else:
        node["rchrg"] = "Y" if reverse_charge else "N"
    return node


def build_b2cs_amendment(
    *, original_month: str, supply_type: str, rate: Any,
    place_of_supply: str, corrected: dict,
) -> dict:
    """One amended B2C-others row, for b2csa.

    `omon` is the month whose figures are being corrected. B2C-others carries no
    document number in table 7, so the month, rate and place of supply ARE the
    identity — the same grain the original was declared at, and the finest a
    correction can be made at.
    """
    return {
        "omon": original_month,
        "sply_ty": supply_type,
        "rt": rate,
        "pos": place_of_supply,
        "txval": _rupees(int(corrected.get("taxable_paise", 0))),
        "iamt": _rupees(int(corrected.get("igst_paise", 0))),
        "camt": _rupees(int(corrected.get("cgst_paise", 0))),
        "samt": _rupees(int(corrected.get("sgst_paise", 0))),
        "csamt": _rupees(int(corrected.get("cess_paise", 0))),
    }


def group_amendments(entries: list[dict]) -> dict:
    """Amendment nodes into the grouped sections GSTN expects.

    b2ba and cdnra group by counterparty GSTIN, b2cla by place of supply, expa
    by export type; cdnura and b2csa are flat. Getting the grouping wrong is not
    cosmetic — GSTN validates the shape and rejects the return.

    `entries` are {section, group, node} triples so the grouping rule lives here
    once rather than at each call site.
    """
    grouped: dict[str, Any] = {}
    for entry in entries:
        section = entry["section"]
        node = entry["node"]

        if section in ("cdnura", "b2csa"):
            grouped.setdefault(section, []).append(node)
            continue

        group_value = entry.get("group") or ""
        buckets = grouped.setdefault(section, [])
        list_key = "nt" if section == "cdnra" else "inv"
        group_key = {"b2ba": "ctin", "cdnra": "ctin",
                     "b2cla": "pos", "expa": "exp_typ"}[section]

        for bucket in buckets:
            if bucket.get(group_key) == group_value:
                bucket[list_key].append(node)
                break
        else:
            buckets.append({group_key: group_value, list_key: [node]})

    return grouped


def merge_into_payload(payload: dict, amendment_sections: dict) -> dict:
    """Fold amendment sections into a period's GSTR-1 payload.

    Returns a new dict rather than mutating: the caller usually still needs the
    un-amended payload to show the CA what changed, and a payload that quietly
    grew extra tables is a hard thing to reason about.

    An empty section is omitted entirely. GSTN treats a present-but-empty
    amendment table as a declaration that there are no amendments, which is a
    different statement from not amending anything, and some validators reject
    it outright.
    """
    out = dict(payload or {})
    for section, rows in (amendment_sections or {}).items():
        if rows:
            out[section] = rows
    return out
