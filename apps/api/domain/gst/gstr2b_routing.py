"""Whose book a GSTR-2B file belongs in, decided from the GSTIN inside it (gst-10).

WHAT WAS MISSING
    A 2B was reconciled one client at a time, from that client's own tab, with
    the CA choosing the client BEFORE the file. A practice with sixty clients
    downloads sixty files in one sitting and then opens sixty tabs. Every file
    already says whose it is — `data.gstin` is the RECIPIENT's registration, and
    `domain/gst/gstr2b_intake` already refuses a file whose GSTIN the chosen
    client does not hold — so the choice can be made the other way round: read
    the GSTIN, find the client.

WHAT THIS DECIDES
    Given the parsed file, the registrations clients of THIS FIRM hold, and the
    set of clients the CALLER may see, one answer: which client, or why none.
    It reads nothing and writes nothing; `services/gst_2b_bulk_service` fetches
    its inputs and acts on the answer.

THE GSTIN DECIDES AND NOTHING DEFAULTS
    `domain/gst/registrations.resolve` refuses a GSTIN the client does not hold
    and never falls back to the primary, because filing one registration's
    figures under another's is invisible until somebody notices. The same rule
    holds one level up: a file whose GSTIN matches no client is REPORTED and not
    stored — not filed under "the" client, not under the first one, not under
    the firm — and a GSTIN that two clients hold is REFUSED as ambiguous rather
    than given to whichever was found first. Two clients holding one GSTIN is a
    data problem (a duplicated client record) and the person who can tell which
    is right is the CA, not a sort order.

THE CALLER'S OWN BOOK, AND NOT A LEAK OF THE REST
    `visible` is `core.authz.effective_client_ids`: None means every client of
    the firm (a Partner), a set means exactly those (an assignment-scoped
    Manager, Executive or Reviewer), and an EMPTY set means nothing — never "no
    filter". A client outside it is as good as absent, and the answer says so in
    the SAME words as for a GSTIN nobody holds: a different sentence for "exists
    but is not yours" would be an oracle for the existence of another person's
    client, the reason `assert_client_access` answers 404 and not 403.

NOT THIS MODULE'S QUESTION
    Whether the file is for the right MONTH and whether the client holds the
    GSTIN as a live registration are `gstr2b_intake`'s, asked per routed file by
    the service. Whether the same client and month appear twice in one upload is
    the service's too: it is a fact about the batch, not about one file.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from domain.gst.gstr2b import GSTR2BFile

ROUTED = "routed"
UNMATCHED_GSTIN = "unmatched_gstin"
AMBIGUOUS_GSTIN = "ambiguous_gstin"
NO_GSTIN = "no_gstin"
NOT_A_GSTR2B = "not_a_gstr2b"

#: One sentence for "no client of yours holds it", whatever the reason — see the
#: module docstring on why a nonexistent GSTIN and an out-of-scope one must read
#: the same.
def unmatched_sentence(gstin: str) -> str:
    return (
        f"No client in your book holds GSTIN {gstin}, so this file was not "
        f"reconciled and nothing was stored. Record {gstin} on the client it "
        f"was downloaded for (the client's GST registrations), or check that "
        f"the right file was chosen.")


@dataclass(frozen=True)
class Holder:
    """One (client, GSTIN) pair — a client's primary GSTIN or one of its
    additional registrations."""
    client_id: str
    gstin: str
    is_primary: bool = False


@dataclass(frozen=True)
class Routing:
    verdict: str
    #: The client the file is for; set only where `verdict` is ROUTED.
    client_id: Optional[str]
    #: The recipient GSTIN the FILE names, normalised ("" where it names none).
    gstin: str
    #: A sentence for a CA; None where the file was routed.
    reason: Optional[str] = None

    @property
    def routed(self) -> bool:
        return self.verdict == ROUTED


def normalise(gstin: Optional[str]) -> str:
    return str(gstin or "").strip().upper()


def route(parsed: GSTR2BFile, holders: Sequence[Holder],
          visible: Optional[set[str]]) -> Routing:
    """The client this file belongs to, or the reason it belongs to nobody.

    `holders` is every (client, GSTIN) pair of the CALLER'S FIRM that could name
    the file's GSTIN — the firm filter is the fetch's, and this still never
    reads a client id off the file or the request. `visible` narrows it to the
    caller's own book (None means every client of the firm).
    """
    if not parsed.docdata_seen:
        return Routing(
            NOT_A_GSTR2B, None, normalise(parsed.gstin),
            " ".join(parsed.problems) or
            "This is not a GSTR-2B file, so it cannot be told whose it is.")

    gstin = normalise(parsed.gstin)
    if not gstin:
        return Routing(
            NO_GSTIN, None, "",
            "This file names no recipient GSTIN (`data.gstin`), so it cannot be "
            "told which client it is for and was not stored. A GSTR-2B as "
            "downloaded from the portal always carries one — do not edit the "
            "file.")

    candidates = {h.client_id for h in holders
                  if normalise(h.gstin) == gstin
                  and (visible is None or h.client_id in visible)}
    if not candidates:
        return Routing(UNMATCHED_GSTIN, None, gstin, unmatched_sentence(gstin))
    if len(candidates) > 1:
        return Routing(
            AMBIGUOUS_GSTIN, None, gstin,
            f"More than one of your clients holds GSTIN {gstin}, so this file "
            f"was not filed under any of them. Two client records for one "
            f"registration is a duplicate to resolve first; once it is, upload "
            f"the file again.")
    return Routing(ROUTED, next(iter(candidates)), gstin, None)
