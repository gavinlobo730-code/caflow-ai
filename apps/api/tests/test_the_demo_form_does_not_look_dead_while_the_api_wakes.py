"""A SLEEPING API MUST NOT MAKE THE DEMO FORM LOOK BROKEN (market_and_trust-17).

The "Book a demo" form posts to the Render API, which sleeps on the free tier.
The form had no timeout, no progress wording and no early fallback, so a visitor
who submitted after an idle spell sat on "Sending…" for as long as the cold start
took (56.55 s measured) and saw nothing else. The demo request is the main way a
new customer reaches the practice; to that visitor the form was dead.

What the fix does, and what it deliberately does not:

  * the wait is NAMED the instant it starts, including "up to a minute";
  * after `SLOW_AFTER_MS` the email fallback appears BESIDE the running request,
    with what the visitor typed already in the message — the request is not
    cancelled to show it;
  * after `GIVE_UP_AFTER_MS` the request is abandoned and the failure says
    nobody can tell whether it arrived;
  * there is NO automatic retry, although the finding asked for one.
    `POST /api/public/demo-request` is not idempotent — every call that passes
    its checks sends the team an email and there is no request id to recognise a
    repeat by — so a client that gave up and sent again can turn one visitor
    into two leads and spend two of their three sends in the per-IP window. The
    same shape CLAUDE.md records for a filing: a retry needs the reference
    recorded first, never a blind resend.

THE GUARD IS ON THE PYTHON SIDE because it was written before apps/marketing had
a test runner (`pnpm test` arrived on 16-11-2026, in the path-filtered Marketing
CI), and the source-level half reads the API's router beside the form. The
behavioural half (the clocks under a fake timer, and the mailto) used to run here under
Node and skip where Node could not strip TypeScript; it moved to the marketing runner,
`apps/marketing/lib/demoRequestWait.test.ts` (POST-A-119), and a test below holds that
it is still there.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MARKETING = REPO / "apps" / "marketing"
FORM = MARKETING / "components" / "DemoForm.tsx"
WAIT = MARKETING / "lib" / "demoRequestWait.ts"
SITE = MARKETING / "lib" / "site.ts"
DEMO_PAGE = MARKETING / "app" / "(site)" / "demo" / "page.tsx"
ROUTER = REPO / "apps" / "api" / "routers" / "demo_request.py"

#: The cold start the finding measured on Render's free tier, in milliseconds.
MEASURED_COLD_START_MS = 56_550


def _strip_comments(src: str) -> str:
    """Comments blanked, `://` left alone so a URL is not read as a comment."""
    src = re.sub(r"/\*[\s\S]*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), src)
    return re.sub(r"(?<!:)//.*", "", src)


def _code(p: Path) -> str:
    return _strip_comments(p.read_text(encoding="utf-8"))


def _const(src: str, name: str) -> int:
    m = re.search(rf"export const {name}\s*=\s*([\d_]+)", src)
    assert m, f"{name} is not declared in lib/demoRequestWait.ts"
    return int(m.group(1).replace("_", ""))


# ── the premise: the endpoint is not idempotent ──────────────────────────────

def test_the_endpoint_carries_no_request_id_so_a_resend_is_a_second_lead():
    """THE PREMISE OF THE NO-RETRY DECISION, asserted rather than remembered.

    If the API ever learns to recognise a repeat (an idempotency key it dedupes
    on), this fails — and that is the moment an automatic retry becomes safe to
    build, so the next reader is told to revisit `lib/demoRequestWait.ts` instead
    of inheriting a prohibition whose reason is gone."""
    router = _code(ROUTER)
    assert re.search(r"email_service\._send\(", router), "premise: each request sends one email"
    for word in ("request_id", "idempotency", "idempotent_key", "dedupe", "already_received"):
        assert word not in router, (
            f"routers/demo_request.py now mentions {word!r}. If the endpoint can recognise a "
            "repeat, an automatic retry in DemoForm is no longer unsafe — read the header of "
            "lib/demoRequestWait.ts and decide, then update this test."
        )


# ── the form: one send, two clocks, a live region ────────────────────────────

def test_the_form_sends_once_and_nothing_can_resend_it():
    form = _code(FORM)
    sends = re.findall(r"fetch\(\s*`\$\{API\}/api/public/demo-request`", form)
    assert len(sends) == 1, f"DemoForm must POST the request exactly once, found {len(sends)} sends"
    # Two fetches in the file in all: the options call on mount, and the one POST.
    assert len(re.findall(r"\bfetch\(", form)) == 2, "a third fetch is a second send or a second call to the API"
    # A resend needs a timer or a loop to schedule it; the only timers are the
    # two clocks in lib/demoRequestWait.ts, and they never call the API.
    assert "setTimeout" not in form, "a timer in the form can schedule a resend"
    assert not re.search(r"\b(?:retry|retries|attempt)\b", form, re.I), "an automatic retry has appeared in DemoForm"
    wait = _code(WAIT)
    assert "fetch(" not in wait, "the clocks module must not touch the network"


def test_the_one_request_is_abortable_and_its_clocks_are_always_stopped():
    form = _code(FORM)
    assert "new AbortController()" in form
    assert re.search(r"signal:\s*controller\.signal", form), "the abort must reach the request"
    assert "watchSlowRequest(" in form
    assert "controller.abort()" in form, "giving up must actually abandon the request"
    # `stop()` runs on every exit — sent, refused, network error, abort — or a
    # clock left running fires onSlow / onGiveUp against a finished request.
    finally_block = re.search(r"\}\s*finally\s*\{([\s\S]*?)\n\s*\}\s*\n\s*\}", form)
    assert finally_block and "watch.stop()" in finally_block.group(1), "watch.stop() must be in a finally"


def test_the_success_check_is_still_the_envelope_and_not_res_ok():
    """The pin from test_the_marketing_site_says_what_the_product_does, kept true
    by the change: the form still checks `success`, never just `res.ok`."""
    form = _code(FORM)
    assert re.search(r"res\.ok\s*&&\s*body\?\.success", form)


def test_the_wait_is_announced_in_a_live_region_below_the_button():
    form = _code(FORM)
    region = re.search(r'role="status"\s+aria-live="polite"', form)
    assert region, "the waiting copy needs a polite live region, present before it fills"
    assert form.index("Request a demo") < region.start() < form.index("{WAITING_COPY}"), (
        "the live region belongs below the button (so it never moves the button out from under "
        "the cursor) and carries WAITING_COPY"
    )
    assert re.search(r"\{SLOW_COPY\}", form)


def test_the_email_fallback_carries_what_was_typed():
    form = _code(FORM)
    assert "buildDemoMailto(contactEmail, payload)" in form, "the link must be built from the typed payload"
    # Both places the address is offered use the prefilled link, not a bare address.
    assert form.count("href={mailto}") == 2, "the slow notice and the failure notice must both use the prefilled link"


def test_the_failure_does_not_claim_the_request_failed_when_it_timed_out():
    wait = _code(WAIT)
    timeout = re.search(r'export const TIMEOUT_COPY\s*=\s*"([^"]+)"', wait).group(1)
    assert "can't tell whether your request reached us" in timeout
    assert not re.search(r"\bfailed\b", timeout, re.I), "a visitor told it failed resends it, and it may have arrived"
    assert "up to a minute" in re.search(r'export const WAITING_COPY\s*=\s*"([^"]+)"', wait).group(1)


def test_the_clocks_are_set_against_the_measured_cold_start():
    wait = _code(WAIT)
    slow, give_up = _const(wait, "SLOW_AFTER_MS"), _const(wait, "GIVE_UP_AFTER_MS")
    assert 5_000 <= slow <= 30_000, f"the fallback appears after {slow} ms — it should be seconds, not a minute"
    assert give_up > MEASURED_COLD_START_MS * 1.25, (
        f"giving up at {give_up} ms abandons a request that a measured {MEASURED_COLD_START_MS} ms cold "
        "start would still have answered"
    )
    assert give_up <= 180_000, "the abandon clock must end before a browser's own network timeout does"
    assert slow < give_up


# ── the behaviour: the clocks and the mailto, run by the marketing runner ─────────────────

def test_the_behaviour_is_driven_by_the_marketing_runner():
    """The fake-clock and mailto half moved to `apps/marketing/lib/demoRequestWait.test.ts` (POST-A-119): it ran
    here under Node and SKIPPED wherever the backend job's Node could not strip TypeScript. This holds that the
    file is still there and still drives the module, so the move cannot quietly become a deletion."""
    runner = WAIT.with_name("demoRequestWait.test.ts")
    assert runner.is_file(), "the demo form's behavioural tests are gone from the marketing runner"
    src = runner.read_text(encoding="utf-8")
    assert re.search(r'from\s+"\./demoRequestWait\.ts"', src), "the marketing runner no longer imports the module it drives"
    for name in ("watchSlowRequest", "buildDemoMailto", "SLOW_AFTER_MS", "GIVE_UP_AFTER_MS", "MAILTO_MAX_LENGTH"):
        assert re.search(rf"\b{name}\b", src), f"the marketing runner no longer drives {name}"
    assert len(re.findall(r"^test\(", src, re.M)) >= 8, "the marketing runner holds fewer behaviours than it was moved with"


# ── PRE-A-026: the form is shown only when there is an address to fall back to ─────────────────

def test_the_form_needs_an_address_and_the_page_shows_it_only_when_bookings_are_open():
    """Every failure path in the form hands the visitor an email address, and until 16-11-2026 that address
    (hello@practicesync.com) did not exist while the form mailed requests to an inbox nobody read. So the
    form takes the address as a required prop, the Demo page renders it only when `DEMO_BOOKINGS_OPEN`, and
    `DEMO_BOOKINGS_OPEN` is derived from the one contact setting, so the form cannot open without a mailbox."""
    form, page, site = _code(FORM), _code(DEMO_PAGE), _code(SITE)
    assert re.search(r"export function DemoForm\(\{\s*contactEmail\s*\}:\s*\{\s*contactEmail:\s*string\s*\}\)", form), (
        "the form must take the fallback address as a required string")
    assert "CONTACT" not in form, "the form reads the site's contact setting itself instead of being handed an address"
    assert re.search(r"export const DEMO_BOOKINGS_OPEN\s*=\s*CONTACT\.email\s*!==\s*null", site), (
        "bookings must open with the mailbox and not separately from it")
    assert re.search(r"DEMO_BOOKINGS_OPEN\s*&&\s*CONTACT\.email\s*\?\s*\(\s*<DemoForm contactEmail=\{CONTACT\.email\}", page), (
        "the Demo page renders the form only while bookings are open")
    assert "Demo bookings are not open yet." in page, "the closed state says so in words"


def test_no_page_offers_an_address_or_a_number_that_does_not_exist():
    """The address and the number the site used to print were nobody's. While `CONTACT.email` is null no
    marketing file may carry a literal mailbox or a phone number, and nothing reads a phone setting."""
    site = _code(SITE)
    assert re.search(r"export const CONTACT:\s*\{\s*email:\s*string \| null\s*\}\s*=\s*\{\s*email:\s*(null|\"[^\"]+\")\s*\}", site), (
        "CONTACT must hold one optional mailbox and no phone")
    if not re.search(r"email:\s*null", site):
        pytest.skip("a mailbox is set: the pages may print it")
    offenders = []
    for path in sorted((MARKETING / "app").rglob("*.tsx")) + sorted((MARKETING / "components").rglob("*.tsx")):
        code = _code(path)
        # The two that were printed, any tel: link, and the phone setting that held one. Not any +91 number: the
        # demo form's own phone box shows an example the visitor overwrites.
        if re.search(r"[\w.+-]+@practicesync\.com|4718\s*2200|tel:|CONTACT\.phone", code):
            offenders.append(str(path.relative_to(MARKETING)))
    assert not offenders, f"these files print an address or a number nobody answers: {offenders}"
