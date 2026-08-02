"""
Indian bank narration parsing — pure, testable, no I/O.

WHY THIS EXISTS
    An Indian bank narration is not free text. It is a delimited record that
    every bank formats slightly differently but that carries the same handful of
    facts:

        UPI/DR/412345678901/RAMESH KUMAR/HDFC/ramesh@okhdfc/PAYMENT
        NEFT DR-SBIN0001234-ACME PVT LTD-N123456789012345
        MMT/IMPS/412512345678/Payment/RAMESH/HDFC

    The channel, the UTR, the counterparty and (for UPI) the VPA are all sitting
    there. Until now the matcher treated the whole thing as an opaque string and
    tested `party_name.lower() in narration` — which works only when the party is
    stored under exactly the name the bank printed, and silently fails on
    "Acme Pvt Ltd" vs "ACME PRIVATE LIMITED".

WHAT THIS IS NOT
    Not a classifier and not a posting decision. It extracts what the bank
    already wrote down. Everything downstream still ranks, suggests and waits for
    a CA to confirm — nothing here settles anything or picks a GL account.

DESIGN
    Bank-specific layouts are NOT enumerated. There are hundreds of them and they
    change without notice; a per-bank adapter list would be permanently out of
    date (the statement parser can afford one because a CSV's column order is
    stable, a narration's is not). Instead every narration is split on the
    delimiters all of them use and each token is CLASSIFIED by shape — a VPA
    looks like a VPA in every bank's format, a 12-digit UTR is a 12-digit UTR.
    Unrecognised tokens are simply left out rather than guessed at.

    Integer paise is not involved: this module touches no money.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ── Channels, in priority order ─────────────────────────────────────────────
# The first pattern that matches wins, so more specific ones come first: an SBI
# narration reads "TO TRANSFER-UPI/DR/..." and is a UPI payment, not a generic
# transfer.
_CHANNELS: tuple[tuple[str, str], ...] = (
    ("UPI",   r"\bUPI\b"),
    ("IMPS",  r"\bIMPS\b"),
    ("NEFT",  r"\bNEFT\b"),
    ("RTGS",  r"\bRTGS\b"),
    ("NACH",  r"\b(?:NACH|ACH)\b"),
    ("CHEQUE", r"\b(?:CHQ|CHEQUE|CLG|MICR)\b"),
    ("ATM",   r"\b(?:ATM|ATW|NWD|CWDR)\b"),
    ("POS",   r"\b(?:POS|ECOM|VPS)\b"),
    ("CARD",  r"\b(?:DEBIT\s?CARD|CREDIT\s?CARD)\b"),
    ("INTEREST", r"\b(?:INT\.?PD|INTEREST|CREDIT\s+INTEREST)\b"),
    ("CHARGES",  r"\b(?:CHRG|CHARGES|CHGS|SMS\s?CHG|AMB\s?CHRG)\b"),
    ("CASH",  r"\b(?:CASH\s?DEP|CDM|BY\s?CASH|TO\s?CASH)\b"),
)

# A UPI/IMPS UTR is 12 digits. NEFT/RTGS references are alphanumeric and longer
# (commonly a 4-letter bank prefix then digits, or 'N' + 15).
_RE_UTR_12 = re.compile(r"(?<!\d)(\d{12})(?!\d)")
_RE_UTR_ALNUM = re.compile(r"\b([A-Z]{4}[A-Z0-9]{8,18}|N\d{15})\b")

# A VPA is the one genuinely unambiguous token in an Indian narration.
_RE_VPA = re.compile(r"\b([a-zA-Z0-9][\w.\-]{1,60}@[a-zA-Z]{2,20})\b")

_RE_IFSC = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")
_RE_MASKED_ACCOUNT = re.compile(r"^[\dX*]{4,}$", re.I)
_RE_HAS_LETTER = re.compile(r"[A-Za-z]")

_DELIMITERS = re.compile(r"[/\-*|,:;]+")

# Structural noise: routing words, direction flags, product codes. These are
# never a counterparty name, so they must not be mistaken for one.
_NOISE = frozenset({
    "UPI", "IMPS", "NEFT", "RTGS", "NACH", "ACH", "MMT", "BIL", "INFT", "INF",
    "TO", "BY", "FROM", "TRANSFER", "TRF", "TRANSFERTO", "PAYMENT", "PAY", "PMT",
    "DR", "CR", "DEBIT", "CREDIT", "P2A", "P2P", "P2M", "COLLECT", "REV",
    "NA", "NIL", "OTHERS", "OTHER", "MISC", "REF", "REFUND", "SENT", "RECEIVED",
    "CHQ", "CHEQUE", "CLG", "MICR", "ATM", "ATW", "NWD", "POS", "ECOM", "VPS",
    "CASH", "CDM", "DEP", "WDL", "SELF", "FT", "IB", "MB", "NB", "INB", "TPT",
    "SETTLEMENT", "TXN", "TRANSACTION", "ONLINE", "MOBILE", "BANK", "LTD",
})

# Four-letter bank identifiers that appear as bare tokens. Kept deliberately
# short — the IFSC pattern catches the full codes, and this only exists so a
# bare "HDFC" beside a name is not itself read as the name.
_BANK_TOKENS = frozenset({
    "HDFC", "ICIC", "SBIN", "UTIB", "KKBK", "PUNB", "BARB", "CNRB", "IOBA",
    "IDIB", "IDFB", "YESB", "INDB", "FDRL", "RATN", "AUBL", "BKID", "MAHB",
    "UBIN", "CBIN", "PYTM", "AIRP", "JIOP", "SIBL", "TMBL", "KVBL", "DBSS",
    "SCBL", "CITI", "HSBC", "AXIS", "KOTAK", "SBI", "PNB", "BOB", "IDFC",
})

# Suffixes stripped before comparing a narration name to a stored party name.
_ENTITY_SUFFIXES = (
    "PRIVATE LIMITED", "PVT LIMITED", "PRIVATE LTD", "PVT LTD", "PVTLTD",
    "LIMITED", "LTD", "LLP", "INC", "CORP", "CO", "COMPANY", "ENTERPRISES",
    "ENTERPRISE", "INDIA", "AND SONS", "SONS",
)


@dataclass(frozen=True)
class ParsedNarration:
    """What the bank already wrote down. Every field is Optional — a narration
    that carries none of them parses to an all-None result rather than a guess."""
    raw: str
    channel: Optional[str] = None          # UPI | NEFT | RTGS | IMPS | …
    utr: Optional[str] = None              # UTR / reference number
    vpa: Optional[str] = None              # UPI id, e.g. ramesh@okhdfc
    counterparty: Optional[str] = None     # the other side's name, as printed
    ifsc: Optional[str] = None
    direction: Optional[str] = None        # 'debit' | 'credit', when stated
    tokens: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not any((self.channel, self.utr, self.vpa, self.counterparty, self.ifsc))


def _clean(token: str) -> str:
    return re.sub(r"\s+", " ", token).strip()


def _detect_channel(text: str) -> Optional[str]:
    upper = text.upper()
    for name, pattern in _CHANNELS:
        if re.search(pattern, upper):
            return name
    return None


def _words(token: str) -> list[str]:
    """A token's words. Banks run structure and content together inside one
    delimited field — 'NEFT DR', 'TO TRANSFER', 'MISC 9987' — so classification
    has to happen at word level, not token level."""
    return [w for w in re.split(r"\s+", token) if w]


def _detect_direction(tokens: list[str]) -> Optional[str]:
    """Only from a STANDALONE Dr/Cr word. 'CREDIT CARD' is a product name, not a
    direction, and the debit/credit columns are the authority anyway — this is a
    corroborating hint, never a source of truth."""
    words = [w.upper() for t in tokens for w in _words(t)]
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if w in ("DR", "DEBIT") and nxt != "CARD":
            return "debit"
        if w in ("CR", "CREDIT") and nxt != "CARD":
            return "credit"
    return None


def _is_noise_word(word: str) -> bool:
    w = word.upper()
    if w in _NOISE or w in _BANK_TOKENS:
        return True
    if not _RE_HAS_LETTER.search(word):
        return True                       # pure digits
    if _RE_MASKED_ACCOUNT.match(word):
        return True                       # XXXXXXXX1234
    if _RE_IFSC.fullmatch(w):
        return True
    if "@" in word:
        return True                       # a VPA, captured separately
    return False


def _is_noise(token: str) -> bool:
    """A token is noise when EVERY word in it is. 'RAMESH KUMAR' survives;
    'NEFT DR' and 'TO TRANSFER' do not."""
    words = _words(token)
    return not words or all(_is_noise_word(w) for w in words)


def _pick_counterparty(tokens: list[str], vpa: Optional[str]) -> Optional[str]:
    """The most name-like remaining token.

    Prefers the longest candidate with a space or at least four letters — real
    names ("RAMESH KUMAR", "ACME PVT LTD") beat fragments. Falls back to the VPA
    handle only when nothing else survives, because `ramesh@okhdfc` still tells a
    CA more than nothing.
    """
    candidates = [t for t in tokens if not _is_noise(t)]
    candidates = [t for t in candidates if len(re.sub(r"[^A-Za-z]", "", t)) >= 3]
    if candidates:
        return max(candidates, key=lambda t: (len(re.sub(r"[^A-Za-z]", "", t)), len(t)))
    if vpa:
        handle = vpa.split("@")[0]
        if len(re.sub(r"[^A-Za-z]", "", handle)) >= 3:
            return handle
    return None


def parse_narration(narration: Optional[str]) -> ParsedNarration:
    """Extract the structured facts an Indian bank narration already carries.

    Never raises: an unparseable narration yields an all-None result. Callers
    treat every field as a hint, not an instruction.
    """
    raw = (narration or "").strip()
    if not raw:
        return ParsedNarration(raw="")

    tokens = [_clean(t) for t in _DELIMITERS.split(raw)]
    tokens = [t for t in tokens if t]

    # Search per TOKEN, not across the raw string: '-' is both a legal VPA
    # character and HDFC's field delimiter, so a raw search happily returns
    # 'KUMAR-RAMESH@OKAXIS' — the previous field glued onto the real VPA.
    vpa = None
    for token in tokens:
        for word in _words(token):
            m = _RE_VPA.fullmatch(word)
            if m:
                vpa = m.group(1)
                break
        if vpa:
            break

    utr = None
    m12 = _RE_UTR_12.search(raw)
    if m12:
        utr = m12.group(1)
    else:
        # Don't let an IFSC be read as a NEFT reference — same alphanumeric shape.
        for m in _RE_UTR_ALNUM.finditer(raw.upper()):
            if not _RE_IFSC.fullmatch(m.group(1)):
                utr = m.group(1)
                break

    ifsc_match = _RE_IFSC.search(raw.upper())

    return ParsedNarration(
        raw=raw,
        channel=_detect_channel(raw),
        utr=utr,
        vpa=vpa,
        counterparty=_pick_counterparty(tokens, vpa),
        ifsc=ifsc_match.group(1) if ifsc_match else None,
        direction=_detect_direction(tokens),
        tokens=tuple(tokens),
    )


# ── Party-name comparison ───────────────────────────────────────────────────

def normalise_party_name(name: Optional[str]) -> str:
    """Upper-case, punctuation-free, entity-suffix-free form for comparison.

    'Acme Pvt. Ltd.' and 'ACME PRIVATE LIMITED' are the same counterparty; a raw
    substring test says they are not, which is why the matcher used to miss them.
    """
    if not name:
        return ""
    text = re.sub(r"[^A-Za-z0-9\s]", " ", str(name)).upper()
    text = re.sub(r"\s+", " ", text).strip()
    for suffix in _ENTITY_SUFFIXES:
        if text.endswith(" " + suffix):
            text = text[: -(len(suffix) + 1)].strip()
    return text


def party_matches(party_name: Optional[str], parsed: ParsedNarration) -> bool:
    """Does this stored customer/vendor look like the narration's counterparty?

    Three ways, cheapest first:
      1. the raw substring test the matcher already did (kept, so nothing that
         matched before stops matching);
      2. normalised equality — 'Acme Pvt Ltd' == 'ACME PRIVATE LIMITED';
      3. every significant word of the shorter name appears in the longer, which
         catches 'ACME PVT LTD' inside 'ACME PVT LTD MUMBAI' without matching on
         one incidental word.
    """
    party = normalise_party_name(party_name)
    if not party:
        return False

    if str(party_name).strip().lower() in (parsed.raw or "").lower():
        return True

    other = normalise_party_name(parsed.counterparty)
    if not other:
        return False
    if party == other:
        return True

    party_words = {w for w in party.split() if len(w) >= 3}
    other_words = {w for w in other.split() if len(w) >= 3}
    if not party_words or not other_words:
        return False
    smaller, larger = ((party_words, other_words)
                       if len(party_words) <= len(other_words)
                       else (other_words, party_words))
    # A single shared word is a coincidence ("SHARMA", "INDIA"); require the
    # whole of the shorter name, and at least two words unless it is genuinely
    # one word long.
    if len(smaller) == 1:
        return smaller <= larger and len(larger) <= 2
    return smaller <= larger


def describe(parsed: ParsedNarration) -> str:
    """One-line human summary for the work queue: 'UPI · RAMESH KUMAR · UTR
    412345678901'. Display only."""
    bits = [b for b in (
        parsed.channel,
        parsed.counterparty,
        f"UTR {parsed.utr}" if parsed.utr else None,
        parsed.vpa,
    ) if b]
    return " · ".join(bits)
