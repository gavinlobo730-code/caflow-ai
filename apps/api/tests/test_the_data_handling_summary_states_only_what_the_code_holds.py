"""PRE-B-015(a) — /privacy, "How we handle your data", says only what the code holds.

WHAT WAS WRONG. The marketing footer's Privacy and Terms links both opened /support, which reads as
a missing legal notice on a product that holds a practice's clients' books, and there was no page that
said, in plain sentences, where the data is and where it goes. On 9 October 2026 the owner decided on a
plain factual summary, marked as a summary, with the full notice to follow: the database in Mumbai, the
API in Singapore, the AI providers outside India, no session replay, and what is not claimed. Terms of
service do not exist, so the Terms link is taken out rather than pointed somewhere else.

THE RULE THIS FILE HOLDS, which is not a list of today's sentences: a sentence on that page is either in
the marketing claims ledger (`_marketing_claims.py`, with the test that proves the fact) or in the
`PAGE_FACTS` table below with the test in THIS file that proves it, and nothing is in both and nothing is
in neither. The ledger's own sweep (`test_every_capability_sentence_on_the_marketing_site_is_in_the_claims_ledger.py`)
already requires the first half for every sentence the vocabulary flags; it cannot see the sentences the
vocabulary does not flag (a heading, a disclaimer, "the demo form sends your message by email"), and those
are exactly where a page about data starts to promise more than it knows. So this file reads the page's own
sentences and asks for the second half.

WHAT THE PAGE MAY NOT SAY, as a rule over its sentences (`test_the_summary_leaves_out_the_vocabulary_...`):
anything about what an AI provider does with content once it has it (training, retention: their terms for
the plans in use are unconfirmed, PRE-B-013, and the in-app notices say nothing about it for the same reason),
encryption, security, safety, certification, compliance, a guarantee, cookies, "no third parties", "all
requests", or data staying in India (the API is in Singapore and the browser reads the database directly).
It also names no mailbox, telephone number or address: those are the owner's to confirm (PRE-C-006).

THE FIGURES PARAGRAPH (9 October 2026). The page first said "Some features send only counts drawn from your own
records", held by a test that read another test file for the word "figures-only" and a source file for the
substring "groq_text", which proved neither "counts" nor "only": it passed while the statement analysis sent
the client's revenue, expenses and net profit in rupees for two financial years, and the net margin and the
current ratio with current assets and liabilities in rupees, to Groq, and while the assistant's client brief
sent "Rs <rupees>" for the hub's three rupee tiles. A CA reads "counts" as "no money figure leaves". The AI card
now says what is sent, and each of its four sentences is held by a test that DRIVES THE REAL BUILDER and reads
every message handed to the model (the section "the figures the product works out and sends"): which features
send figures and that they are the engines' own, that rupee amounts are among them, that the assistant's client
brief carries them, and that no client name is attached to any of ten builders (the statement analysis, the
assistant's brief, the digest, the executive dashboard, the copilot's global and client contexts, its client,
compliance and relationship reports, and the firm copilot route). What is read is the builder's output before
the door's PAN/GSTIN replacement, because the sentence is about what the product attaches. One more test ties the
list of builders to the AI-disclosure test's own classification, so a new module that sends the product's figures
fails until somebody drives it here. Not in the list, on purpose: the copilot's workflow report sends the NAMES the
firm gave its workflow templates and the reasons they failed, which are the firm's own words and not a client's
name field; and everything a person types or uploads, which the other card covers.

THE PYTHON PORT OF A TYPESCRIPT RULE. "No session-replay or screen-recording tool" is held for the product by
`apps/web/scripts/the-browser-reports-crashes-without-recording-screens.test.ts`, a TypeScript test. The
claims ledger names only Python tests as proof, and the marketing app has no test runner at all, so the rule
is restated here over BOTH apps: no replay integration or sample rate in the source, no replay or recording
package in either `package.json`. It is a scan of what is in the repository. It cannot see a tool injected at
the edge or switched on in a dashboard, and the ledger's `not_proved` says so.

THE GUARD IS ON THE PYTHON SIDE for the reason `_marketing_copy.py` gives: a test inside the thing it guards
passes whenever the thing and its copy drift together.
"""
from __future__ import annotations

import ast
import asyncio
import functools
import inspect
import json
import os
import re
from datetime import date
from pathlib import Path

import pytest

from tests import _marketing_claims as ledger
from tests._marketing_copy import MARKETING, blank_class_names, blank_comments, sentences_in_source
from tests._marketing_vocabulary import topics_of

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]
WEB = REPO / "apps" / "web"

PAGE_REL = "app/(site)/privacy/page.tsx"
PAGE = MARKETING / PAGE_REL
FOOTER = MARKETING / "components" / "SiteFooter.tsx"
OPEN_ITEMS = REPO / "docs" / "open-items"

# Test names in this file that a PAGE_FACTS entry may point at.
STATUS = "test_the_summary_says_the_notice_is_not_published_while_none_is"
OMISSIONS = "test_the_summary_leaves_out_the_vocabulary_of_what_nobody_has_checked"
DEMO_FORM = "test_the_demo_form_sends_an_email_and_writes_no_row"
FIGURES = "test_the_features_that_send_figures_send_what_the_engines_computed_and_nothing_typed"
RUPEES = "test_the_statement_analysis_sends_rupee_amounts_for_two_years"
ASSISTANT_FIGURES = "test_the_assistant_is_given_a_clients_rupee_figures_and_not_its_name"
NO_CLIENT_NAME = "test_no_client_name_is_attached_to_a_figure_the_product_sends"
UNNAMED = "test_the_services_the_summary_leaves_unnamed_are_in_the_product"
SUPPORT_LINK = "test_the_support_page_the_summary_points_to_exists_and_the_page_prints_no_address"

HEADING = "heading"

#: Every sentence on the page the vocabulary does NOT flag, and what holds it. A `heading` states no fact (a
#: title, a subtitle, a fragment of a headline) and is held by being unflagged: a heading that makes a claim
#: would be flagged and would have to be in the ledger. Everything else names a test in this file.
PAGE_FACTS: dict[str, str] = {
    # titles, subtitles and the halves of headlines
    "How we handle your data": HEADING,
    "A plain summary of where PracticeSync keeps your firm's records, where the application runs and which AI providers receive content.": HEADING,
    "This is a short, factual summary of where your records are kept and where they go.": HEADING,
    "are, and where they go.": HEADING,
    "The places your firm's information is stored, worked on and sent to.": HEADING,
    "What is replaced on the way": HEADING,
    "and the demo form.": HEADING,
    "What the product and this website do not do, and what the demo form does.": HEADING,
    "If you book a demo": HEADING,
    "A short list of what is deliberately left out, so nothing here reads as more than it is.": HEADING,
    # what the page says it is: true only while no notice and no terms are published
    "It is a summary, not the full privacy notice.": STATUS,
    "It is a summary and not our full privacy notice, which is still to come.": STATUS,
    "This page is a summary.": STATUS,
    "It is not a privacy notice or terms of service.": STATUS,
    # what it declines to say
    "It does not describe what the AI providers do with content once they receive it.": OMISSIONS,
    "It does not cover how long records are kept or how they are protected in storage.": OMISSIONS,
    # the figures paragraph of the AI card (whose title gives the destination): four facts, each driven through
    # the real prompt builders (see the section "the figures the product works out and sends" below)
    "Some features also send figures the product has already worked out from your records, such as counts, totals and ratios.": FIGURES,
    "Some of those figures are rupee amounts, such as the revenue, expenses and profit the statement analysis sends for two financial years.": RUPEES,
    "When you ask the assistant about one client, it is also given figures from that client's records, including rupee amounts.": ASSISTANT_FIGURES,
    "The product attaches no client name to these figures.": NO_CLIENT_NAME,
    # facts the vocabulary does not flag
    "The form sends what you type to our team by email.": DEMO_FORM,
    "It does not write to the product's database.": DEMO_FORM,
    "It does not name every service the product uses; email delivery and error reporting are two it leaves out.": UNNAMED,
    "For a question about your data, see how to reach us on the Support page.": SUPPORT_LINK,
}


# ── reading the page ─────────────────────────────────────────────────────────

def page_sentences_of(source: str, min_words: int) -> frozenset[str]:
    """The sentences a visitor reads in a page's source. A class list is a string literal and the extractor would read
    it as copy, so the value of every `className` is blanked first: WHERE a string sits decides that it is styling,
    never what it looks like. (The first version of this guard dropped any sentence holding a word-dash-digit token,
    `text-[15px]` or `gap-x-12` by its shape, and so also dropped `tier-1`, `aes-256` and `ap-south-1` in prose: a
    sentence about what a provider does with content, written with one of them, passed every test here.)"""
    return frozenset(sentences_in_source(blank_class_names(source), min_words))


@functools.lru_cache(maxsize=None)
def _page_sentences(min_words: int) -> frozenset[str]:
    return page_sentences_of(PAGE.read_text(encoding="utf-8"), min_words)


def disagreement(sentences, facts) -> tuple[set[str], set[str]]:
    """(unflagged sentences the table does not hold, table entries no unflagged sentence matches). Both empty is agreement."""
    unflagged = {s for s in sentences if not topics_of(s)}
    return unflagged - set(facts), set(facts) - unflagged


def _code(path: Path) -> str:
    return blank_comments(path.read_text(encoding="utf-8"))


def _tests_defined_here() -> set[str]:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


# ═══ every sentence is held, in the ledger or in the table, and not in both ═══════════════════════

def test_the_page_exists_and_the_scan_reads_it():
    assert PAGE.is_file(), "the privacy summary is gone: the footer's Privacy link opens nothing"
    sentences = _page_sentences(2)
    assert len(sentences) >= 25, f"only {len(sentences)} sentences read from the page: the scan is broken"
    assert any(topics_of(s) for s in sentences), "no sentence on the page is a claim: the vocabulary stopped seeing it"


def test_every_unflagged_sentence_is_in_the_table_and_the_table_holds_nothing_the_page_lacks():
    """The ledger takes the sentences the vocabulary flags. This takes the rest."""
    unheld, stale = disagreement(_page_sentences(4), PAGE_FACTS)
    assert not unheld and not stale, (
        "the page and PAGE_FACTS disagree.\n"
        f"on the page and in neither the ledger nor the table: {sorted(unheld)}\n"
        f"in the table and not on the page as written: {sorted(stale)}\n"
        "A sentence added to the page names the test that holds it; a reworded one is read against its proof again. "
        "A class list kept in a constant is read as copy: write it in the className attribute, where it is styling.")


def test_nothing_is_in_both_the_ledger_and_the_table():
    in_ledger = {says.text for c in ledger.CLAIMS for says in c.says if PAGE_REL in says.where}
    assert in_ledger, "no ledger sentence is on the privacy page"
    both = in_ledger & set(PAGE_FACTS)
    assert not both, f"in the ledger AND the table: {sorted(both)}"


def test_no_sentence_on_the_page_rests_on_an_unproven_claim():
    held_by = {}
    for c in ledger.CLAIMS:
        for says in c.says:
            if PAGE_REL in says.where:
                held_by.setdefault(says.text, []).append(c)
    weak = {t: [c.id for c in cs] for t, cs in held_by.items() if any(c.status == ledger.UNPROVEN for c in cs)}
    assert not weak, f"the page promises something the ledger calls unproven: {weak}"


def test_every_table_entry_names_a_test_in_this_file_or_is_a_heading():
    here = _tests_defined_here()
    for sentence, proof in PAGE_FACTS.items():
        assert proof == HEADING or proof in here, f"{sentence!r} points at {proof!r}, which this file does not define"
    assert {p for p in PAGE_FACTS.values() if p != HEADING} <= here


def test_a_heading_makes_no_claim():
    for sentence in PAGE_FACTS:
        assert not topics_of(sentence), f"{sentence!r} is a claim and belongs in the ledger, not the table"


# ═══ what the page must not say ═══════════════════════════════════════════════════════════════════

#: Words that would turn a summary into a promise nobody has checked. Each is a thing the repository says it
#: has NOT confirmed or cannot show; the reason is beside it, so a person loosening one reads why.
BANNED = (
    (r"\btrain\w*", "what a provider does with content (PRE-B-013, unconfirmed)"),
    (r"\bretain\w*|\bretention\b", "what a provider does with content, or a retention period nobody has set out"),
    (r"\bencrypt\w*", "no citation for encryption at rest is held (CLAUDE.md)"),
    (r"\bsecur\w*", "a 'secure' claim is an assurance nothing here proves"),
    (r"\bsafe\w*", "an assurance"),
    (r"\bcertif\w*", "no certification is held"),
    (r"\bcompl(?:iant|iance)\b|\bgdpr\b|\bsoc\s?2\b|\biso\s?27001\b", "no compliance standard is claimed"),
    (r"\bguarant\w*", "an assurance"),
    (r"\bcookies?\b", "whether the hosting platform sets one cannot be read from the source"),
    (r"\bthird[- ]part(?:y|ies)\b", "a sub-processor is used (mail, error reporting): 'none' is false"),
    (r"\ball (?:requests|data|traffic)\b|\bonly in india\b|\bstays? in india\b|\bdata residency\b|\bhosted in india\b",
     "the API is in Singapore and the browser reads the database directly: nothing is 'all' or 'only'"),
    (r"\bopenai\b|\banthropic\b|\bclaude\b|\bmistral\b|\bcohere\b", "a provider the code does not call"),
)


def _ban_hits(sentences) -> list[str]:
    return [f"{s!r}: {why}" for s in sentences for rx, why in BANNED if re.search(rx, s, re.I)]


def test_the_summary_leaves_out_the_vocabulary_of_what_nobody_has_checked():
    sentences = _page_sentences(2)
    assert len(sentences) >= 25
    hits = _ban_hits(sentences)
    assert not hits, "the summary says what the repository cannot back:\n  " + "\n  ".join(hits)


@pytest.mark.parametrize("sentence", [
    "Your content is never used to train a model.",
    "Providers keep content for thirty days, then it is retained no longer.",
    "Records are encrypted at rest.",
    "Your data is secure with us.",
    "We use no third parties.",
    "We set no cookies.",
    "All requests go through Singapore.",
    "Your data stays in India.",
    "We are SOC 2 certified.",
    "Content goes to OpenAI.",
])
def test_the_ban_would_catch_what_it_is_for(sentence):
    assert _ban_hits([sentence]), f"{sentence!r} would pass the summary"


# ═══ the reading of the page does not look past prose, whatever the prose contains ═══════════════

#: A page as a person would write one: styling in className (every form React allows) and sentences in constants and
#: in JSX text, four of them holding a token that has the SHAPE of a utility class (a word, a dash, a digit). The
#: styling is the page's real classes (the page's own are in `app/(site)/privacy/page.tsx`).
_SYNTHETIC_PAGE = '''
const FACTS = [
  { title: "Terms", body: "Providers never train on your content under tier-1 plans and delete it after 30 days." },
  { title: "Region", body: "Content is kept in ap-south-1 and never leaves it." },
  { title: "Cipher", body: "Records are protected with aes-256 and stay secure." },
  { title: "Hash", body: "Content is hashed with sha-256 before it is retained." },
];
export default function Page() {
  return (
    <div className={`${a.variable} ${b.variable} font-manrope text-[15px]`}>
      <div className="mt-12 grid gap-x-12 gap-y-9 sm:grid-cols-2">
        <h3 className="font-display text-[22px] italic text-brand-dark">A heading with a short title</h3>
        <p className={cn("mt-2 text-[15px] leading-relaxed", on && "hover:text-brand-dark underline-offset-2")}>
          This is a plain sentence about nothing in particular.
        </p>
        <li className={'max-w-[60ch] text-[15px] leading-relaxed text-slate-600'}>Another plain sentence, in a list item.</li>
      </div>
    </div>
  );
}
'''

_CLASS_TOKENS = ("gap-x-12", "text-[15px]", "text-[22px]", "sm:grid-cols-2", "hover:text-brand-dark", "underline-offset-2",
                 "max-w-[60ch]", "leading-relaxed", "font-manrope", "font-display", "text-slate-600")
_PROSE_WITH_UTILITY_SHAPED_TOKENS = (
    "Providers never train on your content under tier-1 plans and delete it after 30 days.",
    "Content is kept in ap-south-1 and never leaves it.",
    "Records are protected with aes-256 and stay secure.",
    "Content is hashed with sha-256 before it is retained.",
)


def test_prose_holding_a_utility_shaped_token_is_still_read_and_class_lists_are_not():
    sentences = page_sentences_of(_SYNTHETIC_PAGE, 2)
    for prose in _PROSE_WITH_UTILITY_SHAPED_TOKENS:
        assert prose in sentences, f"{prose!r} was looked past: a sentence is told from a class list by where it sits"
    assert "This is a plain sentence about nothing in particular." in sentences
    assert "Another plain sentence, in a list item." in sentences
    leaked = [s for s in sentences if any(tok in s for tok in _CLASS_TOKENS)]
    assert not leaked, f"a class list was read as copy: {leaked}"


def test_prose_holding_a_utility_shaped_token_is_scanned_for_the_banned_vocabulary():
    hits = _ban_hits(page_sentences_of(_SYNTHETIC_PAGE, 2))
    for word, prose in (("train", _PROSE_WITH_UTILITY_SHAPED_TOKENS[0]),
                        ("secure", _PROSE_WITH_UTILITY_SHAPED_TOKENS[2]),
                        ("retain", _PROSE_WITH_UTILITY_SHAPED_TOKENS[3])):
        assert any(h.startswith(repr(prose)) for h in hits), f"{word!r} in {prose!r} was not scanned"


def test_prose_holding_a_utility_shaped_token_is_not_waved_through_by_the_table():
    unheld, stale = disagreement(page_sentences_of(_SYNTHETIC_PAGE, 4), {})
    for prose in _PROSE_WITH_UTILITY_SHAPED_TOKENS:
        assert prose in unheld, f"{prose!r} is on the page, unflagged, and the table would not have noticed it"
    assert not stale


@pytest.mark.parametrize("source", [
    '<p className="mt-2 text-[15px] leading-relaxed">x</p>',
    "<p className='mt-2 text-[15px] leading-relaxed'>x</p>",
    '<p className={"mt-2 text-[15px] leading-relaxed"}>x</p>',
    '<p className={`mt-2 ${a.b} text-[15px] leading-relaxed`}>x</p>',
    '<p className={cn("mt-2 text-[15px]", on && "leading-relaxed")}>x</p>',
    '<p className={cn(`mt-2 ${f("}")} text-[15px]`, { "leading-relaxed": on })}>x</p>',
    '<p className = "mt-2 text-[15px] leading-relaxed">x</p>',
    'const props = { className: "mt-2 text-[15px] leading-relaxed" };',
    'const props = { className: `mt-2 ${x} text-[15px] leading-relaxed` };',
    '<p\n  className={\n    "mt-2 text-[15px] leading-relaxed"\n  }\n>x</p>',
])
def test_every_way_of_writing_a_class_list_is_blanked(source):
    blanked = blank_class_names(source)
    for token in ("mt-2", "text-[15px]", "leading-relaxed"):
        assert token not in blanked, f"{token!r} survived in {blanked!r}"
    assert len(blanked) == len(source), "blanking moves nothing: the text around it keeps its place"


@pytest.mark.parametrize("source", [
    '<a title="Plans on tier-1 hosts" aria-label="ap-south-1 region">x</a>',
    "type Props = { className?: string; id: string };",
    "type Props = { className: string };",
    'const note = "Set the className to something sensible for tier-1 plans.";',
    '<p className={cn("a")}>Providers never train on tier-1 plans.</p>',
])
def test_what_is_not_a_class_list_is_left_alone(source):
    blanked = blank_class_names(source)
    for kept in ("tier-1", "ap-south-1", "string"):
        if kept in source:
            assert kept in blanked, f"{kept!r} was blanked out of {source!r}"


def test_a_commented_out_element_is_not_scanned_and_a_broken_one_does_not_hang():
    assert "never train" not in " ".join(page_sentences_of('// <p>Providers never train on tier-1 plans.</p>\nconst a = 1;', 2))
    for broken in ('<p className={cn("a"', '<p className="unterminated\n<p>after</p>', "<p className={`a ${b", '<p className='):
        blank_class_names(broken)  # must return


def test_the_page_prints_no_address_and_names_no_exact_region_it_cannot_confirm():
    """No mailbox, no telephone number, no postal address, no hosting-region code. The owner confirms each
    (PRE-C-006) and a value typed from memory is the thing this page must not carry. The Support page is
    where a person is sent."""
    code = _code(PAGE)
    assert "CONTACT" not in code, "the page reads the site's contact details"
    assert not re.search(r"mailto:|tel:|[\w.+-]+@[\w-]+\.[\w.-]+|\+\d{2}[\s\d-]{8,}", code), "an address or number is on the page"
    assert not re.search(r"\b[a-z]{2}-[a-z]+-\d\b", code), "a hosting region code is on the page"
    assert not re.search(r"\b(?:street|road|floor|nagar|pin code)\b", code, re.I), "a postal address is on the page"


def test_the_providers_the_page_names_are_the_two_doors_the_code_has():
    names = dict(re.findall(r'^\s*(groq|gemini):\s*"([^"]+)"', (WEB / "lib" / "ai" / "disclosure.ts").read_text(encoding="utf-8"), re.M))
    assert set(names) == {"groq", "gemini"}, "the in-app provider names moved: read the page's AI sentences again"
    text = " ".join(_page_sentences(2))
    for provider, display in names.items():
        assert display in text, f"the page does not name {display}, which the code sends content to"
        door = API / "domain" / "ai" / f"{'groq_text' if provider == 'groq' else 'gemini_vision'}.py"
        assert door.is_file(), f"{door.name} is gone: what does the page's AI sentence describe now?"


def test_the_database_the_page_names_is_the_one_the_code_talks_to():
    """'Supabase hosts the database' is a commitment about WHERE (the Mumbai part cannot be read), but that it is
    Supabase is the code's: the client module, the deploy manifest and the browser all name it."""
    assert (API / "core" / "supabase_client.py").is_file()
    manifest = (REPO / "render.yaml").read_text(encoding="utf-8")
    assert "SUPABASE_URL" in manifest and "SUPABASE_SERVICE_ROLE_KEY" in manifest
    assert "region: singapore" in manifest, "the API's region moved: the page says Singapore"


# ═══ the sentences that depend on the notice not being published yet ═══════════════════════════════

_NOTICE_ROUTES = ("terms", "terms-of-service", "terms-and-conditions", "tos", "privacy-notice", "privacy-policy", "legal")


def _routes_named(app_dir: Path) -> list[str]:
    found = []
    for p in app_dir.rglob("page.tsx"):
        parts = [x for x in p.relative_to(app_dir).parent.parts if not (x.startswith("(") and x.endswith(")"))]
        found += [x for x in parts if x.lower() in _NOTICE_ROUTES]
    return found


def test_the_summary_says_the_notice_is_not_published_while_none_is():
    """'It is not a privacy notice or terms of service … which is still to come.' is true while no such page exists
    and while the work to write one is an open item. Publishing either makes the sentence false, and this is the test
    that makes somebody reword the page the same day."""
    assert _routes_named(MARKETING / "app") == [], "a terms or notice page exists: the summary's status sentences are stale"
    assert _routes_named(WEB / "app") == [], "the product has a terms or notice page: the summary's status sentences are stale"
    ledger_text = (OPEN_ITEMS / "post-demo-B-ours.md").read_text(encoding="utf-8")
    assert re.search(r"^- \*\*POST-B-259\*\*", ledger_text, re.M), (
        "POST-B-259 (publish a real Privacy Notice and Terms of Service) is closed: the summary's 'still to come' "
        "sentences were written while it was open. Rewrite the page, then this test.")


# ═══ the facts behind the unflagged sentences ═════════════════════════════════════════════════════

def test_the_demo_form_sends_an_email_and_writes_no_row():
    src = (API / "routers" / "demo_request.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    reaches_a_database = [i for i in imported if re.search(r"supabase|db_provider|repositor|\bdb\b|sqlalchemy|psycopg", i)]
    assert not reaches_a_database, f"the demo form's router imports {reaches_a_database}: 'does not write to the product's database' is stale"
    writes = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in ("table", "insert", "upsert", "rpc")]
    assert not writes, f"the demo form's router calls {writes}"
    sends = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "_send" and isinstance(n.func.value, ast.Name) and n.func.value.id == "email_service"]
    assert sends, "the demo form no longer sends its message by email: 'sends what you type to our team by email' is stale"


# ═══ the figures the product works out and sends ═════════════════════════════════════════════════
#
# WHAT WAS WRONG. The page said "Some features send only counts drawn from your own records." Its proof read
# ANOTHER test file for the word "figures-only" and a source file for the substring "groq_text", so it proved
# neither "counts" nor "only". A CA reads "counts" as "no money figure leaves", and two features send rupee
# amounts: the statement analysis puts the client's revenue, expenses and net profit in rupees for two financial
# years, and the net margin and the current ratio with current assets and liabilities in rupees, into the
# request to Groq (domain/financial_analysis_service.py, generate_statement_analysis), and the assistant's
# client brief sends "Rs <rupees>" for the three hub tiles whose unit is paise (domain/ai/client_brief.py,
# _figure). Every test below DRIVES THE REAL BUILDER and reads what was handed to the model; none greps a
# source file for a word.
#
# THE LAYER. `groq_text.chat` is replaced by a function that records its messages, so what is read is what the
# builder asked the one door to send, BEFORE the door's PAN/GSTIN replacement: the page's "no client name"
# sentence is about what the product attaches, and a name is not something the door removes. The planted
# strings below are placed where a regression would read a name from (a field of the data the builder is
# handed, a ledger account's name, a task title, a narration), and none may reach a model.

LEGAL_NAME = "Zyxwvu Holdings Private Limited"
TRADING_NAME = "Quibble Traders"
OWNER_PAN, OWNER_GSTIN = "AAAAA0000A", "27AAAAA0000A1Z5"
OWNER_DOMAIN = "zyxwvu-holdings.example"
ACCOUNT_NAMES = ("Loan from Wobblefoot Sundaram", "Plumtree Exports receivable", "Hollis Gantry rent")
TASK_TITLE = "Chase Plumtree Exports for the March bills"
CHECK_NAME = "Wobblefoot ledger tie-out"

#: Everything a fixture plants that must never be handed to a model by a builder of figures.
PLANTED = (LEGAL_NAME, TRADING_NAME, "Zyxwvu", "Quibble", OWNER_PAN, OWNER_GSTIN, OWNER_DOMAIN,
           *ACCOUNT_NAMES, TASK_TITLE, CHECK_NAME)


@pytest.fixture
def sent(monkeypatch):
    """Every list of messages any feature hands to the Groq door. The door itself is replaced, so nothing is
    sent and nothing is redacted: this is the builder's own output."""
    from domain.ai import groq_text

    handed: list[list[dict]] = []

    async def record(messages, **_kw):
        handed.append([dict(m) for m in messages])
        return "A short reply.", 5

    monkeypatch.setattr(groq_text, "chat", record)
    monkeypatch.setenv("GROQ_API_KEY", "k")
    return handed


def _text(messages: list[dict]) -> str:
    return "\n".join(str(m.get("content", "")) for m in messages)


# ── the drivers: each one runs a REAL builder against data that carries the planted names ─────────

def _ledger_line(name: str, paise: int, **extra) -> dict:
    return {"account_name": name, "balance_paise": paise, **extra}


def _statement_analysis(monkeypatch) -> None:
    import domain.financial_analysis_service as fa

    monkeypatch.setattr(fa, "_GROQ_API_KEY", "k")
    pl = {"client_name": LEGAL_NAME, "legal_name": TRADING_NAME,
          "revenue": {"lines": [_ledger_line(ACCOUNT_NAMES[1], 12_00_000_00)], "total_paise": 12_00_000_00},
          "operating_expenses": {"lines": [_ledger_line(ACCOUNT_NAMES[2], 9_00_000_00)], "total_paise": 9_00_000_00},
          "net_profit_paise": 3_00_000_00}
    prev = {"revenue": {"lines": [], "total_paise": 10_00_000_00},
            "operating_expenses": {"lines": [], "total_paise": 8_50_000_00}, "net_profit_paise": 1_50_000_00}
    bs = {"assets": [{"lines": [_ledger_line(ACCOUNT_NAMES[1], 6_00_000_00, account_type="Asset",
                                             account_subtype="Receivable")]}],
          "liabilities": [{"lines": [_ledger_line(ACCOUNT_NAMES[0], 2_00_000_00, account_type="Liability",
                                                  account_subtype="Payable")]}]}
    asyncio.run(fa.generate_statement_analysis(pl, bs, prev, "2026-27", "2025-26", firm_id="f1", user_id="u1"))


#: The hub's own tiles for one client, as `services.hub_service.hub` shapes them (labels and questions are
#: `domain/hub/tiles.py`'s): one in rupees and one count. Extra keys are planted: a builder that read a name
#: out of the payload would be caught.
def _hub_payload() -> dict:
    return {"client_name": LEGAL_NAME, "legal_name": TRADING_NAME, "tiles": [
        {"id": "sales", "label": "Sales", "question": "Overdue from customers", "unit": "paise",
         "answerable": True, "signal": 1_18_000_00},
        {"id": "gst", "label": "GST", "question": "Returns prepared and not yet filed", "unit": "count",
         "answerable": True, "signal": 3},
    ]}


def _assistant(monkeypatch) -> None:
    import core.authz as authz
    import routers.assistant as asst
    import services.hub_service as hub_service
    from repositories.client_repository import client_repo

    monkeypatch.setattr(authz, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(client_repo, "find_by_id", lambda *a, **k: {
        "id": "c1", "legal_name": LEGAL_NAME, "client_name": TRADING_NAME, "entity_type": "Private Limited",
        "pan": OWNER_PAN, "gstin": OWNER_GSTIN})
    monkeypatch.setattr(hub_service, "hub", lambda *a, **k: _hub_payload())
    user = {"id": "u1", "firm_id": "f1", "auth_user_id": "u1", "role": "Executive"}
    request = asst.AssistantRequest(question="What is outstanding for this client?", client_id="c1")
    asyncio.run(asst.assistant(request, user))


def _digest_items() -> list[dict]:
    """The digest's four sections, built by the engines' own functions from rows that carry the planted names."""
    from domain.practice import digest

    risk = [{"client_id": "c1", "client_name": LEGAL_NAME, "overdue_count": 3, "due_soon_count": 2},
            {"client_id": "c2", "client_name": TRADING_NAME, "overdue_count": 1, "due_soon_count": 0}]
    names = {r["client_id"]: r["client_name"] for r in risk}
    items = digest.compliance_items(risk)
    items.append(digest.task_item(
        [{"client_id": "c1", "title": TASK_TITLE, "assignee_id": "u1"},
         {"client_id": "c2", "title": TASK_TITLE}], "u1", names))
    items.append(digest.findings_item(
        {"c1": {"id": "r1"}}, [{"client_id": "c1", "severity": "critical", "check_name": CHECK_NAME}], names))
    return digest.ordered(items)


def _digest(monkeypatch) -> None:
    from services import digest_service

    digest_service.reset_narration_cache()
    asyncio.run(digest_service.narrate("f1", _digest_items(), date(2026, 10, 9), user_id="u1"))


# The firm's own records, as the copilot's builders read them. Two clients share a PAN and an email domain
# (what the relationship report counts), both carry names, and a task and a compliance record each.
_CLIENTS = [
    {"id": "c1", "client_name": LEGAL_NAME, "legal_name": LEGAL_NAME, "pan": OWNER_PAN, "gstin": OWNER_GSTIN,
     "email": f"owner@{OWNER_DOMAIN}", "status": "active", "health_score": 30, "lifecycle_stage": "retained",
     "entity_type": "Private Limited"},
    {"id": "c2", "client_name": TRADING_NAME, "legal_name": TRADING_NAME, "pan": OWNER_PAN, "gstin": None,
     "email": f"accounts@{OWNER_DOMAIN}", "status": "at_risk", "health_score": 55, "lifecycle_stage": "retained",
     "entity_type": "Proprietorship"},
]


class _Clients:
    def find_all(self, **_kw):
        return list(_CLIENTS)

    def find_by_id(self, client_id, **_kw):
        return next((c for c in _CLIENTS if c["id"] == client_id), None)


class _Tasks:
    def find_overdue(self, **_kw):
        return [{"id": "t1", "client_id": "c1", "title": TASK_TITLE}, {"id": "t2", "client_id": "c2", "title": TASK_TITLE}]


class _Compliance:
    def find_all(self, **_kw):
        return [{"client_id": "c1", "status": "Overdue", "due_date": "2026-01-01", "compliance_type": "GSTR-3B"},
                {"client_id": "c2", "status": "Overdue", "due_date": "2026-01-01", "compliance_type": "GSTR-1"}]


class _Workflows:
    def list_failures(self, firm_id, **_kw):
        return []

    list_approvals = list_failures

    def list_templates(self, firm_id, **_kw):
        return [{"is_active": True}]

    def client_ids_for_instances(self, firm_id, ids):
        return {}

    def get_analytics(self, firm_id):
        return []


class _CopilotRepo:
    def __init__(self):
        self.rows: list[dict] = []

    def add_message(self, firm_id, conversation_id, role, content, **_kw):
        row = {"role": role, "content": content}
        self.rows.append(row)
        return row

    def list_messages(self, conversation_id, limit=20):
        return list(self.rows)

    def get_summary(self, *_a, **_k):
        return None

    def upsert_summary(self, firm_id, kind, entity, row):
        return row


def _copilot(monkeypatch):
    """The copilot service wired to the firm's records above; `groq_text.chat` is already recording."""
    import domain.ai_copilot_service as mod

    monkeypatch.setattr(mod, "_GROQ_API_KEY", "k")
    monkeypatch.setattr(mod, "_get_client_repo", lambda: _Clients())
    monkeypatch.setattr(mod, "_get_task_repo", lambda: _Tasks())
    monkeypatch.setattr(mod, "_get_compliance_records_repo", lambda: _Compliance())
    monkeypatch.setattr(mod, "_get_workflow_repo", lambda: _Workflows())
    svc = mod.ai_copilot_service
    monkeypatch.setattr(svc, "_repo", _CopilotRepo())
    return svc


def _executive_dashboard(monkeypatch) -> None:
    svc = _copilot(monkeypatch)
    asyncio.run(svc.get_executive_dashboard("f1", allowed_client_ids={"c1", "c2"}))


def _copilot_chat(context_type: str, context_id):
    def drive(monkeypatch) -> None:
        svc = _copilot(monkeypatch)
        asyncio.run(svc.chat(firm_id="f1", user_id="u1", conversation_id="conv-1", user_message="What is due?",
                             context_type=context_type, context_id=context_id, allowed_client_ids=None))
    return drive


def _client_intelligence(monkeypatch) -> None:
    asyncio.run(_copilot(monkeypatch).get_client_intelligence("f1", "c1"))


def _compliance_intelligence(monkeypatch) -> None:
    asyncio.run(_copilot(monkeypatch).get_compliance_intelligence("f1", allowed_client_ids=None))


def _relationship_intelligence(monkeypatch) -> None:
    asyncio.run(_copilot(monkeypatch).get_relationship_intelligence("f1", allowed_client_ids=None))


def _firm_copilot_route(monkeypatch) -> None:
    import routers.ai_copilot as cp
    from repositories.client_repository import client_repo

    monkeypatch.setattr(cp, "check_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(client_repo, "find_all", lambda *a, **k: list(_CLIENTS))
    user = {"id": "u1", "firm_id": "f1", "auth_user_id": "u1", "role": "Partner"}
    asyncio.run(cp.copilot_chat(request=None, body=cp.CopilotRequest(message="What is due?"), current_user=user))


#: feature -> (the module it lives in, what runs it, a figure it MUST be seen to send). The last is what keeps
#: the no-name test from passing on an empty prompt: a builder that sent nothing would contain no name.
FIGURE_FEATURES = {
    "statement_analysis": ("domain/financial_analysis_service.py", _statement_analysis, "Revenue: Rs 12,00,000.00"),
    "assistant_client_brief": ("routers/assistant.py", _assistant, "Overdue from customers): Rs 1,18,000"),
    "digest": ("services/digest_service.py", _digest, "4 filings overdue across 2 clients"),
    "executive_dashboard": ("domain/ai_copilot_service.py", _executive_dashboard, "Clients in view: 2"),
    "copilot_global": ("domain/ai_copilot_service.py", _copilot_chat("global", None), "TOTAL CLIENTS: 2"),
    "copilot_client": ("domain/ai_copilot_service.py", _copilot_chat("client", "c1"), "HEALTH SCORE: 30"),
    "client_intelligence": ("domain/ai_copilot_service.py", _client_intelligence, "Health Score: 30/100"),
    "compliance_intelligence": ("domain/ai_copilot_service.py", _compliance_intelligence, "Overdue filings: 2"),
    "relationship_intelligence": ("domain/ai_copilot_service.py", _relationship_intelligence,
                                  "PANs appearing across multiple entities: 1"),
    "firm_copilot_route": ("routers/ai_copilot.py", _firm_copilot_route, "Clients: 2"),
}


def _asked_the_model(sent, name: str, monkeypatch) -> str:
    FIGURE_FEATURES[name][1](monkeypatch)
    assert sent, f"{name}: the model was never called, so nothing was proved"
    return _text(sent[0])


# ── 1. "Some features send figures the product has already worked out ... counts, totals and ratios" ──

#: What the statement analysis may say after its one fixed sentence: a labelled rupee total for a financial
#: year, a percentage and a ratio. Nothing else, so a line of free text (an account's name) cannot be one.
_FIGURE_LINE = re.compile(
    r"^(FY \d{4}-\d{2} (Revenue|Expenses|Net Profit): Rs -?[\d,]+\.\d{2}"
    r"|Net margin: -?\d+(\.\d)?%"
    r"|Current ratio: -?\d+(\.\d+)?x \(current assets Rs -?[\d,]+\.\d{2} / current liabilities Rs -?[\d,]+\.\d{2}\))$")


def test_the_features_that_send_figures_send_what_the_engines_computed_and_nothing_typed(sent, monkeypatch):
    # Totals and ratios: after one fixed sentence, the statement analysis sends eight labelled figures and
    # nothing else, and the percentage and the ratio are the engine's (3 / 12 lakh, 6 lakh / 2 lakh).
    _asked_the_model(sent, "statement_analysis", monkeypatch)
    lines = sent[0][-1]["content"].split("\n")
    assert lines[0] == "Here are this client's financial figures:"
    figures = lines[1:]
    assert len(figures) == 8 and all(_FIGURE_LINE.match(line) for line in figures), figures
    assert "Net margin: 25.0%" in figures
    assert "Current ratio: 3.0x (current assets Rs 6,00,000.00 / current liabilities Rs 2,00,000.00)" in figures

    # Counts: after the date, the digest sends one line per section and each is the engine's own headline for
    # the fixture's rows (3 + 1 overdue filings over 2 clients, 2 due, 2 overdue tasks of which 1 is the
    # caller's, 1 critical finding), with no client and no task in it.
    sent.clear()
    _asked_the_model(sent, "digest", monkeypatch)
    lines = sent[0][-1]["content"].split("\n")
    assert lines[0] == "As at 09 October 2026:"
    assert set(lines[1:]) == {
        "- Overdue filings (needs attention): 4 filings overdue across 2 clients",
        "- Books-integrity findings (needs attention): 1 critical and 0 other books-integrity finding across 1 client in the latest checks",
        "- Filings due in 7 days (needs attention): 2 filings due within the next 7 days across 1 client",
        "- Overdue tasks (needs attention): 2 tasks overdue — 1 assigned to you, 1 with nobody assigned",
    }


# ── 2. "Some of those figures are rupee amounts ... the statement analysis ... two financial years" ──

def test_the_statement_analysis_sends_rupee_amounts_for_two_years(sent, monkeypatch):
    from domain.money_text import rupees_paise

    text = _asked_the_model(sent, "statement_analysis", monkeypatch)
    for label, paise in (("FY 2026-27 Revenue", 12_00_000_00), ("FY 2026-27 Expenses", 9_00_000_00),
                         ("FY 2026-27 Net Profit", 3_00_000_00), ("FY 2025-26 Revenue", 10_00_000_00),
                         ("FY 2025-26 Expenses", 8_50_000_00), ("FY 2025-26 Net Profit", 1_50_000_00)):
        assert f"{label}: Rs {rupees_paise(paise)}" in text, f"{label} is not sent as a rupee amount"
    assert "12,00,000.00" in text, "the amount is grouped the Indian way"
    assert "(current assets Rs 6,00,000.00 / current liabilities Rs 2,00,000.00)" in text


# ── 3. "When you ask the assistant about one client, it is also given figures ..., including rupee amounts" ──

def test_the_assistant_is_given_a_clients_rupee_figures_and_not_its_name(sent, monkeypatch):
    everything = _asked_the_model(sent, "assistant_client_brief", monkeypatch)
    briefs = [m["content"] for m in sent[0] if m["role"] == "system" and m["content"].startswith("CLIENT CONTEXT")]
    assert len(briefs) == 1, "no client brief was attached, so the rest of this proves nothing"
    brief = briefs[0]
    assert brief.startswith("CLIENT CONTEXT — this client (Private Limited)"), brief
    assert "- Sales (Overdue from customers): Rs 1,18,000" in brief, "a rupee amount from the client's records is sent"
    assert "- GST (Returns prepared and not yet filed): 3" in brief
    assert not [p for p in PLANTED if p in everything]


def test_the_client_brief_has_no_parameter_a_name_could_arrive_through():
    from domain.ai.client_brief import build_client_brief

    assert list(inspect.signature(build_client_brief).parameters) == ["entity_type", "hub_payload"]
    brief = build_client_brief("Private Limited", _hub_payload())
    assert brief and not [p for p in PLANTED if p in brief], "a name planted in the hub payload reached the brief"


# ── 4. "The product attaches no client name to these figures" ──────────────────────────────────────

@pytest.mark.parametrize("name", sorted(FIGURE_FEATURES))
def test_no_client_name_is_attached_to_a_figure_the_product_sends(name, sent, monkeypatch):
    everything = _asked_the_model(sent, name, monkeypatch)
    must_see = FIGURE_FEATURES[name][2]
    assert must_see in everything, f"{name}: the prompt no longer carries {must_see!r}, so this is not the builder it was"
    leaked = [p for p in PLANTED if p in everything]
    assert not leaked, f"{name}: a client's name, identifier or free text reached the prompt: {leaked}"


def test_the_workflow_report_sends_the_names_the_firm_gave_its_workflows_and_no_client_name(sent, monkeypatch):
    """The one builder left out of the list above, and why. The copilot's workflow report names the firm's failing
    and slow workflow TEMPLATES and counts their failure reasons: words the firm typed when it built them. They are
    not a client's name field and the product adds none, which is the sentence the page makes; but a firm that
    named a template after a client sends that name, and the page's figures paragraph does not claim otherwise because
    it does not list this report. If this stops being true, reword the header of this file."""
    class _Failing(_Workflows):
        def get_analytics(self, firm_id):
            return [{"template_name": "Onboarding checklist", "failed": 2, "avg_duration_ms": 4_000_000}]

        def list_failures(self, firm_id, **_kw):
            return [{"instance_id": "i1", "error_type": "step timed out"}]

    import domain.ai_copilot_service as mod

    svc = _copilot(monkeypatch)
    monkeypatch.setattr(mod, "_get_workflow_repo", lambda: _Failing())
    asyncio.run(svc.get_workflow_intelligence("f1", allowed_client_ids=None))
    everything = _text(sent[0])
    assert "Failing workflows: 1 (Onboarding checklist)" in everything
    assert "Slow workflows (>1h avg): Onboarding checklist" in everything
    assert "step timed out" in everything
    assert not [p for p in PLANTED if p in everything]


def test_every_module_that_sends_the_products_own_figures_has_a_driver_here():
    """The AI-disclosure test classifies every module that reaches a provider. The ones that send the product's
    own figures rather than a document are the figures-only and no-screen ones and the two chat surfaces; each
    needs a driver above, so a new one cannot send a client's name unobserved."""
    from tests.test_the_ai_disclosure_names_the_providers_the_code_calls import EXEMPT, SURFACE_MODULES

    sends_figures = {rel for rel, (kind, _route, _why) in EXEMPT.items() if kind in {"figures-only", "no-screen"}}
    sends_figures |= {SURFACE_MODULES["assistant"], SURFACE_MODULES["copilot"]}
    driven = {module for module, _drive, _sees in FIGURE_FEATURES.values()}
    assert sends_figures == driven, (
        f"modules that send figures and have no driver: {sorted(sends_figures - driven)}; "
        f"drivers for a module that no longer does: {sorted(driven - sends_figures)}")


def test_the_services_the_summary_leaves_unnamed_are_in_the_product():
    """'Email delivery and error reporting are two it leaves out.' They exist (a mail provider and an error
    tracker are declared in the deploy manifest) and the page names neither, which is the sentence."""
    manifest = (REPO / "render.yaml").read_text(encoding="utf-8")
    assert "RESEND_API_KEY" in manifest, "no mail provider is declared: 'email delivery' is not a service the product uses"
    assert "SENTRY_DSN" in manifest, "no error tracker is declared: 'error reporting' is not a service the product uses"
    text = " ".join(_page_sentences(2)).lower()
    assert "resend" not in text and "sentry" not in text, "the page now names a service it says it leaves out"


def test_the_support_page_the_summary_points_to_exists_and_the_page_prints_no_address():
    support = MARKETING / "app" / "(site)" / "support" / "page.tsx"
    assert support.is_file()
    assert 'href="/support"' in _code(PAGE), "the page's closing sentence no longer links to the Support page"
    assert "CONTACT.email" in _code(support), "the Support page no longer offers a way to reach us"


# ═══ the Python port of the replay rule ═══════════════════════════════════════════════════════════

#: A replay or screen-recording tool, by the names it goes by in source and in a dependency list. Lower case:
#: the match is case-insensitive.
_REPLAY = re.compile(
    r"replayintegration|replaycanvasintegration|replayssessionsamplerate|replaysonerrorsamplerate|sessionreplay"
    r"|session_replay|@sentry/replay|@sentry-internal/replay|rrweb|fullstory|hotjar|logrocket|mouseflow"
    r"|clarity\.ms|smartlook|openreplay|inspectlet|luckyorange", re.I)

_SKIP_DIRS = {"node_modules", ".next", "out", ".turbo", ".git", "scripts", "__pycache__"}
_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


def replay_hits_in_source(text: str) -> list[str]:
    """Replay machinery named in code. Comments are blanked first: a comment explaining why replay is off is not replay."""
    return sorted({m.group(0).lower() for m in _REPLAY.finditer(blank_comments(text))})


def replay_hits_in_manifest(text: str) -> list[str]:
    """A replay or recording package among the dependencies a package.json declares (its own, by name)."""
    manifest = json.loads(text)
    names = [n for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
             for n in (manifest.get(key) or {})]
    return sorted(n for n in names if _REPLAY.search(n))


def _app_sources(app: Path):
    for dirpath, dirnames, filenames in os.walk(app):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix in _SOURCE_SUFFIXES and not re.search(r"\.(test|spec)\.", fn):
                yield p


def test_no_replay_or_recording_tool_is_in_either_browser_app():
    scanned = {"web": 0, "marketing": 0}
    problems = []
    for name, app in (("web", WEB), ("marketing", MARKETING)):
        for p in _app_sources(app):
            scanned[name] += 1
            hits = replay_hits_in_source(p.read_text(encoding="utf-8", errors="ignore"))
            if hits:
                problems.append(f"{p.relative_to(REPO).as_posix()}: {hits}")
        hits = replay_hits_in_manifest((app / "package.json").read_text(encoding="utf-8"))
        if hits:
            problems.append(f"{(app / 'package.json').relative_to(REPO).as_posix()}: depends on {hits}")
    # A vacuity floor: a scan that read nothing passes for ever.
    assert scanned["web"] > 300, f"only {scanned['web']} web sources were read: the walk is broken"
    assert scanned["marketing"] > 15, f"only {scanned['marketing']} marketing sources were read: the walk is broken"
    assert not problems, (
        "a session-replay or screen-recording tool is in the repository, and the privacy summary says there is none. "
        "Turning replay on is an owner decision that names payroll, bank and the portal as blocked routes first:\n  "
        + "\n  ".join(problems))


def test_the_product_drops_a_replay_integration_even_if_one_is_added():
    """Defence in depth the page can lean on: the error tracker's options drop the replay integrations by name."""
    options = (WEB / "lib" / "monitoring" / "options.ts").read_text(encoding="utf-8")
    dropped = re.search(r"DROPPED_INTEGRATIONS[^=]*=\s*\[([^\]]*)\]", options)
    assert dropped, "DROPPED_INTEGRATIONS is gone from lib/monitoring/options.ts"
    assert '"Replay"' in dropped.group(1) and '"ReplayCanvas"' in dropped.group(1)


def test_the_replay_scan_would_catch_a_replay_tool():
    """A scan that matches nothing would pass the test above for ever."""
    assert replay_hits_in_source("Sentry.init({ integrations: [Sentry.replayIntegration({ maskAllText: true })] })") == ["replayintegration"]
    assert replay_hits_in_source("Sentry.init({ replaysSessionSampleRate: 0.1, replaysOnErrorSampleRate: 1 })") == [
        "replaysonerrorsamplerate", "replayssessionsamplerate"]
    assert replay_hits_in_source("import { record } from 'rrweb'") == ["rrweb"]
    assert replay_hits_in_source("<script src='https://static.hotjar.com/c/hotjar.js'>") == ["hotjar"]
    assert replay_hits_in_manifest('{"dependencies": {"next": "14", "@sentry/replay": "^8"}}') == ["@sentry/replay"]
    assert replay_hits_in_manifest('{"devDependencies": {"logrocket": "^9"}}') == ["logrocket"]
    # …and does not flag what is not a replay tool: a comment saying there is none, and the error tracker itself.
    assert replay_hits_in_source("// there is no replayIntegration anywhere in apps/web\nconst a = 1;") == []
    assert replay_hits_in_source("/* rrweb is not used */ const a = 1;") == []
    assert replay_hits_in_manifest('{"dependencies": {"@sentry/nextjs": "^10", "next": "14"}}') == []


# ═══ the chat door changes a PAN and a GSTIN and nothing else ═════════════════════════════════════

def test_a_name_and_an_amount_typed_into_a_chat_are_sent_unchanged():
    """'Names and amounts you type there are sent as written.' The redactor replaces a PAN or GSTIN SHAPE; a name
    and an amount have none, and the reversible 'Client A' layer is not built (domain/ai/redaction)."""
    from domain.ai import groq_text
    from domain.ai.redaction import redact, redact_messages

    typed = "Sharma & Associates paid Rs 1,18,000 against invoice INV/2026-27/0042."
    assert redact(typed) == typed
    with_identifier = f"{typed} Their PAN is AAAAA0000A and GSTIN 27AAAAA0000A1Z5."
    sent = redact_messages([{"role": "user", "content": with_identifier}])[0]["content"]
    assert "Sharma & Associates" in sent and "1,18,000" in sent and "INV/2026-27/0042" in sent
    assert "AAAAA0000A" not in sent and "27AAAAA0000A1Z5" not in sent
    assert inspect.signature(groq_text.chat_detailed).parameters["redact"].default is True


def test_a_picture_of_a_document_goes_to_gemini_with_nothing_removed():
    """'A bill, a notice or a statement sent to be read is sent as it is.' A picture is not text, so the door that sends
    one has no redactor to run, and the two text readers switch it off by name (the existing disclosure test holds those)."""
    for rel in ("domain/ai/gemini_vision.py", "services/statement_vision.py"):
        tree = ast.parse((API / rel).read_text(encoding="utf-8"))
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {f"{n.module}.{a.name}" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        assert not [i for i in imported if "redaction" in i], f"{rel} runs a redactor: 'sent as it is' is stale"
    for rel in ("routers/document_intelligence_v1.py", "routers/document_intelligence_v2.py"):
        assert "redact=False" in (API / rel).read_text(encoding="utf-8"), f"{rel} no longer sends the document as it is"


# ═══ the footer ═══════════════════════════════════════════════════════════════════════════════════

_COLUMN_LINK = re.compile(r"\{\s*label:\s*\"([^\"]+)\",\s*href:\s*(`[^`]*`|\"[^\"]*\"|[A-Za-z_.]+)")
_JSX_LINK = re.compile(r"<Link\s+href=\"([^\"]+)\"[^>]*>\s*([^<>{}]+?)\s*</Link>")
_LEGAL_LABEL = re.compile(r"privacy|terms|legal|policy|policies|notice|cookie|disclaimer|conditions?", re.I)
#: What a legal-looking label's page is called, so that the link lands on a page named for it.
_LEGAL_STEM = {"privacy": "privacy", "terms": "terms", "legal": "legal", "policy": "polic", "policies": "polic",
               "notice": "notice", "cookie": "cookie", "disclaimer": "disclaimer", "condition": "condition",
               "conditions": "condition"}


def footer_links(source: str) -> list[tuple[str, str]]:
    """(label, href) for every link the footer draws, from its column table and from its bottom row. An href that
    is not a plain string (a template with a mailto, an `appLinks` member) is returned as written and is external."""
    code = blank_comments(source)
    links = [(label, expr.strip('"')) for label, expr in _COLUMN_LINK.findall(code)]
    links += [(label, href) for href, label in _JSX_LINK.findall(code)]
    return links


def page_exists(href: str, marketing: Path = MARKETING) -> bool:
    path = href.split("#")[0].split("?")[0].strip("/")
    candidates = ([marketing / "app" / "(site)" / "page.tsx"] if not path else
                  [marketing / "app" / "(site)" / path / "page.tsx", marketing / "app" / path / "page.tsx"])
    return any(c.is_file() for c in candidates)


def footer_problems(links: list[tuple[str, str]], marketing: Path = MARKETING) -> list[str]:
    out = []
    for label, href in links:
        internal = href.startswith("/")
        if internal and not page_exists(href, marketing):
            out.append(f"{label!r} links to {href}, which is not a page on the site")
        legal = _LEGAL_LABEL.search(label)
        if legal:
            word = _LEGAL_STEM[legal.group(0).lower()]
            if not internal:
                out.append(f"{label!r} is a legal link and leaves the site for {href}: it opens a document we cannot check")
            elif word not in href.lower():
                out.append(f"{label!r} is a legal-looking link that opens {href}, a page not named for it "
                           "(a Privacy or Terms link that lands on Support reads as a missing notice)")
    return out


def test_the_footer_is_read():
    links = footer_links(FOOTER.read_text(encoding="utf-8"))
    assert len(links) >= 12, f"only {len(links)} footer links read: the parser is broken"
    labels = [label for label, _ in links]
    assert "Privacy" in labels and "Support" in labels


def test_every_internal_footer_link_is_a_page_and_a_legal_one_goes_to_a_page_named_for_it():
    problems = footer_problems(footer_links(FOOTER.read_text(encoding="utf-8")))
    assert not problems, "\n".join(problems)


def test_the_privacy_link_opens_the_summary_and_there_is_no_terms_link_without_a_terms_page():
    links = dict(footer_links(FOOTER.read_text(encoding="utf-8")))
    assert links.get("Privacy") == "/privacy"
    assert page_exists("/privacy")
    # Terms: either no link, or a link to a page called terms that exists (the rule above fails any other).
    if "Terms" in links:
        assert "terms" in links["Terms"].lower() and page_exists(links["Terms"])
    else:
        assert not page_exists("/terms"), "a Terms page exists and the footer does not link it"


def test_the_privacy_page_is_listed_for_search_and_inherits_the_layouts_canonical():
    site = _code(MARKETING / "lib" / "site.ts")
    listed = re.search(r"export const INDEXABLE_PATHS = \[([^\]]*)\]", site)
    assert listed and '"/privacy"' in listed.group(1)
    assert not re.search(r"\balternates\b", _code(PAGE)), "a page-level alternates drops the layout's canonical"


@pytest.mark.parametrize("footer, expect", [
    # the old footer: both legal links opened Support
    ('<Link href="/support" className="x">Privacy</Link><Link href="/support" className="x">Terms</Link>', 2),
    # a Terms link to a page that does not exist
    ('<Link href="/terms" className="x">Terms</Link>', 1),
    # a Privacy link to a page that exists and is not about privacy
    ('<Link href="/pricing" className="x">Privacy policy</Link>', 1),
    # a legal link that leaves the site
    ('{ label: "Privacy", href: "https://example.com/p" },', 1),
    # an internal link to a page that does not exist
    ('{ label: "Guides", href: "/no-such-page" },', 1),
])
def test_the_footer_rule_fails_on_the_mistakes_it_exists_for(footer, expect):
    got = footer_problems(footer_links(footer))
    assert len(got) == expect, got


def test_the_footer_rule_passes_a_correct_footer():
    good = '{ label: "Support", href: "/support" },<Link href="/privacy" className="x">Privacy</Link>'
    assert footer_problems(footer_links(good)) == []
