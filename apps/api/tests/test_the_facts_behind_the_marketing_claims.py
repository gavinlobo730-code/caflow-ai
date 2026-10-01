"""The facts four marketing sentences rest on, each pinned where no test did
(market_and_trust-09).

The claims ledger (`_marketing_claims.py`) ties every capability sentence on the public
site to a test. Most claims already had one. Four did not, and each is a sentence a
CA's IT-minded partner would check first:

  * "MFA ... on approvals" — the guard is attached to six ROUTERS in `main.py`, and
    approvals is not one of them: it carries `mfa_guard` PER ACTION, on approve and
    reject, as a comment in `main.py` says and no test held;
  * "No AI key ever reaches the browser" — `CLAUDE.md` states it as a rule and nothing
    scanned the two browser apps for a key;
  * "the AI features send the text or image of a document to an AI provider outside
    India" — a disclosure about WHERE data goes, so the test that matters is the one that
    fails when the destination changes;
  * "The software never transmits anything to a government portal" — pinned for the
    filing DEMO by `test_filing_simulation_never_files.py`, but nothing looked at the
    rest of the server for an address a return could be sent to.

They read source and the mounted routes. They cost nothing and cannot flake.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

API = Path(__file__).resolve().parents[1]
APPS = API.parent


# ── 1. approve and reject each ask for a second factor ───────────────────────

def _route_guarded_by_mfa(method: str, path: str) -> bool:
    import main
    from core.auth import mfa_guard

    found = [r for r in main.app.routes
             if getattr(r, "path", None) == path and method in (getattr(r, "methods", None) or ())]
    assert found, f"no {method} {path} is mounted — the premise of this test moved"
    deps = getattr(getattr(found[0], "dependant", None), "dependencies", [])
    return mfa_guard in {getattr(d, "call", None) for d in deps}


def test_approving_and_rejecting_a_request_each_ask_for_a_second_factor():
    """Approve EXECUTES the privileged action the request was for and reject is a
    governance decision; `main.py` leaves the approvals router unguarded as a whole so a
    read stays open and puts the guard on the two actions that decide. The site says
    'approvals' among the places a Partner or Manager is asked for a factor."""
    assert _route_guarded_by_mfa("POST", "/api/approvals/{request_id}/approve")
    assert _route_guarded_by_mfa("POST", "/api/approvals/{request_id}/reject")


def test_the_guard_detector_is_not_vacuous():
    """A helper that answers False for everything would make the test above fail, and one
    that answers True for everything would make it pass for ever. Pin both sides on routes
    whose answer is known: payroll is behind the guard, a plain read of approvals is not."""
    import main
    paths = {(m, r.path) for r in main.app.routes for m in (getattr(r, "methods", None) or ())}
    payroll = next(p for m, p in sorted(paths) if m == "GET" and p.startswith("/api/payroll"))
    assert _route_guarded_by_mfa("GET", payroll)
    assert not _route_guarded_by_mfa("POST", "/api/approvals/{request_id}/cancel"), (
        "cancel is the requester's own withdrawal and is deliberately not behind the factor")


# ── 2. no AI key in either browser app ───────────────────────────────────────

_VENDOR = r"(?:GROQ|GEMINI|OPENAI|ANTHROPIC|OPENROUTER|MISTRAL|COHERE)"
_KEY_SHAPES = (
    # an environment variable named for a model vendor, or a generic AI key name
    re.compile(rf"\b[A-Z0-9_]*{_VENDOR}[A-Z0-9_]*\b"),
    re.compile(r"\b(?:AI|LLM|MODEL)_(?:API_)?KEY\b"),
    # a key itself: Groq, Google and OpenAI-shaped literals
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{32,}"),
)
_BROWSER_APPS = ("web", "marketing")
_SKIP_DIRS = {"node_modules", ".next", "out", ".wrangler", ".vercel", ".turbo", "coverage"}
_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".toml", ".example", ".env", ".yml", ".yaml"}


def _browser_files():
    for app in _BROWSER_APPS:
        for path in (APPS / app).rglob("*"):
            if not path.is_file() or _SKIP_DIRS & set(path.parts):
                continue
            if path.name.endswith((".test.ts", ".test.tsx", ".tsbuildinfo")) or path.name == "pnpm-lock.yaml":
                continue  # a test that PROVES a key is scrubbed has to name one; the lockfile names packages
            if path.suffix in _SUFFIXES or path.name.startswith(".env"):
                yield path


def _key_mentions(text: str) -> list[str]:
    return [m.group(0) for rx in _KEY_SHAPES for m in rx.finditer(text)]


def test_no_ai_key_is_named_in_either_browser_app():
    """`apps/web` is a static export: it has no server, so the only values it can read are
    `NEXT_PUBLIC_*`, which are inlined into the bundle every visitor downloads. A key here
    is at best ignored and at worst published, and the marketing site is public by
    definition. Every model call is made by apps/api with keys in apps/api/.env only."""
    seen = list(_browser_files())
    assert len(seen) > 150, "the browser apps were not found — the scan would pass for ever"
    hits = []
    for path in seen:
        for mention in _key_mentions(path.read_text(encoding="utf-8", errors="ignore")):
            hits.append(f"{path.relative_to(APPS)}: {mention}")
    assert not hits, "an AI key is named in a browser app:\n" + "\n".join(hits)


@pytest.mark.parametrize("text", [
    "const k = process.env.NEXT_PUBLIC_GROQ_API_KEY;",
    "GEMINI_API_KEY=abc",
    "const key = 'gsk_" + "a" * 24 + "'",
    "headers: { Authorization: `Bearer ${process.env.OPENAI_KEY}` }",
    "const model = process.env.AI_API_KEY",
])
def test_the_key_scan_would_catch_a_key(text):
    assert _key_mentions(text), text


def test_the_key_scan_leaves_ordinary_words_alone():
    assert not _key_mentions("Ask the AI assistant. Every model call is made server-side. Keys live in apps/api.")


def test_the_api_is_where_the_keys_are_read():
    """The other half of 'every model call is made server-side': the keys the browser
    must not hold are read by the backend, from the environment."""
    # The RULE is "a backend module reads each key from the environment", not "this
    # particular file does" — the keys are named in the gateway's provider table and
    # read where a call is made, and that moved when the two doors were built (ai-04).
    sources = [p.read_text(encoding="utf-8")
               for p in API.rglob("*.py")
               if "tests" not in p.relative_to(API).parts and "venv" not in p.parts]
    assert len(sources) > 100, "the backend was not found — the scan would pass for ever"
    for key in ("GROQ_API_KEY", "GEMINI_API_KEY"):
        assert any(re.search(r"(environ|getenv)[^\n]*" + key, src) for src in sources), (
            f"no backend module reads {key} from the environment")
    from domain.ai import gateway
    assert gateway.GROQ.key_env == "GROQ_API_KEY" and gateway.GEMINI.key_env == "GEMINI_API_KEY"


# ── 3. a model call leaves for a provider outside India ──────────────────────

def test_a_model_call_leaves_for_a_provider_outside_india():
    """'The AI features send the text or image of a document to an AI provider outside
    India.' Text goes to Groq's API and pictures go through Google's SDK. If either
    destination changes — a self-hosted model, an in-region endpoint — the sentence on
    four pages is wrong in the OTHER direction (it discloses more than is true), and this
    is the test that makes somebody read it."""
    from domain.ai import groq_text

    # There is ONE text destination now (ai-04): the copilot route and the statement
    # narrator used to carry a URL each, and both go through the door instead.
    host = urlparse(groq_text.GROQ_CHAT_URL).hostname
    assert host == "api.groq.com", f"text goes to {host}, which the site says is outside India"
    assert not host.endswith(".in")

    # …and nothing else names a Groq host, so a second destination cannot appear unseen.
    others = [str(p.relative_to(API)) for p in API.rglob("*.py")
              if "tests" not in p.relative_to(API).parts and "venv" not in p.parts
              and p.name != "groq_text.py" and "api.groq.com" in p.read_text(encoding="utf-8")]
    assert not others, f"a second place names a Groq host: {others}"

    vision = (API / "domain" / "ai" / "gemini_vision.py").read_text(encoding="utf-8")
    assert "from google import genai" in vision, (
        "pictures no longer go through Google's SDK — what do the site's AI sentences say now?")


# ── 4. no server code addresses a government portal ──────────────────────────

# A host that is a government portal, a statutory utility's own site, or the departments'
# filing back-ends. A return can only be SENT to an address; there is none in the server.
_PORTAL_SUFFIXES = ("gov.in", "nic.in", "gstn.org.in", "esic.in", "proteantech.in",
                    "tin-nsdl.com", "nsdl.co.in", "epfindia.gov.in")

# An XBRL namespace is an identifier written into a document the CA uploads; it is never
# requested. Named with the reason, so the exemption is a decision and not a silence.
_NAMESPACE_ONLY = {
    "domain/income_tax/xbrl_service.py": ("http://www.mca.gov.in",),
}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                ids.add(id(body[0].value))
    return ids


def portal_urls_in(source: str) -> list[str]:
    """Every string constant that is an http(s) URL on a government portal's host, other than
    in a docstring (which explains, and sends nothing) or a comment (which is not code)."""
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            for url in re.findall(r"https?://[^\s'\"<>)]+", node.value):
                host = (urlparse(url).hostname or "").lower()
                if any(host == s or host.endswith("." + s) for s in _PORTAL_SUFFIXES):
                    found.append(url)
    return found


def _server_sources():
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API).as_posix()
        if rel.startswith(("tests/", "migrations/", ".venv/", "venv/")) or "/site-packages/" in rel:
            continue
        yield rel, path


def test_no_server_code_addresses_a_government_portal():
    """'The software never transmits anything to a government portal, for GST, ITR, TDS or
    MCA.' `test_filing_simulation_never_files.py` proves the filing DEMO writes and sends
    nothing; this is the rest of the server. A client for a portal needs an address to call,
    and there is none in apps/api — so adding the first one is a decision this test makes
    somebody take, together with the CA-confirmation rule in CLAUDE.md and the sentence on
    the pricing, support, products and homepage pages."""
    sources = list(_server_sources())
    assert len(sources) > 500, "the server sources were not found — the scan would pass for ever"
    hits = []
    for rel, path in sources:
        allowed = _NAMESPACE_ONLY.get(rel, ())
        for url in portal_urls_in(path.read_text(encoding="utf-8")):
            if not url.startswith(allowed or ("\0",)):
                hits.append(f"{rel}: {url}")
    assert not hits, "server code names a government portal address:\n" + "\n".join(hits)


def test_the_namespace_exemption_is_still_the_only_reason_for_the_exemption():
    for rel, prefixes in _NAMESPACE_ONLY.items():
        urls = portal_urls_in((API / rel).read_text(encoding="utf-8"))
        assert urls, f"{rel} no longer names a portal host — delete its exemption"
        assert all(u.startswith(prefixes) for u in urls)
        assert "xmlns" in (API / rel).read_text(encoding="utf-8").lower() or "namespace" in (
            (API / rel).read_text(encoding="utf-8").lower()), "the exemption says namespace; it is not one"


@pytest.mark.parametrize("source,expected", [
    ('requests.post("https://api.gst.gov.in/taxpayerapi/v1.0/returns/gstr1", json=p)', 1),
    ('URL = "https://einvoice1.nic.in/api"', 1),
    ('httpx.get(f"https://www.incometax.gov.in/{path}")', 1),  # an f-string's literal parts are read
    ('"""Explains https://gst.gov.in and sends nothing."""\nx = 1', 0),
    ('# https://gst.gov.in in a comment\nx = 1', 0),
    ('x = "https://api.groq.com/openai/v1/chat/completions"', 0),
])
def test_the_portal_scan_sees_a_url_and_ignores_prose(source, expected):
    assert len(portal_urls_in(source)) == expected
