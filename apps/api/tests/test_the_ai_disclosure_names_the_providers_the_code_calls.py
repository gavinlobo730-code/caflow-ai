"""The sentence a screen shows before it sends content to an AI provider names the
providers the code really calls (PRE-A-006).

WHAT WAS WRONG

No screen a CA uses to send a document or a question to a model named the provider in
its visible text (the invoice Extract box, the statement scan opt-in and the AI
Assistant said "AI" and nothing more); only the Partner-only AI status screen did. The
fix is a plain sentence beside each of those controls, from one module,
`apps/web/lib/ai/disclosure.ts`. A sentence like that is worth having only while it is
TRUE, and what makes it true is a fact about the backend: which provider a given
feature reaches. That is decided in apps/api, so it is held here, on the side that owns
it, and not in apps/web, where a guard would be asserting the sentence against a copy of
itself and would pass whenever both drifted together (the Schedule III caption lesson).

THE RULE, IN THREE PARTS

1. A surface lists the providers its backend module calls, and no others. The set is
   DERIVED from the module's own code (a reference to the sending function of
   `domain/ai/groq_text` or `domain/ai/gemini_vision`), so a Gemini call added to the
   assistant, or Groq dropped from the invoice reader, fails here until the sentence is
   re-read.
2. Every module that sends to a provider is either behind a surface or named below as
   one that sends no content a person typed or uploaded. Equality in both directions:
   a NEW caller fails until somebody classifies it, and a stale exemption fails too.
   This is also what forces a new kind of AI screen through a person who adds its
   trigger to the screen guard (apps/web/scripts/a-screen-that-sends-content-to-ai-names-
   the-provider.test.ts), which cannot see a spelling it was not told about.
3. A sentence says what the code can vouch for and no more: each provider by the name a
   person is shown, "outside India" (the fact the public site already states, pinned in
   test_the_facts_behind_the_marketing_claims), and the page limit of a scanned PDF as
   the constant that enforces it.

WHAT IT DELIBERATELY DOES NOT PIN: anything about training, retention or security of
the content at the provider. Those are the provider-terms questions (PRE-B-013,
Decision 5) and are unsettled, so the vocabulary of such a claim is refused on the web
side (lib/ai/disclosure.test.ts), not asserted here.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

API = pathlib.Path(__file__).resolve().parents[1]
WEB = API.parent / "web"
DISCLOSURE = WEB / "lib" / "ai" / "disclosure.ts"

#: surface (a key of AI_DISCLOSURES) -> the ONE backend module that makes its calls.
#: Not the router that mounts the route where the call happens elsewhere: the statement
#: scan is mounted in routers/banking.py and sends from services/statement_vision.py.
SURFACE_MODULES = {
    "invoice_extraction": "routers/document_intelligence_v1.py",
    "statement_scan": "services/statement_vision.py",
    "notice_extraction": "routers/document_intelligence_v2.py",
    "assistant": "routers/assistant.py",
    "copilot": "domain/ai_copilot_service.py",
}

#: Modules that send to a provider and are NOT a surface, each with its category and why.
#:   figures-only: what is sent is figures the product computed itself (counts, totals,
#:       ratios, and rupee amounts) and labels, with no client name; the CA types and
#:       uploads nothing on the screen, so there is no content to name. "Figures" is not
#:       "counts": the privacy page's figures card is held to the real builders by
#:       test_the_data_handling_summary_states_only_what_the_code_holds.
#:   no-screen: a real route no screen calls. If a screen ever does, it needs a surface
#:       (this test fails then, because the route's URL appears in the web source).
EXEMPT = {
    "services/digest_service.py": (
        "figures-only", None,
        "the morning digest narrates counts and labels the checks computed; the model is "
        "given no client name and is asked only when something needs attention"),
    "domain/financial_analysis_service.py": (
        "figures-only", None,
        "statement analysis narrates the revenue, expenses and profit in rupees for two "
        "financial years and the ratios the ledger computes, with no client name; the CA "
        "presses a button and types nothing"),
    "routers/ai_copilot.py": (
        "no-screen", "/api/ai-copilot/chat",
        "a real, rate-limited, redacted route that no screen calls"),
}

#: The functions of each door that SEND content. The premise test below holds this list
#: to the doors themselves, so a sender added to a door cannot be missed here.
SENDING = {
    "groq": {"chat", "chat_detailed", "chat_sync"},
    "gemini": {"generate"},
}
DOOR_MODULE = {"groq": "groq_text", "gemini": "gemini_vision"}
DISPLAY_FALLBACK = {"groq": "Groq", "gemini": "Google Gemini"}

NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
                7: "seven", 8: "eight", 9: "nine", 10: "ten"}


# ── reading the backend ─────────────────────────────────────────────────────────

def providers_called_by(source: str) -> set[str]:
    """The providers a module REFERENCES a sending function of.

    A reference and not only a call, so a door handed over as a callback
    (`call_model=groq_text.chat_sync`) is seen. `groq_text.answered_by()`,
    `.text_model()` and `.fallback_models()` are reads of a label, not a send, and a
    mention in a docstring is not code: none of them counts.
    """
    tree = ast.parse(source)
    modules: dict[str, str] = {}    # local name of a door module -> provider
    functions: dict[str, str] = {}  # local name of an imported sending function -> provider
    by_module = {v: k for k, v in DOOR_MODULE.items()}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "domain.ai":
            for a in node.names:
                if a.name in by_module:
                    modules[a.asname or a.name] = by_module[a.name]
        elif isinstance(node, ast.ImportFrom) and node.module in {f"domain.ai.{m}" for m in by_module}:
            provider = by_module[node.module.rsplit(".", 1)[1]]
            for a in node.names:
                if a.name in SENDING[provider]:
                    functions[a.asname or a.name] = provider
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("domain.ai.") and a.name.rsplit(".", 1)[1] in by_module:
                    modules[a.asname or a.name.rsplit(".", 1)[1]] = by_module[a.name.rsplit(".", 1)[1]]
    found: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id in modules and node.attr in SENDING[modules[node.value.id]]):
            found.add(modules[node.value.id])
        elif isinstance(node, ast.Name) and node.id in functions and isinstance(node.ctx, ast.Load):
            found.add(functions[node.id])
    return found


def _production_modules() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in API.rglob("*.py"):
        rel = path.relative_to(API).as_posix()
        if rel.startswith(("tests/", "migrations/", "scripts/", "domain/ai/")) or "__pycache__" in rel:
            continue
        out[rel] = path.read_text(encoding="utf-8")
    return out


def _callers() -> dict[str, set[str]]:
    """Every production module outside domain/ai that sends to a provider -> which."""
    found: dict[str, set[str]] = {}
    for rel, src in _production_modules().items():
        if "groq_text" not in src and "gemini_vision" not in src:
            continue
        providers = providers_called_by(src)
        if providers:
            found[rel] = providers
    return found


# ── reading the browser's module ────────────────────────────────────────────────

def _strip_comments(src: str) -> str:
    """Blank `//` and `/* */` comments, stepping over string literals, offsets kept.
    The header of disclosure.ts quotes `providers: [...]` in prose; read raw it would
    be taken for an entry."""
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in "\"'`":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i = j + 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(ch if ch == "\n" else " " for ch in src[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


ENTRY = re.compile(
    r'(\w+)\s*:\s*\{\s*providers\s*:\s*\[([^\]]*)\]\s*,\s*sentence\s*:\s*"((?:[^"\\]|\\.)*)"\s*,?\s*\}',
    re.S)


def _parse_disclosure(src: str) -> dict:
    code = _strip_comments(src)
    start = code.index("export const AI_DISCLOSURES")
    entries = {}
    for name, providers, sentence in ENTRY.findall(code[start:]):
        entries[name] = {
            "providers": re.findall(r'"([a-z]+)"', providers),
            "sentence": re.sub(r"\\(.)", r"\1", sentence),
        }
    names_block = re.search(r"export const AI_PROVIDER_NAMES[^=]*=\s*\{(.*?)\}", code, re.S)
    names = dict(re.findall(r'(\w+)\s*:\s*"([^"]+)"', names_block.group(1))) if names_block else {}
    union = re.search(r'export type AiDisclosureSurface\s*=\s*((?:\|\s*"[a-z_]+"\s*)+);', code)
    declared = re.findall(r'"([a-z_]+)"', union.group(1)) if union else []
    return {"entries": entries, "names": names, "union": declared}


@pytest.fixture(scope="module")
def disclosure() -> dict:
    assert DISCLOSURE.exists(), f"{DISCLOSURE} has moved — update this guard, do not delete it"
    return _parse_disclosure(DISCLOSURE.read_text(encoding="utf-8"))


# ── the premise: the doors, and that the scan reads them ────────────────────────

def test_the_sending_functions_are_exactly_the_ones_the_doors_expose():
    """If a door gains a function that sends (a `chat_stream`, a `generate_batch`), the
    scan below would not see a module that calls it. Held to the doors themselves."""
    from domain.ai import gemini_vision, groq_text
    chat_like = {n for n in dir(groq_text)
                 if n.startswith("chat") and callable(getattr(groq_text, n))}
    assert chat_like == SENDING["groq"], (
        f"groq_text exposes {sorted(chat_like)}; SENDING names {sorted(SENDING['groq'])} — "
        "add the new sender so a module calling it is not invisible")
    generate_like = {n for n in dir(gemini_vision)
                     if n.startswith("generate") and callable(getattr(gemini_vision, n))}
    assert generate_like == SENDING["gemini"], (
        f"gemini_vision exposes {sorted(generate_like)}; SENDING names {sorted(SENDING['gemini'])}")


def test_the_scan_finds_the_modules_that_send_and_is_not_vacuous():
    callers = _callers()
    assert len(callers) >= 8, f"found only {sorted(callers)}"
    assert callers["routers/document_intelligence_v1.py"] == {"groq", "gemini"}
    assert callers["services/statement_vision.py"] == {"gemini"}
    assert callers["routers/assistant.py"] == {"groq"}


def test_the_disclosure_module_parses_into_the_surfaces_it_should(disclosure):
    assert set(disclosure["entries"]) == set(SURFACE_MODULES), (
        f"lib/ai/disclosure.ts holds {sorted(disclosure['entries'])}; this test maps "
        f"{sorted(SURFACE_MODULES)} to backend modules — a surface added or removed on one "
        "side only")
    assert set(disclosure["union"]) == set(SURFACE_MODULES), (
        "the AiDisclosureSurface type and the table of sentences disagree")
    assert set(disclosure["names"]) == set(DOOR_MODULE), "AI_PROVIDER_NAMES is not keyed by the backend's provider ids"
    for n, expected in DISPLAY_FALLBACK.items():
        assert disclosure["names"][n] == expected


# ── part 1: the providers each surface lists are the providers the code calls ───

@pytest.mark.parametrize("surface", sorted(SURFACE_MODULES))
def test_a_surface_lists_exactly_the_providers_its_backend_calls(surface, disclosure):
    rel = SURFACE_MODULES[surface]
    path = API / rel
    assert path.exists(), f"{rel} has moved — update SURFACE_MODULES"
    derived = providers_called_by(path.read_text(encoding="utf-8"))
    assert derived, f"{rel} calls no provider — is {surface} still an AI surface?"
    listed = set(disclosure["entries"][surface]["providers"])
    assert listed == derived, (
        f"{surface}: lib/ai/disclosure.ts lists {sorted(listed)} but {rel} calls "
        f"{sorted(derived)}. The sentence the CA reads must name every provider that "
        "receives the content, and only those.")


# ── part 2: no module sends to a provider without being accounted for ───────────

def test_every_module_that_sends_to_a_provider_is_a_surface_or_named_as_figures_only():
    callers = set(_callers())
    accounted = set(SURFACE_MODULES.values()) | set(EXEMPT)
    new = callers - accounted
    assert not new, (
        f"{sorted(new)} send to an AI provider and are neither behind a disclosed surface "
        "nor listed in EXEMPT. If the CA types or uploads content that reaches it, add a "
        "surface to lib/ai/disclosure.ts, render <AiDisclosure> on the screen and add its "
        "trigger to the screen guard; if it sends only figures the product computed, name "
        "it in EXEMPT with the reason.")
    stale = accounted - callers
    assert not stale, f"{sorted(stale)} no longer send to a provider — remove them from this test"


@pytest.mark.parametrize("rel", sorted(m for m, (cat, _, _) in EXEMPT.items() if cat == "no-screen"))
def test_a_route_exempted_as_having_no_screen_really_has_none(rel):
    _cat, route, _why = EXEMPT[rel]
    hits, scanned = [], 0
    for top in ("app", "components", "lib"):
        for p in (WEB / top).rglob("*"):
            if p.suffix not in (".ts", ".tsx") or "node_modules" in p.parts or ".next" in p.parts:
                continue
            if re.search(r"\.(test|spec)\.tsx?$", p.name):
                continue
            scanned += 1
            if route in _strip_comments(p.read_text(encoding="utf-8")):
                hits.append(p.relative_to(WEB).as_posix())
    assert scanned > 100, f"the scan read {scanned} web files — it would pass vacuously"
    assert not hits, (
        f"{route} is exempt because no screen calls it, and {hits} do. Give that screen a "
        "surface (and the module a place in SURFACE_MODULES) instead of exempting it.")


# ── part 3: what a sentence says that the code can vouch for ────────────────────

@pytest.mark.parametrize("surface", sorted(SURFACE_MODULES))
def test_a_sentence_names_each_provider_by_the_name_a_person_is_shown_and_says_where_it_goes(surface, disclosure):
    entry = disclosure["entries"][surface]
    for p in entry["providers"]:
        assert disclosure["names"][p] in entry["sentence"], (
            f"{surface}: lists {p} but the sentence does not say {disclosure['names'][p]}")
    for p in set(DOOR_MODULE) - set(entry["providers"]):
        assert disclosure["names"][p] not in entry["sentence"], (
            f"{surface}: names {disclosure['names'][p]}, which its backend does not call")
    assert "outside India" in entry["sentence"]


def test_the_invoice_sentence_states_the_page_limit_the_code_enforces(disclosure):
    from routers.document_intelligence_v1 import SCANNED_PDF_PAGE_LIMIT
    word = NUMBER_WORDS[SCANNED_PDF_PAGE_LIMIT]
    sentence = disclosure["entries"]["invoice_extraction"]["sentence"]
    assert f"up to {word} pages" in sentence, (
        f"routers/document_intelligence_v1.SCANNED_PDF_PAGE_LIMIT is {SCANNED_PDF_PAGE_LIMIT} "
        f"and the sentence does not say 'up to {word} pages'")


def test_the_chat_surfaces_say_a_pan_or_gstin_is_replaced_because_the_door_replaces_it(disclosure):
    """The assistant and the copilot go through `groq_text.chat` with redaction on by
    default (domain/ai/redaction). If that default changes, the sentence is false."""
    import inspect
    from domain.ai import groq_text
    assert inspect.signature(groq_text.chat_detailed).parameters["redact"].default is True
    for surface in ("assistant", "copilot"):
        assert "PAN or a GSTIN is replaced" in disclosure["entries"][surface]["sentence"]


def test_the_document_readers_do_not_claim_a_replacement_they_do_not_make(disclosure):
    """The invoice and notice readers switch redaction OFF (the document is the payload;
    the supplier's GSTIN is printed on the invoice). Their sentences must not say otherwise."""
    for surface in ("invoice_extraction", "notice_extraction"):
        assert "replaced" not in disclosure["entries"][surface]["sentence"]
        src = (API / SURFACE_MODULES[surface]).read_text(encoding="utf-8")
        assert "redact=False" in src, f"{surface}: the reader no longer switches redaction off — re-read the sentence"


# ── the detector reads what it claims (synthetic source) ────────────────────────

def test_detector_sees_a_call_through_the_module_an_alias_and_an_imported_function():
    assert providers_called_by("from domain.ai import groq_text\nx = groq_text.chat(m)") == {"groq"}
    assert providers_called_by("from domain.ai import groq_text as g\nx = g.chat_sync(m)") == {"groq"}
    assert providers_called_by("from domain.ai import gemini_vision\ny = gemini_vision.generate(a)") == {"gemini"}
    assert providers_called_by("from domain.ai.groq_text import chat as c\nx = c(m)") == {"groq"}
    assert providers_called_by("import domain.ai.gemini_vision as gv\ny = gv.generate(a)") == {"gemini"}
    both = ("from domain.ai import groq_text, gemini_vision\n"
            "a = groq_text.chat_sync(m)\nb = gemini_vision.generate(i)")
    assert providers_called_by(both) == {"groq", "gemini"}


def test_detector_sees_a_door_passed_as_a_callback():
    assert providers_called_by(
        "from domain.ai import groq_text\nrun(call_model=groq_text.chat_sync)") == {"groq"}


def test_detector_does_not_count_a_label_a_docstring_or_an_unused_import():
    src = ('"""Calls groq_text.chat and gemini_vision.generate in prose."""\n'
           "from domain.ai import groq_text, gemini_vision\n"
           "label = groq_text.answered_by()\n"
           "models = gemini_vision.fallback_models()\n"
           "m = groq_text.text_model()\n"
           "# groq_text.chat(m)\n")
    assert providers_called_by(src) == set()


def test_detector_does_not_confuse_another_object_with_a_door():
    assert providers_called_by("from domain.ai import groq_text\nother.chat(m)") == set()
    assert providers_called_by("def chat(m):\n    return m\nchat(1)") == set()


def test_parser_reads_an_entry_and_ignores_the_header_comment():
    src = ('/* providers: ["x"], sentence: "not an entry" */\n'
           'export const AI_PROVIDER_NAMES: Record<AiProvider, string> = { groq: "Groq", gemini: "Google Gemini" };\n'
           'export type AiDisclosureSurface = | "a_b" | "c";\n'
           "export const AI_DISCLOSURES = {\n"
           "  // providers: [\"y\"], sentence: \"also not\"\n"
           '  a_b: { providers: ["groq", "gemini"], sentence: "Sent to Groq and Google Gemini, outside India." },\n'
           '  c: {\n    providers: ["groq"],\n    sentence: "It\'s sent to Groq, outside India.",\n  },\n'
           "};\n")
    parsed = _parse_disclosure(src)
    assert parsed["entries"] == {
        "a_b": {"providers": ["groq", "gemini"], "sentence": "Sent to Groq and Google Gemini, outside India."},
        "c": {"providers": ["groq"], "sentence": "It's sent to Groq, outside India."},
    }
    assert parsed["names"] == {"groq": "Groq", "gemini": "Google Gemini"}
    assert parsed["union"] == ["a_b", "c"]
