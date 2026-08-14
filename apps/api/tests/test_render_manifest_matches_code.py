"""
render.yaml must describe the environment the backend actually reads.

THE MISTAKE THIS EXISTS TO CATCH
    The manifest and the running service drifted apart with nothing to notice.
    At the point this test was written the backend read 24 environment
    variables and render.yaml declared 11 — and one of the 11
    (DOCUMENT_INTELLIGENCE_PROVIDER) was read by no code at all.

    Two of the gaps had teeth:

      * GEMINI_API_KEY was read by routers/document_intelligence_v1.py and
        declared nowhere. Image-based invoice extraction fails CLOSED — it logs
        "refusing to fabricate an extraction" and returns nothing — so a
        missing key looks like a quiet feature, not an outage.

      * ENABLE_SCHEDULER was declared with a literal value that never reached
        the service, because the service was created by hand rather than from
        this blueprint. jobs/scheduler.py stays dormant unless it reads exactly
        "true", so compliance reminders, recurring invoices and escalations
        simply never ran, and nothing said so.

    Both failure modes are silent. That is precisely the kind a test has to
    cover, because operating the system will not surface them.

WHAT IT DOES NOT DO
    It cannot see the Render dashboard, so it cannot tell you a declared
    variable is actually SET in production. It only keeps the manifest honest
    about what the code needs. Confirming the dashboard is a human step.
"""
import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
MANIFEST = REPO_ROOT / "render.yaml"

# Read by the backend, deliberately NOT declared in render.yaml. Each entry is a
# reason, not a parking space — test_no_exempt_entry_is_stale fails once a name
# stops being read, so this list cannot quietly outlive its justification.
EXEMPT: dict[str, str] = {
    "NEXT_PUBLIC_SUPABASE_ANON_KEY":
        "Compatibility fallback only. core/supabase_client.py reads it when "
        "SUPABASE_ANON_KEY is unset, because the frontend spelling is what "
        "existed first. Declaring it would legitimise a second name for one "
        "value; SUPABASE_ANON_KEY is the one that belongs on the server.",
    "ENVIRONMENT":
        "Sentry's environment tag, defaulting to 'production' in main.py. "
        "Setting it wrong mislabels dashboards; leaving it unset is correct "
        "for this service, so declaring it would invite a needless value.",
    "MFA_REQUIRED_ROLES":
        "Only consulted when REQUIRE_MFA is on, and defaults to 'Partner' — "
        "the safe tier. REQUIRE_MFA is declared; this rider does not need to "
        "be until someone wants a different set of roles.",
    "GROQ_TEXT_MODEL":
        "Model-name override with a working default pinned in code. Declaring "
        "it would encourage pinning a model in the environment, where a stale "
        "value outlives the code that expects it.",
    "GEMINI_VISION_MODEL":
        "Same reasoning as GROQ_TEXT_MODEL — an override, not a requirement.",
    "RAZORPAY_KEY_ID":
        "Live payment-gateway credential. Only read when PAYMENT_PROVIDER is "
        "'razorpay', which is declared. Listing the gateway secrets in the "
        "manifest implies the real gateway is expected to be wired up; it is "
        "not, and MVP Phase 1 runs the mock provider.",
    "RAZORPAY_KEY_SECRET":
        "As RAZORPAY_KEY_ID — real-money credential, mock provider is default.",
    "RAZORPAY_WEBHOOK_SECRET":
        "As RAZORPAY_KEY_ID — real-money credential, mock provider is default.",
    "SENTRY_TRACES_SAMPLE_RATE":
        "Performance-tracing knob, defaulting to 0 (off) in main.py. Declaring "
        "it would invite someone to set a rate; the free Sentry tier drops "
        "events once the transaction quota is gone, and the events it drops "
        "include the posting failures Sentry is installed to surface. Raising "
        "it should be a deliberate act on a paid plan, not a filled-in blank.",
    "MOCK_WEBHOOK_SECRET":
        "Mock payment provider's webhook signing secret. services/payments/"
        "mock.py refuses a hardcoded default on purpose, so an unset value "
        "disables mock webhooks rather than trusting anything that arrives — "
        "the safe direction, and not something production needs set.",
}

# `os.environ.get("X")`, `os.getenv("X")`, `os.environ["X"]`, and the indirect
# `_flag("X")` helper in core/security_config.py. The helper matters: without it
# USE_USER_JWT and REQUIRE_MFA — two flags that decide whether RLS and MFA are
# enforced — read as unused, which is the wrong direction to be wrong in.
_READ = re.compile(
    r"""(?:os\.environ\.get|os\.getenv|_flag)\(\s*["']([A-Z][A-Z0-9_]*)["']"""
    r"""|os\.environ\[\s*["']([A-Z][A-Z0-9_]*)["']\s*\]"""
)

# Deliberately not PyYAML: it is installed in this container but absent from
# requirements.txt, so importing it would make the suite pass locally and error
# in CI. The manifest's env block is a flat list of `- key: NAME` and needs no
# real parser.
_DECLARED = re.compile(r"^\s*-\s*key:\s*([A-Z][A-Z0-9_]*)\s*$", re.M)

_SKIP_DIRS = {"tests", ".venv", "venv", "__pycache__", "migrations", "node_modules"}


def _read_by_code() -> dict[str, set[str]]:
    """env var -> the files reading it."""
    found: dict[str, set[str]] = {}
    for path in API_ROOT.rglob("*.py"):
        if set(path.parts) & _SKIP_DIRS:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for direct, indexed in _READ.findall(src):
            name = direct or indexed
            found.setdefault(name, set()).add(path.relative_to(API_ROOT).as_posix())
    return found


def _declared() -> set[str]:
    return set(_DECLARED.findall(MANIFEST.read_text(encoding="utf-8")))


pytestmark = pytest.mark.skipif(
    not MANIFEST.is_file(), reason="render.yaml not in this checkout")


def test_the_scan_finds_both_sides():
    """Vacuity guard. If either half comes back empty the checks below are
    assertions about nothing, and would pass through any amount of drift."""
    assert len(_read_by_code()) >= 15, "no env reads parsed from apps/api"
    assert len(_declared()) >= 10, "no env vars parsed from render.yaml"


def test_the_scan_sees_indirectly_read_flags():
    """Anchors the `_flag()` half of the pattern. These two are read through a
    helper rather than os.environ directly, and a regex that only matched the
    direct form would report them as unused — the exact reasoning that would
    get a security flag deleted as dead config."""
    read = _read_by_code()

    for name in ("USE_USER_JWT", "REQUIRE_MFA"):
        assert name in read, f"{name} no longer parses as read — check _READ"


def test_every_variable_the_code_reads_is_declared_or_exempt():
    read = _read_by_code()
    missing = sorted(set(read) - _declared() - set(EXEMPT))

    assert not missing, (
        "the backend reads these environment variables but render.yaml does "
        "not declare them, so a service rebuilt from the manifest would be "
        "missing them:\n  "
        + "\n  ".join(f"{n}  ({', '.join(sorted(read[n]))})" for n in missing)
        + "\n\nAdd each to render.yaml, or to EXEMPT with the reason it should "
          "stay undeclared."
    )


def test_no_declared_variable_is_read_by_nothing():
    """Dead config is not harmless: it tells whoever reads the manifest that
    the service needs something it does not, and the next person to wire up a
    real setting of that name inherits a value nobody chose."""
    dead = sorted(_declared() - set(_read_by_code()))

    assert not dead, (
        f"render.yaml declares variables no code reads: {dead}. Remove them, "
        f"or point the code at them if the setting was meant to be honoured."
    )


def test_no_exempt_entry_is_stale():
    """An exemption that outlives its variable is a hole: the name can come
    back into use later and skip the declaration check entirely."""
    stale = sorted(set(EXEMPT) - set(_read_by_code()))

    assert not stale, f"EXEMPT names variables no code reads any more: {stale}"


def test_every_exemption_states_a_reason():
    for name, why in EXEMPT.items():
        assert len(why) > 60, f"{name}: say why it stays undeclared, not just that it does"


def test_the_scheduler_flag_is_declared():
    """Called out by name because its failure is the quietest one here: unset,
    jobs/scheduler.py logs a warning and every recurring job stops, while the
    API keeps serving normally and nothing looks wrong."""
    assert "ENABLE_SCHEDULER" in _declared()
