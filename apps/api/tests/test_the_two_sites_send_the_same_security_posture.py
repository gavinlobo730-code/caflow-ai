"""The marketing site and the product site send the same security headers, and the API's HSTS is the same value (security_privacy-05).

WHY THIS IS A PYTHON TEST
    `apps/marketing` has no test runner, and CLAUDE.md records the rule that follows: a guard for it lives on
    the Python side (or in apps/web/scripts), which the backend job runs on EVERY pull request because it has no
    `paths:` filter. The product site's own tests are `apps/web/scripts/the-sites-send-security-headers.test.ts`;
    this reads both generators by actually RUNNING them under node, so it holds what each really writes and not
    a spelling of it.

WHAT IT HOLDS
    * the headers that must be identical across the two sites — nosniff, X-Frame-Options, Referrer-Policy,
      Permissions-Policy, HSTS — are, and the HSTS value is also the one the API's middleware sends, so the
      three surfaces cannot drift to three max-ages;
    * both policies carry frame-ancestors, object-src, base-uri and form-action at their strictest, name no
      wildcard in connect-src, and have no 'unsafe-eval';
    * the marketing policy is exactly what the marketing code needs and no more: connect-src is 'self' and the
      API origin and NOTHING else (no Supabase, no error tracker), and the code agrees — every fetch goes to
      the API base, there is no iframe, no script or stylesheet loaded from another host, no image from a
      third party, no socket or worker;
    * the marketing build runs its generator after `next build`, and neither site has a hand-written
      `public/_headers` for it to overwrite;
    * SECURITY_CSP_MODE works the same way on both (a rollback of the policy that does not roll back the other
      headers);
    * the runbook that holds the Cloudflare half says in its opening lines that it is NOT APPLIED.

NOT HELD HERE
    That the marketing app builds (no node_modules here), that Cloudflare applies the file, and that the page
    renders under the policy; `apps/web/scripts/check-live-headers.mjs` asks the live site.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]
WEB = REPO / "apps" / "web"
MARKETING = REPO / "apps" / "marketing"
RUNBOOK = REPO / "docs" / "operations" / "edge-protection.md"

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed here")

SHARED = ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Permissions-Policy",
          "Strict-Transport-Security")

#: The generator's path and the environment travel in the process ENVIRONMENT and not in argv. In `node -e`
#: the first extra argument IS `process.argv[1]`, which is exactly what each generator compares its own URL
#: with to decide it was run as a script: passing the path in argv made the import run `main()` and write
#: out/_headers. (That is a property of this harness, not of how the build runs the script.)
_DRIVER = """
const mod = await import(new URL(`file://${process.env.GENERATOR}`).href);
const built = mod.buildHeadersFile(JSON.parse(process.env.GENERATOR_INPUT));
console.log(JSON.stringify({ content: built.content, mode: built.mode, origins: built.origins, missing: built.missing,
                              hsts: mod.HSTS }));
"""


def _run(generator: Path, env: dict) -> dict:
    import os
    out = subprocess.run(
        [NODE, "--input-type=module", "-e", _DRIVER],
        capture_output=True, text=True, timeout=60, check=True,
        env={**os.environ, "GENERATOR": str(generator), "GENERATOR_INPUT": json.dumps(env)})
    return json.loads(out.stdout)


WEB_GEN = WEB / "scripts" / "security-headers.mjs"
MKT_GEN = MARKETING / "scripts" / "security-headers.mjs"

API_URL = "https://practicesync-api.onrender.com"
SUPABASE_URL = "https://abcdefghij.supabase.co"
SENTRY_DSN = "https://k@o123.ingest.sentry.io/9"


def _headers(content: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in content.splitlines():
        if line.startswith("  ") and ":" in line:
            name, value = line.strip().split(":", 1)
            out[name.strip()] = value.strip()
    return out


@pytest.fixture(scope="module")
def web():
    return _run(WEB_GEN, {"apiUrl": API_URL, "supabaseUrl": SUPABASE_URL, "sentryDsn": SENTRY_DSN, "mode": "enforce"})


@pytest.fixture(scope="module")
def marketing():
    return _run(MKT_GEN, {"apiUrl": API_URL, "mode": "enforce"})


def _directive(csp: str, name: str) -> list[str]:
    for part in csp.split(";"):
        part = part.strip()
        if part.startswith(name + " "):
            return part.split()[1:]
    raise AssertionError(f"no {name} in {csp}")


# ═══ the same headers ═════════════════════════════════════════════════════════

def test_the_headers_that_must_agree_do(web, marketing):
    w, m = _headers(web["content"]), _headers(marketing["content"])
    for name in SHARED:
        assert name in w and name in m, f"{name} missing from a site"
        assert w[name] == m[name], f"{name} differs between the sites: {w[name]!r} vs {m[name]!r}"


def test_all_three_surfaces_send_one_hsts_value(web, marketing):
    from middleware.security_headers import HSTS_VALUE
    assert _headers(web["content"])["Strict-Transport-Security"] == HSTS_VALUE
    assert _headers(marketing["content"])["Strict-Transport-Security"] == HSTS_VALUE
    assert web["hsts"] == marketing["hsts"] == HSTS_VALUE


@pytest.mark.parametrize("site", ["web", "marketing"])
def test_each_policy_has_the_strict_directives_and_no_wildcard_to_connect_to(site, request):
    built = request.getfixturevalue(site)
    csp = _headers(built["content"])["Content-Security-Policy"]
    assert _directive(csp, "frame-ancestors") == ["'none'"]
    assert _directive(csp, "object-src") == ["'none'"]
    assert _directive(csp, "base-uri") == ["'self'"]
    assert _directive(csp, "form-action") == ["'self'"]
    assert _directive(csp, "default-src") == ["'self'"]
    assert "unsafe-eval" not in csp
    for source in _directive(csp, "connect-src"):
        assert source == "'self'" or re.fullmatch(r"https?://[A-Za-z0-9.-]+(:\d+)?", source), source
    assert "*" not in " ".join(_directive(csp, "connect-src"))


def test_the_web_policy_names_its_three_hosts_and_the_marketing_policy_only_its_one(web, marketing):
    w = _directive(_headers(web["content"])["Content-Security-Policy"], "connect-src")
    m = _directive(_headers(marketing["content"])["Content-Security-Policy"], "connect-src")
    assert w == ["'self'", API_URL, SUPABASE_URL, "https://o123.ingest.sentry.io"]
    assert m == ["'self'", API_URL], "the marketing site talks to the API for the demo form and to nothing else"


@pytest.mark.parametrize("mode", ["enforce", "report-only", "off", "enforced-typo", ""])
def test_the_rollback_switch_means_the_same_on_both_sites(mode):
    for gen, env in ((WEB_GEN, {"apiUrl": API_URL, "supabaseUrl": SUPABASE_URL}), (MKT_GEN, {"apiUrl": API_URL})):
        built = _run(gen, {**env, "mode": mode})
        h = _headers(built["content"])
        # nobody having decided (unset, blank, a typo) is report-only on BOTH sites, and only the word "enforce"
        # enforces: the policy has not met the real hosts, and a wrong enforced policy stops sign-in silently
        expect = mode if mode in ("enforce", "report-only", "off") else "report-only"
        assert built["mode"] == expect
        assert ("Content-Security-Policy" in h) == (expect == "enforce")
        assert ("Content-Security-Policy-Report-Only" in h) == (expect == "report-only")
        for name in SHARED:
            assert name in h, f"{name} must survive the CSP being rolled back ({gen.parent.parent.name}, {mode!r})"


# ═══ the marketing policy is what the marketing code needs ════════════════════

def _marketing_sources() -> list[Path]:
    out = []
    for root in ("app", "components", "lib"):
        for p in (MARKETING / root).rglob("*"):
            if p.suffix in (".ts", ".tsx") and "node_modules" not in p.parts:
                out.append(p)
    return out


def _code(p: Path) -> str:
    """Source with comments removed, so a comment explaining why a thing is not done is not the thing done."""
    text = p.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)(^|[^:\"'`\\])//.*$", r"\1", text)


def test_the_marketing_source_is_found():
    assert len(_marketing_sources()) > 20


def test_every_request_the_marketing_site_makes_goes_to_the_api():
    fetches = []
    for p in _marketing_sources():
        for m in re.finditer(r"fetch\(\s*([^,)]+)", _code(p)):
            fetches.append((p.name, m.group(1).strip()))
    assert fetches, "vacuous: the demo form's fetch calls were not found"
    for name, target in fetches:
        assert target.startswith("`${API}") or target.startswith("API"), f"{name} fetches {target}: not the API base"


def test_the_marketing_site_loads_nothing_from_another_host():
    for p in _marketing_sources():
        code = _code(p)
        assert "<iframe" not in code and "<object" not in code and "<embed" not in code, p.name
        assert not re.search(r"new\s+(WebSocket|EventSource|Worker|SharedWorker)\s*\(|sendBeacon", code), p.name
        assert not re.search(r"<script[^>]+src=|<link[^>]+href=[\"']https?:", code), f"{p.name} loads a script or stylesheet"
        for form in re.findall(r"<form\b[^>]*>", code):
            assert "action=" not in form, f"{p.name}: a form with an action needs form-action widened: {form[:80]}"
        for m in re.finditer(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", code):
            assert m.group(1).startswith(("/", "data:")), f"{p.name}: an image from {m.group(1)}"


# ═══ the build runs it, and nothing hand-written competes ═════════════════════

def test_the_marketing_build_runs_the_generator_after_next_build():
    scripts = json.loads((MARKETING / "package.json").read_text(encoding="utf-8"))["scripts"]
    cmd = scripts["build"]
    assert "next build" in cmd and cmd.index("scripts/security-headers.mjs") > cmd.index("next build"), cmd


@pytest.mark.parametrize("app", [WEB, MARKETING], ids=["web", "marketing"])
def test_no_hand_written_headers_file_competes_with_the_generated_one(app):
    assert not (app / "public" / "_headers").exists()


def test_the_generators_are_plain_esm_files_that_need_no_install():
    """The marketing build has to run this on a machine that has only what `pnpm install` gave it: nothing
    here may import a package."""
    for gen in (WEB_GEN, MKT_GEN):
        imports = re.findall(r"^import\s[^;]*from\s+[\"']([^\"']+)[\"']", gen.read_text(encoding="utf-8"), re.M)
        assert imports and all(i.startswith("node:") for i in imports), (gen.name, imports)


# ═══ the human half says it is not done ═══════════════════════════════════════

def test_the_edge_runbook_says_in_its_opening_lines_that_it_is_not_applied():
    assert RUNBOOK.is_file(), "docs/operations/edge-protection.md is missing"
    head = "\n".join(RUNBOOK.read_text(encoding="utf-8").splitlines()[:14])
    assert "NOT APPLIED" in head
