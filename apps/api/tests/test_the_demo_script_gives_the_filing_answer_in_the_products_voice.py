"""The demo script gives the filing answer in the product's own voice, and shows only what exists (PRE-B-005).

WHY THIS EXISTS

    A CA's first question in a demo is some form of "can I use this for my practice tomorrow", and the honest
    answer is about FILING: PracticeSync prepares every return and transmits none, because direct submission
    needs registrations (a GSP, an ERI, NIC credentials) that nobody has sought yet (decision D17). The product
    already words that once, in `domain/filing_posture.py`, and a test holds the wording to the rule that no
    sentence may claim a standing the product lacks. But that test reads the five fields of one object. A
    person speaking has no object to read from, so the sentence a CA hears is whatever the presenter says, and
    there was nowhere that fixed it. The owner decided the words on 9 October 2026 and
    `docs/operations/demo-script.md` is where they live: the one sentence verbatim, the long form equal to the
    posture the filing screens print, a run of show in the order the marketing site's /demo page promises, the
    screens to steer round, and the words never to use.

WHAT THIS HOLDS, AS RULES RATHER THAN SPELLINGS

    * The sentence the owner chose is the ONLY block under its heading and is exactly the owner's text, says
      "planned", and none of `domain.filing_posture.FORBIDDEN_REGISTRATION_CLAIMS` (the list is held once, there,
      and imported here) appears anywhere in the script outside the fenced "Never say" block and outside words
      quoted from a screen (the register's «» convention: the screen's voice, held by its own guard).
      The same goes for the five extra phrases (NEVER_SAY_ALSO), everywhere except the Never-say section, whose
      explanation of why each is on the list has to name it. The scan reads the script the way a listener hears
      it (`fold`): the file is hard-wrapped, so a phrase split by a line break, a double space, a hyphen, a
      blockquote marker or a bold mark is the same phrase, and a heading is as much the presenter's voice as a
      paragraph.
    * The long form is `POSTURE.roadmap` character for character: edit one and not the other and this fails, so
      what is said aloud and what the filing screens print cannot drift apart.
    * The "Never say" block lists every phrase of that constant, so a phrase added there is added here.
    * Every id the script cites (an open-items line, a register row, a decision) exists, so closing a ledger
      item or deleting a register row forces a look at the script in the same commit.
    * It shows only what exists TODAY: every route it names is a page in one of the two apps; every word in
      bold in the sections that say where to click is a label found in the product's source; every «quoted»
      screen sentence is in the source; the thirty minutes add up to the thirty the /demo page promises.
    * A screen whose register row is marked unsafe (its words overstate what it does) is never "explained":
      the table says avoid.
    * The script says it has not been rehearsed until its record holds a date, and the record and the warning
      agree. There is no demo date in it (PRE-C-001: the owner has not set one).
    * No credential, address or phone number: it is a public repository.

WHAT IT DOES NOT DO

    It does not find a screen that says "planned" and is missing from the avoid-or-explain table: the register
    (`docs/open-items/coming-soon.md`) is the list of such screens and the script cites the ones a demo can
    reach, so a row added there later is not a failure here. That is why the script's header says its list is
    NOT exhaustive and why a test requires it to (a header claiming every such screen is listed would claim
    what nothing can back). It does not prove any step works (nobody has rehearsed it), and the Decision column
    is a proposal the owner overwrites.

WRITE THE RULE, NOT A SPELLING OF IT

    Every check below is a function of the script's text, and the verify-clause tests at the bottom run the
    same functions over deliberately broken copies, so each rule is shown to fail on the mistake it exists for.
"""
from __future__ import annotations

import functools
import os
import re
from pathlib import Path

import pytest

from domain.filing_posture import FORBIDDEN_REGISTRATION_CLAIMS, POSTURE

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "docs" / "operations" / "demo-script.md"
LEDGER_DIR = REPO / "docs" / "open-items"
REGISTER = LEDGER_DIR / "coming-soon.md"
THE_PLAN = REPO / "docs" / "plan" / "THE-PLAN.md"
WEB = REPO / "apps" / "web"
MARKETING = REPO / "apps" / "marketing"
API = REPO / "apps" / "api"
DEMO_PAGE = MARKETING / "app" / "(site)" / "demo" / "page.tsx"

#: The owner's decision of 9 October 2026, word for word.
THE_ONE_SENTENCE = (
    "PracticeSync prepares your returns and books; you file on the portal. "
    "Direct submission is planned and depends on registrations we do not yet hold."
)

#: Phrases the script must never be heard using, beyond the filing list: each is a claim the code cannot back
#: (a replacement of Tally, a filing the product does not make, an acceptance nobody recorded, encryption nothing
#: cites, a training position nobody confirmed).
NEVER_SAY_ALSO = ("replaces Tally", "files for you", "accepted by GSTN", "encrypted", "trained on")

#: The sections that tell a person where to click: in them, bold type is a label on a screen and nothing else.
CLICK_SECTIONS = ("Before you start", "The run of show")

RUN_HEADER = ["Min", "The /demo page promises", "Screen", "Click", "Say"]
AVOID_HEADER = ["Decision", "Screen or claim", "The line to say if it comes up", "Held by"]
SWITCH_HEADER = ["What is off", "What it means on the day", "Held by"]

LEDGER_ID = re.compile(r"\b(?:PRE|POST)-[ABC]-\d{3}\b")
COMING_ID = re.compile(r"\bCOMING-\d{3}\b")
DECISION_ID = re.compile(r"\bD\d{1,2}\b")

#: A repository path as the script writes it (`docs/open-items/coming-soon.md`): a path is read, never spoken.
_PATH = re.compile(
    r"(?<![\w/.\-])((?:apps|docs|scripts|tests|lib|components|app|core|\.github)/[\w./\-]*[\w]\.(?:md|py|sql|tsx|ts|mjs|yml|yaml|json|toml)(?![\w]))"
)

Problems = list[str]


# ── reading the script ───────────────────────────────────────────────────────

def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def sections(text: str) -> list[tuple[int | None, str, str]]:
    """(number, title, body) for every `## ` heading; the number is None for an unnumbered one."""
    out: list[tuple[int | None, str, str]] = []
    heads = list(re.finditer(r"^## (?:(\d+)\. )?(.+?)\s*$", text, re.M))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append((int(m[1]) if m[1] else None, m[2], text[m.end():end]))
    return out


def bodies(text: str, title_prefix: str) -> list[str]:
    return [b for _n, t, b in sections(text) if t.startswith(title_prefix)]


def blockquotes(body: str) -> list[str]:
    """Each run of consecutive `>` lines, joined with single spaces (a quote wrapped over lines is one sentence)."""
    blocks: list[str] = []
    cur: list[str] = []
    for line in body.splitlines():
        if line.startswith(">"):
            cur.append(line[1:].strip())
        elif cur:
            blocks.append(" ".join(cur))
            cur = []
    if cur:
        blocks.append(" ".join(cur))
    return blocks


FENCE = re.compile(r"^```[^\n]*\n(.*?)^```[ \t]*$", re.M | re.S)


def fenced_blocks(body: str) -> list[str]:
    return [m[1] for m in FENCE.finditer(body)]


def tables(body: str) -> list[list[list[str]]]:
    """Each markdown table in `body` as rows of cells, the header first and the `---` row dropped."""
    found: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for line in body.splitlines():
        if line.lstrip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                cur.append(cells)
        elif cur:
            found.append(cur)
            cur = []
    if cur:
        found.append(cur)
    return found


def the_table(text: str, title_prefix: str, header: list[str]) -> tuple[list[list[str]], Problems]:
    """The one table under a section, or why there is not exactly one with this header."""
    secs = bodies(text, title_prefix)
    if len(secs) != 1:
        return [], [f"there must be exactly one section called {title_prefix!r}, found {len(secs)}"]
    tbls = tables(secs[0])
    if len(tbls) != 1:
        return [], [f"section {title_prefix!r} must hold exactly one table, found {len(tbls)}"]
    if tbls[0][0] != header:
        return [], [f"section {title_prefix!r}: the header is {tbls[0][0]}, expected {header}"]
    rows = tbls[0][1:]
    bad = [r for r in rows if len(r) != len(header) or not all(c for c in r)]
    return rows, [f"section {title_prefix!r} has a row with an empty or missing cell: {r[:2]}" for r in bad]


def quotes(text: str) -> list[str]:
    return [q.strip() for q in re.findall(r"«([^»]+)»", text)]


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def fold(s: str) -> str:
    """`s` as a listener hears it, lower-cased, for matching a spoken phrase.

    The script is hard-wrapped at about 110 columns, so a phrase can be split by a line break, and an edit can
    put two spaces, a hyphen (`under-way`), a blockquote marker (`> `) or bold marks between its words. A
    substring test on the raw text sees none of those. A repository path is dropped first: it is read, never
    spoken, and `coming-soon.md` is not the words 'coming soon'."""
    s = _PATH.sub(" ", s)
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"(?m)^[ \t]*>[ \t]?", "", s)            # blockquote markers at the start of a line
    s = re.sub(r"[\u00ad\u200b-\u200d\u2060\ufeff]", "", s)  # soft hyphen and zero-width characters join, never split
    s = re.sub(r"[*`~]", "", s)                           # bold, italic and code marks
    s = re.sub(r"[-\u2010-\u2015]", " ", s)              # hyphen, non-breaking hyphen, en and em dash
    return re.sub(r"\s+", " ", s).strip().lower()


# ── what the product holds (read once) ───────────────────────────────────────

_SKIP_DIRS = {"__pycache__", ".venv", "venv", "node_modules", ".pytest_cache", ".next", "out", "tests"}


def _files(root: Path, suffixes: tuple[str, ...]):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(suffixes) and not fn.endswith((".test.ts", ".test.tsx")):
                yield Path(dirpath) / fn


@functools.lru_cache(maxsize=None)
def _source(*roots: str) -> tuple[str, str]:
    """Every non-test source file under `roots`, whitespace squashed, and a second copy with adjacent string
    literals joined (`"a "` newline `"b"`), because a long sentence is written in pieces. A sentence is 'on a
    screen' if either copy holds it."""
    plain: list[str] = []
    joined: list[str] = []
    for root in roots:
        for f in _files(Path(root), (".ts", ".tsx", ".py")):
            raw = f.read_text(encoding="utf-8", errors="ignore")
            plain.append(squash(raw))
            joined.append(squash(re.sub(r"""(["'`])\s*\+?\s*\n\s*\1""", "", raw)))
    return " ".join(plain), " ".join(joined)


def web_source() -> str:
    return _source(str(WEB / "app"), str(WEB / "components"), str(WEB / "lib"))[0]


def product_source() -> tuple[str, str]:
    return _source(str(WEB / "app"), str(WEB / "components"), str(WEB / "lib"),
                   str(MARKETING / "app"), str(MARKETING / "components"), str(MARKETING / "lib"), str(API))


@functools.lru_cache(maxsize=None)
def ledger_ids() -> frozenset[str]:
    ids: set[str] = set()
    for p in [*LEDGER_DIR.glob("pre-demo-*.md"), *LEDGER_DIR.glob("post-demo-*.md")]:
        ids.update(re.findall(rf"^- \*\*({LEDGER_ID.pattern})\*\*", read(p), re.M))
    return frozenset(ids)


@functools.lru_cache(maxsize=None)
def register_rows() -> dict[str, tuple[str, str]]:
    """COMING id -> (kind, safe) where safe is 'yes' or 'no'."""
    rows: dict[str, tuple[str, str]] = {}
    pat = re.compile(r"^- \*\*(COMING-\d{3})\*\* · `([a-z]+)` · `[a-z]+` · .* — _Safe:_ (yes|no)\b", re.M)
    for m in pat.finditer(read(REGISTER)):
        rows[m[1]] = (m[2], m[3])
    return rows


def _page_at(here: Path, segs: list[str]) -> bool:
    if not segs:
        return (here / "page.tsx").is_file() or (here / "page.ts").is_file()
    if not here.is_dir():
        return False
    seg, rest = segs[0], segs[1:]
    if seg.startswith("<"):
        return any(_page_at(d, rest) for d in here.iterdir() if d.is_dir() and d.name.startswith("["))
    return _page_at(here / seg, rest)


def route_exists(route: str) -> bool:
    """`/clients/<id>/compliance/gst` is a page if each segment is a directory (a `<...>` segment is any
    `[...]` directory) and the last holds a page, in either app (the marketing pages sit in a route group)."""
    segs = [s for s in route.strip("/").split("/") if s]
    return any(_page_at(root, segs) for root in (WEB / "app", MARKETING / "app", MARKETING / "app" / "(site)"))


# ── the checks (each a function of text, so the verify clause can break it) ──

def check_status_and_record(text: str) -> Problems:
    """The warning at the top and the record at the bottom agree, and the record names no rehearsal that did not happen."""
    out: Problems = []
    head = "\n".join(text.splitlines()[:12])
    warned = "NOT REHEARSED" in head
    rows = [l for l in text.splitlines() if re.match(r"\|\s*R\d+\.", l)]
    if len(rows) < 2:
        return ["the rehearsal record must have a row per pass (R1, R2)"]
    dated = [bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{2}-\d{2}-\d{4}\b", r)) for r in rows]
    not_run = ["not run" in r.lower() for r in rows]
    for r, d, n in zip(rows, dated, not_run, strict=True):
        if d == n:
            out.append(f"a rehearsal row says 'not run' or carries a date, never both or neither: {r!r}")
    if warned == all(dated):
        out.append("the warning at the top and the record at the bottom disagree about whether it has been rehearsed")
    return out


def check_one_sentence(text: str) -> Problems:
    out: Problems = []
    secs = bodies(text, "The one sentence")
    if len(secs) != 1:
        return [f"there must be exactly one section 'The one sentence', found {len(secs)}"]
    qs = blockquotes(secs[0])
    if len(qs) != 1:
        return [f"'The one sentence' must hold exactly one quoted block, found {len(qs)}"]
    if qs[0] != THE_ONE_SENTENCE:
        out.append(f"the sentence is not the owner's words: {qs[0]!r}")
    low = fold(qs[0])
    if "planned" not in low:
        out.append("the sentence must say direct submission is planned")
    out += [f"the sentence says {p!r}, a claim of standing the product lacks" for p in FORBIDDEN_REGISTRATION_CLAIMS if p in low]
    return out


def check_if_pressed(text: str, roadmap: str) -> Problems:
    secs = bodies(text, "If pressed")
    if len(secs) != 1:
        return [f"there must be exactly one section 'If pressed', found {len(secs)}"]
    qs = blockquotes(secs[0])
    if len(qs) != 1:
        return [f"'If pressed' must quote the filing posture exactly once, found {len(qs)} blocks"]
    if qs[0] != roadmap:
        return ["the long form is not POSTURE.roadmap character for character: what is said aloud and what the filing "
                f"screens print have drifted apart\n  script : {qs[0]!r}\n  posture: {roadmap!r}"]
    return []


def voice_of_the_script(text: str, *, never_say_commentary: bool = True) -> str:
    """The script minus its fenced 'Never say' block(s) and minus words quoted from a screen. A heading is the
    presenter's voice too, so each section's title is kept. With `never_say_commentary=False` the whole 'Never
    say' section goes, because its explanation of why each phrase is on the list has to name the phrase."""
    parts: list[str] = []
    for _n, title, body in sections(text):
        if title.startswith("Never say"):
            if not never_say_commentary:
                continue
            body = FENCE.sub("", body)
        parts.append(title)
        parts.append(body)
    head = text.split("\n## ", 1)[0]
    return re.sub(r"«[^»]*»", "", head + "\n" + "\n".join(parts))


def check_no_forbidden_claim(text: str) -> Problems:
    low = fold(voice_of_the_script(text))
    out = [f"the script says {p!r} outside the 'Never say' block: about filing, a registration or regulatory standing "
           "the words are 'planned' and what gates it (D17)" for p in FORBIDDEN_REGISTRATION_CLAIMS if p in low]
    spoken = fold(voice_of_the_script(text, never_say_commentary=False))
    # Whole words: 'files for you' is inside 'profiles for you'.
    out += [f"the script says {p!r} outside the 'Never say' section: it is on the list of things never to say"
            for p in NEVER_SAY_ALSO if re.search(rf"(?<![a-z]){re.escape(fold(p))}(?![a-z])", spoken)]
    return out


def check_does_not_claim_the_list_is_complete(text: str) -> Problems:
    """Sections 6 and 7 cite the register's rows that a demo is likely to reach, and the register itself says it
    does not find a promise that has no row. A header saying every such screen is listed would claim what nothing
    can back, and the presenter reads that line to decide what is safe to click, so the header must say the list
    is not exhaustive."""
    head = fold(text.split("\n## ", 1)[0])
    if "not exhaustive" not in head:
        return ["the header must say the list of screens that say 'planned' is not exhaustive: the register does not "
                "find every such sentence, and the public site is outside the script"]
    return []


def check_never_say(text: str) -> Problems:
    secs = bodies(text, "Never say")
    if len(secs) != 1:
        return [f"there must be exactly one section 'Never say', found {len(secs)}"]
    fences = fenced_blocks(secs[0])
    if len(fences) != 1:
        return [f"'Never say' must hold exactly one fenced block, found {len(fences)}"]
    listed = {l.strip().lower() for l in fences[0].splitlines() if l.strip()}
    want = [*FORBIDDEN_REGISTRATION_CLAIMS, *(p.lower() for p in NEVER_SAY_ALSO)]
    return [f"'Never say' does not list {p!r}" for p in want if p.lower() not in listed]


def check_quotes_are_on_a_screen(text: str, held: tuple[str, str]) -> Problems:
    return [f"«{q[:70]}» is not in any source file of the product: a quoted screen sentence must be on a screen"
            for q in quotes(text) if not any(squash(q) in variant for variant in held)]


def check_ids(text: str, ledger: frozenset[str], register: dict[str, tuple[str, str]], plan: str) -> Problems:
    out: Problems = []
    out += [f"{i} is not in any open-items section file (closed? edit the script in the same commit)"
            for i in sorted(set(LEDGER_ID.findall(text)) - ledger)]
    out += [f"{i} is not a row of docs/open-items/coming-soon.md (deleted? edit the script in the same commit)"
            for i in sorted(set(COMING_ID.findall(text)) - set(register))]
    out += [f"{i} is not a decision in docs/plan/THE-PLAN.md" for i in sorted(set(DECISION_ID.findall(text)))
            if not re.search(rf"\b{i}\b", plan)]
    return out


def check_section_references(text: str) -> Problems:
    """'section 6' is this file's section 6. A statute's section is written s.89 or §192, never 'section 89'."""
    have = {n for n, _t, _b in sections(text) if n is not None}
    wanted = set()
    for m in re.finditer(r"\bsections? (\d+)(?: (?:or|and) (\d+))?", text):
        wanted.update(int(g) for g in m.groups() if g)
    return [f"'section {n}' points at no section of this file" for n in sorted(wanted - have)]


def is_a_label_on_a_screen(label: str, web: str) -> bool:
    """`label` stands as a WHOLE label in the web source: JSX text or a string between its own delimiters, not a
    few words inside a longer sentence. (It is found somewhere in apps/web, not on the one screen the script names:
    a label is a short word and a screen's text is spread over its components, so the stronger claim would need a
    map from every screen to every component it draws.)"""
    return re.search(r"[>}\"'`] ?" + re.escape(squash(label)) + r" ?[<{\"'`]", web) is not None


def check_screens(text: str, web: str) -> Problems:
    out: Problems = []
    for tok in sorted(set(re.findall(r"`(/[A-Za-z0-9\-/<>]*)`", text))):
        if not route_exists(tok):
            out.append(f"{tok} is not a page in apps/web or apps/marketing")
    labels: list[str] = []
    for prefix in CLICK_SECTIONS:
        for body in bodies(text, prefix):
            labels += re.findall(r"\*\*([^*\n]+)\*\*", body)
    out += [f"**{lab}** is set in bold in a section that says where to click but is not a label in apps/web"
            for lab in sorted(set(labels)) if not is_a_label_on_a_screen(lab, web)]
    if not labels:
        out.append("no bold labels found in the click sections: the check would be vacuous")
    return out


def words_to_minutes(page: str) -> int | None:
    m = re.search(r"\b(Twenty|Thirty|Forty-five|Sixty) minutes\b", page, re.I)
    return {"twenty": 20, "thirty": 30, "forty-five": 45, "sixty": 60}[m[1].lower()] if m else None


def check_run_of_show(text: str, demo_page: str) -> Problems:
    rows, out = the_table(text, "The run of show", RUN_HEADER)
    if out:
        return out
    if len(rows) < 6:
        out.append(f"the run of show has {len(rows)} rows; the /demo page promises more than that")
    promised = words_to_minutes(demo_page)
    try:
        total = sum(int(r[0]) for r in rows)
    except ValueError:
        return out + ["a Min cell is not a whole number of minutes"]
    if promised is None:
        out.append("the /demo page no longer says how many minutes it takes: re-read the run of show against it")
    elif total != promised:
        out.append(f"the run of show adds up to {total} minutes and the /demo page promises {promised}")
    page = squash(demo_page)
    for r in rows:
        qs = quotes(r[1])
        if len(qs) != 1 or squash(qs[0]) not in page:
            out.append(f"the promise cell {r[1]!r} must be exactly one «quote» that is on the /demo page")
        if not re.findall(r"`/[^`]+`", r[2]):
            out.append(f"row {r[2]!r} names no screen")
    return out


def check_avoid_table(text: str, register: dict[str, tuple[str, str]]) -> Problems:
    rows, out = the_table(text, "Avoid or explain", AVOID_HEADER)
    if out:
        return out
    if len(rows) < 20:
        out.append(f"only {len(rows)} avoid-or-explain rows: PRE-B-004's eleven lines and the register's screens are more")
    for decision, subject, _line, held in rows:
        if decision not in ("avoid", "explain"):
            out.append(f"{subject[:50]!r}: the decision is {decision!r}, expected avoid or explain")
        cited = LEDGER_ID.findall(held) + COMING_ID.findall(held)
        if not cited:
            out.append(f"{subject[:50]!r} cites no open-items id or register row")
        if decision == "explain":
            out += [f"{subject[:50]!r} is 'explain' but {c} is marked unsafe in the register (its words overstate what "
                    "it does): a screen that overstates is steered round, so the decision is avoid"
                    for c in COMING_ID.findall(held) if register.get(c, ("", "yes"))[1] == "no"]
    if sum("PRE-B-004" in r[3] for r in rows) < 11:
        out.append("fewer than eleven rows cite PRE-B-004: its item 4 has eight lines and its first-hour gaps three")
    return out


def check_switch_table(text: str, register: dict[str, tuple[str, str]]) -> Problems:
    rows, out = the_table(text, "Switched off until the owner supplies something", SWITCH_HEADER)
    if out:
        return out
    if len(rows) < 4:
        out.append(f"only {len(rows)} rows in the switched-off table")
    for what, _means, held in rows:
        cited = COMING_ID.findall(held)
        if not cited:
            out.append(f"{what[:50]!r} cites no register row")
        out += [f"{what[:50]!r} cites {c}, which is a {register[c][0]!r} row and not a switch row"
                for c in cited if c in register and register[c][0] != "switch"]
    return out


_HYGIENE = {
    "an email address": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "a phone number": re.compile(r"(?<![\w.])(?:\+?\d{1,3}[\s-]?)?(?:\d[\s-]?){9,12}\d(?![\w.])"),
    "a JWT": re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}"),
    "a provider secret key": re.compile(r"\b(?:sb_secret_|sbp_|sk-[A-Za-z0-9]{10,}|gsk_[A-Za-z0-9]{10,}|re_[A-Za-z0-9]{16,})"),
    "a connection string with a password": re.compile(r"postgres(?:ql)?://[^\s:@/]+:[^\s@]+@"),
    "a long opaque token": re.compile(r"\b[A-Za-z0-9+/_-]{40,}\b"),
}


def check_hygiene(text: str) -> Problems:
    flat = re.sub(r"https?://[^\s)`>]+", "URL", _PATH.sub("PATH", text))
    return [f"the script contains what looks like {label}: {_HYGIENE[label].findall(flat)[:3]}"
            for label in sorted(_HYGIENE) if _HYGIENE[label].search(flat)]


def all_checks(text: str, roadmap: str) -> dict[str, Problems]:
    """Every check the script is held to, by name (used by the verify clause to show each can fail)."""
    return {
        "status": check_status_and_record(text),
        "one-sentence": check_one_sentence(text),
        "if-pressed": check_if_pressed(text, roadmap),
        "voice": check_no_forbidden_claim(text),
        "not-exhaustive": check_does_not_claim_the_list_is_complete(text),
        "never-say": check_never_say(text),
        "ids": check_ids(text, ledger_ids(), register_rows(), read(THE_PLAN)),
        "sections": check_section_references(text),
        "avoid": check_avoid_table(text, register_rows()),
        "switch": check_switch_table(text, register_rows()),
        "hygiene": check_hygiene(text),
    }


# ═══ the script exists and is the real thing ══════════════════════════════════

@pytest.fixture(scope="module")
def script() -> str:
    return read(SCRIPT)


def test_the_script_exists_and_is_not_a_stub(script):
    assert SCRIPT.is_file()
    assert len(script) > 8000, "the demo script is a stub"
    titles = [t for _n, t, _b in sections(script)]
    for needed in ("Before you start", "The one sentence", "If pressed", "The run of show", "Avoid or explain",
                   "Switched off until the owner supplies something", "Never say", "After the demo", "Rehearsal record"):
        assert any(t.startswith(needed) for t in titles), f"the script has no section {needed!r}"


def test_it_says_it_has_not_been_rehearsed_until_its_record_holds_a_date(script):
    assert not check_status_and_record(script), check_status_and_record(script)
    assert "NOT REHEARSED" in "\n".join(script.splitlines()[:12])


# ═══ the answer, in the product's voice ═══════════════════════════════════════

def test_the_one_sentence_is_the_owners_words_alone_in_its_section_and_says_planned(script):
    assert not check_one_sentence(script), check_one_sentence(script)


def test_the_long_form_is_the_filing_posture_character_for_character(script):
    assert not check_if_pressed(script, POSTURE.roadmap), check_if_pressed(script, POSTURE.roadmap)


def test_the_one_sentence_is_consistent_with_the_posture_it_summarises():
    """The owner's sentence and the posture make one claim in two lengths: both say direct submission is planned,
    both say the CA submits on the portal, and neither names a registration as being sought."""
    for text in (THE_ONE_SENTENCE, POSTURE.roadmap):
        low = fold(text)
        assert "planned" in low and "portal" in low
        assert not [p for p in FORBIDDEN_REGISTRATION_CLAIMS if p in low]


def test_no_claim_of_standing_is_made_outside_the_never_say_block(script):
    assert not check_no_forbidden_claim(script), check_no_forbidden_claim(script)


def test_the_never_say_block_lists_every_forbidden_claim_and_the_named_five(script):
    assert not check_never_say(script), check_never_say(script)


# ═══ it shows only what exists, and cites only what exists ════════════════════

def test_every_quoted_screen_sentence_is_in_the_products_source(script):
    assert quotes(script), "the script quotes no screen sentence: the check would be vacuous"
    assert not check_quotes_are_on_a_screen(script, product_source())


def test_every_id_the_script_cites_exists(script):
    assert len(LEDGER_ID.findall(script)) >= 10 and len(COMING_ID.findall(script)) >= 15, "the script cites too few ids"
    assert not check_ids(script, ledger_ids(), register_rows(), read(THE_PLAN))


def test_every_section_reference_points_at_a_section(script):
    assert not check_section_references(script)


def test_every_screen_it_names_is_a_page_and_every_bold_label_is_on_a_screen(script):
    assert not check_screens(script, web_source()), check_screens(script, web_source())


def test_the_run_of_show_adds_up_to_the_minutes_the_demo_page_promises_and_quotes_its_promises(script):
    assert not check_run_of_show(script, read(DEMO_PAGE)), check_run_of_show(script, read(DEMO_PAGE))


def test_a_screen_whose_words_overstate_is_avoided_never_explained(script):
    assert not check_avoid_table(script, register_rows()), check_avoid_table(script, register_rows())


def test_the_switched_off_table_cites_only_switch_rows(script):
    assert not check_switch_table(script, register_rows()), check_switch_table(script, register_rows())


def test_the_script_holds_no_credential_address_or_phone_number(script):
    assert not check_hygiene(script), check_hygiene(script)


def test_the_script_is_covered_by_the_runbook_path_check():
    """`test_the_operations_runbooks_point_at_files_that_exist` globs docs/operations/*.md, so every repository path
    this script names is resolved there. Assert the glob still reaches it, so moving the script out would not
    quietly drop that check."""
    assert SCRIPT.parent == REPO / "docs" / "operations" and SCRIPT.suffix == ".md"


# ═══ the verify clause: each rule fails on the mistake it exists for ═════════

def _broken(text: str, old: str, new: str) -> str:
    assert old in text, f"the verify clause expects the script to contain {old!r}"
    return text.replace(old, new, 1)


def test_the_checks_pass_on_the_real_script_and_the_helper_is_not_vacuous(script):
    results = all_checks(script, POSTURE.roadmap)
    assert all(not p for p in results.values()), results
    assert len(results) == 11


def test_a_reworded_sentence_fails(script):
    broken = _broken(script, "Direct submission is planned and depends", "Direct submission is under way and depends")
    assert check_one_sentence(broken)
    # and a softer verb the owner did not choose fails too
    assert check_one_sentence(_broken(script, "prepares your returns and books", "prepares returns and books"))


def test_swapping_planned_for_a_claim_of_motion_fails_both_the_sentence_and_the_voice_scan(script):
    broken = _broken(script, "Direct submission is planned and depends", "Direct submission is in progress and depends")
    assert check_one_sentence(broken) and check_no_forbidden_claim(broken)


def test_editing_the_posture_without_the_script_fails(script):
    assert check_if_pressed(script, POSTURE.roadmap + " (reworded)")
    assert check_if_pressed(script, POSTURE.roadmap.replace("is planned", "will follow"))


def test_a_second_quoted_block_under_the_one_sentence_fails(script):
    broken = _broken(script, "## 3. If pressed", "> And, in short, we file for you.\n\n## 3. If pressed")
    assert check_one_sentence(broken)


def test_a_forbidden_phrase_outside_the_never_say_block_fails_and_inside_it_does_not(script):
    assert not check_no_forbidden_claim(script)
    for phrase in FORBIDDEN_REGISTRATION_CLAIMS:
        broken = _broken(script, "## 9. After the demo\n", f"## 9. After the demo\n\nWe have {phrase} for the portals.\n")
        assert check_no_forbidden_claim(broken), f"{phrase!r} outside the Never say block was not caught"
    # the same words quoted from a screen are the screen's voice (held by the register's guard), not the script's
    quoted = _broken(script, "## 9. After the demo\n", "## 9. After the demo\n\nThe button says «Online payment is coming soon».\n")
    assert not check_no_forbidden_claim(quoted)


def _said(script: str, line: str) -> str:
    """The script with `line` added under the last heading, as an author's edit would."""
    return script.rstrip("\n") + "\n\n" + line + "\n"


def test_a_forbidden_phrase_is_found_however_the_line_is_wrapped_or_spaced(script):
    """The file is hard-wrapped at about 110 columns, so a phrase can be split by a line break, and an edit can put
    two spaces, a hyphen, a blockquote marker or bold marks between its words. Derived from the constant, so a
    phrase added there is exercised too."""
    assert not check_no_forbidden_claim(script)
    for phrase in FORBIDDEN_REGISTRATION_CLAIMS:
        words = phrase.split(" ")
        if len(words) < 2:
            continue
        spellings = {
            "wrapped": "\n".join([" ".join(words[:1]), " ".join(words[1:])]),
            "wrapped at every space": "\n".join(words),
            "double space": "  ".join(words),
            "tab": "\t".join(words),
            "hyphen": "-".join(words),
            "en dash": "\u2013".join(words),
            "capitals": phrase.upper(),
            "bold": " ".join(f"**{w}**" for w in words),
            "soft hyphen inside a word": phrase[:2] + "\u00ad" + phrase[2:],
        }
        for how, spelled in spellings.items():
            assert check_no_forbidden_claim(_said(script, f"We say {spelled} to the CA.")), f"{phrase!r} {how}"
        in_quote = "> " + spellings["wrapped"].replace("\n", "\n> ")
        assert check_no_forbidden_claim(_said(script, in_quote)), f"{phrase!r} wrapped inside a blockquote"
    # a word broken at the end of a line with a hyphen ('under-' newline 'way') reads as the two words 'under way'
    assert check_no_forbidden_claim(_said(script, "Registration is under-\nway."))


def test_a_forbidden_phrase_in_a_heading_fails(script):
    assert check_no_forbidden_claim(script + "\n## 11. We are registered\n\nText.\n")
    assert check_no_forbidden_claim(_broken(script, "## 9. After the demo", "## 9. After the demo, coming soon"))


def test_the_phrases_never_to_say_are_not_said_outside_the_never_say_section(script):
    for phrase in NEVER_SAY_ALSO:
        assert check_no_forbidden_claim(_said(script, f"It {phrase} for the CA.")), f"{phrase!r} outside Never say"
        words = phrase.split(" ")
        if len(words) > 1:
            assert check_no_forbidden_claim(_said(script, f"It {words[0]}\n{' '.join(words[1:])} the CA.")), f"{phrase!r} wrapped"
    # the same words quoted from a screen are the screen's voice, and whole words only: 'profiles for you' is not 'files for you'
    assert not check_no_forbidden_claim(_said(script, "Your profiles for you to read."))
    assert not check_no_forbidden_claim(_said(script, "The page says «files for you»."))


def test_a_repository_path_is_read_not_spoken(script):
    """`docs/open-items/coming-soon.md` is not the words 'coming soon', whatever the hyphen folding does."""
    assert "coming soon" in re.sub(r"-", " ", script.lower()), "premise: the script names that path, so folding needs the exemption"
    assert not check_no_forbidden_claim(script)
    assert not check_no_forbidden_claim(_said(script, "See `docs/open-items/coming-soon.md` for the register."))
    assert check_no_forbidden_claim(_said(script, "See docs/open-items/register.md, it is coming soon."))


def test_fold_reads_the_way_a_listener_hears():
    assert fold("We have applied\n  for  it.") == "we have applied for it."
    assert fold("> Under-\n> way") == "under way"
    assert fold("**In** *progress*") == "in progress"
    assert fold("under\u00adway") == "underway"
    assert fold("See `docs/open-items/coming-soon.md`.") == "see ."


def test_a_header_that_claims_every_such_screen_is_listed_fails(script):
    """The sentence this check exists for: the first draft of the header said every screen that says planned is in
    section 6 or 7, which nothing can back."""
    assert not check_does_not_claim_the_list_is_complete(script)
    head, rest = script.split("\n## ", 1)
    claim = ("Every screen that says a feature is planned, not built or not switched on is in section 6 or 7, "
             "next to its row in the register of such wording. ")
    claimed = re.sub(r"Sections 6 and 7.*?(?=The script describes)", claim, head, flags=re.S)
    assert claimed != head and "not exhaustive" not in fold(claimed), "the verify clause did not break the header"
    assert check_does_not_claim_the_list_is_complete(claimed + "\n## " + rest)


def test_a_phrase_added_to_the_forbidden_list_and_not_to_the_never_say_block_fails(script):
    fence_gone = _broken(script, "coming soon\nreplaces Tally", "replaces Tally")
    assert check_never_say(fence_gone)
    no_extra = _broken(script, "encrypted\n", "")
    assert check_never_say(no_extra)


def test_a_screen_that_does_not_exist_or_a_label_nobody_wrote_fails(script):
    web = web_source()
    assert not check_screens(script, web)
    assert check_screens(_broken(script, "`/migration`", "`/migrations-that-do-not-exist`"), web)
    assert check_screens(_broken(script, "**Compute from Books**", "**Compute everything automatically**"), web)
    assert check_screens(_broken(script, "`/clients/<id>/bank`", "`/clients/<id>/no-such-section`"), web)


def test_a_label_must_stand_whole_in_the_source_not_sit_inside_a_sentence():
    assert is_a_label_on_a_screen("Compute from Books", squash("<button>\n   Compute from Books\n </button>"))
    assert is_a_label_on_a_screen("Pass", 'label: "Pass"')
    assert not is_a_label_on_a_screen("Compute from Books", "<p>Please Compute from Books first</p>")
    assert not is_a_label_on_a_screen("Pass", "<p>Pass this entry into the books</p>")


def test_a_quoted_sentence_that_is_on_no_screen_fails(script):
    held = product_source()
    broken = _broken(script, "## 9. After the demo\n", "## 9. After the demo\n\nThe screen says «We file everything for you overnight».\n")
    assert check_quotes_are_on_a_screen(broken, held)


def test_a_dangling_id_fails(script):
    ids = ledger_ids()
    assert check_ids(_broken(script, "PRE-C-005", "PRE-C-999"), ids, register_rows(), read(THE_PLAN))
    assert check_ids(_broken(script, "COMING-010", "COMING-998"), ids, register_rows(), read(THE_PLAN))
    assert check_ids(_broken(script, "(D17)", "(D99)"), ids, register_rows(), read(THE_PLAN))
    # a ledger line closed: the same text against a ledger without PRE-B-004
    assert check_ids(script, ids - {"PRE-B-004"}, register_rows(), read(THE_PLAN)), "PRE-B-004 is cited and was closed"
    assert check_ids(script, frozenset(), register_rows(), read(THE_PLAN))


def test_a_statute_section_written_as_a_document_section_fails(script):
    assert check_section_references(_broken(script, "The s.89 relief worksheet", "The section 89 relief worksheet"))
    assert check_section_references(script + "\nSee section 11.\n")


def test_explaining_a_screen_whose_register_row_is_unsafe_fails(script):
    """The rule: an 'explain' row may not cite a register row marked unsafe. The unsafe case is BUILT here, from a
    copy of the live register, and not read from it: which rows are unsafe moves as the wording fixes land (Pay
    Now, Scheduled Reports and the PF and ESI walk-throughs are each on their way to Safe: yes), and a test that
    expects today's unsafe rows would fail on a correct change made in another file."""
    register = register_rows()
    assert not check_avoid_table(script, register), "premise: the live register and the script agree"
    rows, problems = the_table(script, "Avoid or explain", AVOID_HEADER)
    assert not problems
    explained = sorted({c for decision, _s, _l, held in rows if decision == "explain" for c in COMING_ID.findall(held)})
    assert len(explained) >= 10, "the script explains too few register rows for this check to mean anything"
    for cited in explained:
        kind = register.get(cited, ("promise", "yes"))[0]
        problem = check_avoid_table(script, {**register, cited: (kind, "no")})
        assert any(cited in p and "unsafe" in p for p in problem), f"{cited} marked unsafe was not refused: {problem}"
    # the other direction: a row the script only AVOIDS may be unsafe, which is exactly what the rule asks for
    avoided_only = sorted({c for decision, _s, _l, held in rows if decision == "avoid"
                           for c in COMING_ID.findall(held)} - set(explained))
    assert avoided_only, "the script avoids no register row that it does not also explain"
    for cited in avoided_only:
        kind = register.get(cited, ("promise", "yes"))[0]
        assert not check_avoid_table(script, {**register, cited: (kind, "no")}), f"{cited} is avoided, so unsafe is fine"


def test_a_decision_that_is_neither_avoid_nor_explain_fails_and_a_row_with_no_id_fails(script):
    assert check_avoid_table(_broken(script, "| avoid | Anything dated FY 2026-27", "| ignore | Anything dated FY 2026-27"), register_rows())
    assert check_avoid_table(_broken(script, "| COMING-019 |", "| nothing |"), register_rows())


def test_a_switched_off_row_that_cites_a_promise_row_fails(script):
    assert check_switch_table(_broken(script, "| COMING-008 |", "| COMING-010 |"), register_rows())


def test_a_run_of_show_that_does_not_add_up_or_promises_what_the_page_does_not_fails(script):
    page = read(DEMO_PAGE)
    assert not check_run_of_show(script, page)
    assert check_run_of_show(_broken(script, "| 8 | «A client's GST month»", "| 9 | «A client's GST month»"), page)
    assert check_run_of_show(_broken(script, "«A client's GST month»", "«A year of books in a minute»"), page)
    assert check_run_of_show(script, page.replace("Thirty minutes", "Forty-five minutes"))


def test_a_demo_dated_and_still_warned_or_a_warning_removed_with_an_empty_record_fails(script):
    dated_but_warned = _broken(script, "| R1. A read-through with the console open (PRE-B-008) | not run | | |",
                               "| R1. A read-through with the console open (PRE-B-008) | ran, two fixes | 2026-12-01 | |")
    # one pass dated, one not run: the script is still not (fully) rehearsed, so the warning must stand
    assert not check_status_and_record(dated_but_warned)
    both_dated = _broken(dated_but_warned, "| R2. A timed run against the seeded firm (PRE-B-001) | not run | | |",
                         "| R2. A timed run against the seeded firm (PRE-B-001) | ran | 2026-12-02 | |")
    assert check_status_and_record(both_dated), "every pass is dated and the warning still stands: it must fail"
    warning_removed = _broken(script, "**DRAFTED, NOT REHEARSED.**", "**Ready.**")
    assert check_status_and_record(warning_removed), "the warning is gone and the record is empty: it must fail"
    both = _broken(script, "| not run | | |\n| R2.", "| not run | 2026-12-01 | |\n| R2.")
    assert check_status_and_record(both), "a row cannot be both 'not run' and dated"


def test_the_hygiene_detectors_detect(script):
    """Samples are ASSEMBLED here so no token-shaped literal sits in this file for the repository's secret scan."""
    assert check_hygiene(script + "\nask someone" + "@example.com\n")
    assert check_hygiene(script + "\ncall +91 98765 43210 now\n")
    assert check_hygiene(script + "\n" + "ey" + "J" + "fake-header-aaaa" + "." + "fake-payload-bbbbbb\n")
    assert check_hygiene(script + "\n" + "sb_" + "secret_" + "not-a-key\n")
    assert check_hygiene(script + "\n" + "postgres" + "ql://u:pw" + "@host/db\n")
    assert check_hygiene(script + "\n" + "a" * 45 + "\n")


def test_the_section_and_table_readers_read_what_they_claim():
    sample = "## 1. One\n\n> a\n> b\n\ntext\n\n> c\n\n| H1 | H2 |\n|---|---|\n| x | y |\n\n```\nl1\nl2\n```\n"
    secs = sections(sample)
    assert [(n, t) for n, t, _b in secs] == [(1, "One")]
    assert blockquotes(secs[0][2]) == ["a b", "c"]
    assert tables(secs[0][2]) == [[["H1", "H2"], ["x", "y"]]]
    assert fenced_blocks(secs[0][2]) == ["l1\nl2\n"]
    assert "ok" in voice_of_the_script("# Title\n\n## 1. Never say\n\n```\nin progress\n```\n\nok\n")
    assert "in progress" not in voice_of_the_script("# Title\n\n## 1. Never say\n\n```\nin progress\n```\n\nok\n")
    assert "in progress" in voice_of_the_script("# Title\n\n## 1. Elsewhere\n\nin progress\n")
