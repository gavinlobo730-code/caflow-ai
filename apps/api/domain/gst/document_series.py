"""
GSTR-1 Table 13 — the documents a client ISSUED, as ranges (GST-18).

WHAT WAS WRONG
    `_build_doc_summary` emitted, per nature,

        {"num": count, "cancel": 0, "net_issue": count}

    and three of those four are wrong.

      * `num` is the ROW's index within the nature — Table 13 allows several
        ranges per nature and numbers them 1, 2, 3 — not a count of documents.
        `totnum` is the count, and `grep totnum apps/api` was empty.
      * `from` and `to` were absent entirely. They are the point of the table:
        it declares the SERIAL RANGE issued, which is how CGST Rule 46(b)'s
        "consecutive serial number ... unique for a financial year" is checked
        against the invoices actually filed.
      * `cancel` was a literal 0 for every client and every period, so
        `net_issue` was always the whole count. A cancelled invoice is exactly
        what this table exists to declare — the number was consumed and no
        supply was made under it.

ONE ROW PER CONTIGUOUS RUN, AND THAT IS WHAT MAKES THE FIGURES AGREE
    Rule 46(b) expressly allows "one or multiple series". A client running
    INV/2026-27/nnn beside EXP/2026-27/nnn in one month has two ranges, and a
    single row spanning the lowest to the highest number would contain
    documents from neither series and a `totnum` that does not match its own
    span.

    So documents are grouped by SERIES HEAD (`invoice_series.split_number`, the
    same split the numbering suggestion and the sequence-break warning use) and
    then by contiguous run inside it. `totnum == to - from + 1` is then an
    INVARIANT rather than a hope, and a gap in the middle becomes two rows —
    which is what Table 13's several-rows-per-nature shape is for, and is
    honest about a number nobody issued.

A NUMBER WITH NO TRAILING DIGIT IS ITS OWN RANGE OF ONE
    `split_number` answers `None` for a sequence it cannot read. Such a
    document still has to be declared, and `from == to == the number itself`
    with `totnum == 1` says exactly what happened without inventing a position
    in anybody's series.

CANCELLED DOCUMENTS ARE AN INPUT, NOT A DERIVATION
    They cannot come from the posted-and-issued documents the builder is given
    — that is the whole reason `cancel` was hard-coded. The caller supplies
    them, and a caller that supplies none gets `cancel = 0` with the return
    NAMING that nobody looked, rather than declaring a confident nil.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .invoice_series import split_number


@dataclass(frozen=True)
class IssuedDocument:
    """One document, for Table 13 only."""

    number: str
    #: True where the document was issued and then cancelled. The number was
    #: consumed and no supply was made under it, which is what the table asks.
    is_cancelled: bool = False


def _runs(seqs: Sequence[int]) -> list[tuple[int, int]]:
    """Contiguous runs of sorted, de-duplicated sequence numbers."""
    out: list[tuple[int, int]] = []
    for n in seqs:
        if out and n == out[-1][1] + 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out


def ranges_for(documents: Iterable[IssuedDocument]) -> list[dict]:
    """Table 13's `docs` rows for ONE nature, numbered from 1.

    Each row carries from/to/totnum/cancel/net_issue, and `totnum` is always
    `to - from + 1` for a numbered series because the rows ARE the contiguous
    runs. `num` is the row's own position, which is what the form means by it.
    """
    # head -> {sequence: (the number AS WRITTEN, cancelled)}. The written form
    # is carried rather than rebuilt from head + str(seq): a series padded to
    # four digits writes 0007, and rejoining would declare a number that
    # appears on no document.
    numbered: dict[str, dict[int, tuple[str, bool]]] = {}
    unnumbered: list[IssuedDocument] = []
    for d in documents:
        head, seq = split_number(d.number)
        if seq is None:
            unnumbered.append(d)
            continue
        # A number repeated inside one period is a real conflict the CA has to
        # resolve (migration 151's per-client uniqueness), not this table's to
        # hide — so a cancelled duplicate keeps the cancellation rather than
        # being overwritten by whichever row happened to come second.
        prior = numbered.setdefault(head, {}).get(seq)
        numbered[head][seq] = (d.number.strip(),
                               bool(prior and prior[1]) or d.is_cancelled)

    rows: list[dict] = []
    for head in sorted(numbered):
        by_seq = numbered[head]
        for lo, hi in _runs(sorted(by_seq)):
            rows.append({
                "from": by_seq[lo][0],
                "to": by_seq[hi][0],
                # The rows ARE the contiguous runs, so this is the span AND
                # the count of documents — they cannot disagree.
                "totnum": hi - lo + 1,
                "cancel": sum(1 for s in range(lo, hi + 1) if by_seq[s][1]),
            })
    for d in unnumbered:
        rows.append({
            "from": d.number.strip(),
            "to": d.number.strip(),
            "totnum": 1,
            "cancel": 1 if d.is_cancelled else 0,
        })

    out = []
    for i, r in enumerate(rows, start=1):
        out.append({
            "num": i,
            "from": r["from"],
            "to": r["to"],
            "totnum": r["totnum"],
            "cancel": r["cancel"],
            "net_issue": r["totnum"] - r["cancel"],
        })
    return out


#: Said on the return when nobody supplied the cancelled documents, so a
#: `cancel` of 0 is not read as "none were cancelled".
CANCELLED_NOT_SUPPLIED = (
    "Table 13's cancelled count is nil because no cancelled documents were "
    "read for this period, not because none were cancelled. A cancelled "
    "invoice consumed its number under CGST Rule 46(b) and is declared here."
)
