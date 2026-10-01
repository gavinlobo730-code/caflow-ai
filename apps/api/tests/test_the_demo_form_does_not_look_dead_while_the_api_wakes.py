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

THE GUARD IS ON THE PYTHON SIDE because apps/marketing has no test runner (it
lints, typechecks and builds — the Schedule III caption lesson). The behavioural
half drives `lib/demoRequestWait.ts` under Node with a fake clock and SKIPS,
rather than passing silently, where Node cannot run TypeScript (`--experimental-
strip-types`, Node 22.6+); the source-level half always runs.
"""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MARKETING = REPO / "apps" / "marketing"
FORM = MARKETING / "components" / "DemoForm.tsx"
WAIT = MARKETING / "lib" / "demoRequestWait.ts"
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
    assert "buildDemoMailto(CONTACT.email, payload)" in form, "the link must be built from the typed payload"
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


# ── the behaviour: the clocks and the mailto, run under Node ─────────────────

_HARNESS = r"""
import { watchSlowRequest, buildDemoMailto, SLOW_AFTER_MS, GIVE_UP_AFTER_MS, MAILTO_MAX_LENGTH } from "%(url)s";

function fakeClock() {
  let now = 0, id = 0; const q = [];
  return {
    timers: {
      set: (fn, ms) => { const t = { id: ++id, at: now + ms, fn, live: true }; q.push(t); return t.id; },
      clear: (i) => { const t = q.find((x) => x.id === i); if (t) t.live = false; },
    },
    advance(ms) {
      const target = now + ms;
      for (;;) {
        const next = q.filter((t) => t.live && t.at <= target).sort((a, b) => a.at - b.at)[0];
        if (!next) break;
        now = next.at; next.live = false; next.fn();
      }
      now = target;
    },
  };
}
const run = (steps) => {
  const c = fakeClock(); const events = []; const snap = [];
  const w = watchSlowRequest({ onSlow: () => events.push("slow"), onGiveUp: () => events.push("giveup") }, c.timers);
  for (const s of steps) { if (s === "stop") w.stop(); else c.advance(s); snap.push(events.slice()); }
  return snap;
};
const out = {};
out.constants = { SLOW_AFTER_MS, GIVE_UP_AFTER_MS };
// A: nobody answers. The fallback appears at SLOW, the abandon at GIVE_UP, each once.
out.A = run([SLOW_AFTER_MS - 1, 1, GIVE_UP_AFTER_MS - SLOW_AFTER_MS - 1, 1, 500000]);
// B: answered fast. Nothing ever fires, however long the page stays open.
out.B = run([5000, "stop", 500000]);
// C: answered after the fallback showed but before the abandon. No abandon.
out.C = run([SLOW_AFTER_MS + 1, 28000, "stop", 500000]);
// D: stop twice is harmless.
out.D = run([100, "stop", "stop", 500000]);

const fields = { name: "CA Priya Raghavan", firm_name: "Raghavan & Associates", email: "priya@raghavan.in",
  phone: "+91 98765 43210", firm_size: "2–5 people", message: "GSTR-1 for 40 clients,\nTally today." };
const url = buildDemoMailto("hello@practicesync.com", fields);
const q = new URL(url.replace("mailto:", "http://x/")).searchParams;
out.mailto = { url, subject: q.get("subject"), body: q.get("body"), startsWith: url.startsWith("mailto:hello@practicesync.com?") };
out.noOptional = decodeURIComponent(new URL(buildDemoMailto("a@b.c", { ...fields, phone: null, firm_size: null, message: null }).replace("mailto:", "http://x/")).searchParams.get("body"));
const long = buildDemoMailto("hello@practicesync.com", { ...fields, message: "word ".repeat(2000) });
out.long = { length: long.length, max: MAILTO_MAX_LENGTH, body: new URL(long.replace("mailto:", "http://x/")).searchParams.get("body") };
console.log(JSON.stringify(out));
"""


def _node_can_run_typescript() -> bool:
    """Probed with a real `.ts` FILE: `-e` does not strip types, so probing with
    it would report "cannot" on a Node that can."""
    node = shutil.which("node")
    if not node:
        return False
    with tempfile.TemporaryDirectory() as d:
        probe_file = Path(d) / "probe.ts"
        probe_file.write_text("const x: number = 1;\nconsole.log(x);\n", encoding="utf-8")
        probe = subprocess.run(
            [node, "--experimental-strip-types", "--no-warnings", str(probe_file)],
            capture_output=True, text=True, timeout=30,
        )
    return probe.returncode == 0 and probe.stdout.strip() == "1"


@pytest.fixture(scope="module")
def ran():
    if not _node_can_run_typescript():
        pytest.skip("node cannot run TypeScript here (needs 22.6+ with --experimental-strip-types)")
    script = _HARNESS % {"url": WAIT.as_uri()}
    proc = subprocess.run(
        [shutil.which("node"), "--experimental-strip-types", "--no-warnings", "--input-type=module", "-"],
        input=script, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"the harness failed:\n{proc.stderr[-1500:]}"
    return json.loads(proc.stdout)


def test_with_no_answer_the_fallback_appears_then_the_request_is_abandoned_once_each(ran):
    a = ran["A"]
    assert a[0] == [], "nothing may fire a millisecond before the fallback is due"
    assert a[1] == ["slow"], "the email fallback appears at SLOW_AFTER_MS"
    assert a[2] == ["slow"], "and the request is still running a millisecond before it is abandoned"
    assert a[3] == ["slow", "giveup"], "it is abandoned at GIVE_UP_AFTER_MS"
    assert a[4] == ["slow", "giveup"], "each clock fires once, never again"


def test_a_fast_answer_never_sees_the_fallback_or_the_abandon(ran):
    assert ran["B"] == [[], [], []]


def test_a_late_answer_is_not_abandoned_after_the_fact(ran):
    c = ran["C"]
    assert c[0] == ["slow"], "the fallback showed"
    assert c[-1] == ["slow"], "an answer that arrives before the abandon clock cancels it"


def test_stopping_twice_is_harmless(ran):
    assert ran["D"][-1] == []


def test_the_constants_the_harness_ran_against_are_the_ones_in_the_file(ran):
    src = _code(WAIT)
    assert ran["constants"] == {
        "SLOW_AFTER_MS": _const(src, "SLOW_AFTER_MS"),
        "GIVE_UP_AFTER_MS": _const(src, "GIVE_UP_AFTER_MS"),
    }


def test_the_mailto_carries_every_field_the_visitor_typed(ran):
    m = ran["mailto"]
    assert m["startsWith"]
    assert m["subject"] == "Demo request"
    body = m["body"]
    for typed in ("CA Priya Raghavan", "Raghavan & Associates", "priya@raghavan.in",
                  "+91 98765 43210", "2–5 people", "GSTR-1 for 40 clients,", "Tally today."):
        assert typed in body, f"{typed!r} was typed and is missing from the email"
    assert "\r\n" in body, "RFC 6068 asks for CRLF line breaks in a mailto body"


def test_an_empty_optional_field_is_left_out_not_printed_as_null(ran):
    body = ran["noOptional"]
    assert "Phone:" not in body and "Practice size:" not in body and "What I would like to see" not in body
    assert "null" not in body and "undefined" not in body


def test_a_very_long_message_is_shortened_so_the_link_survives_and_says_so(ran):
    long = ran["long"]
    assert long["length"] <= long["max"], "a mailto URL past ~2,000 characters is cut by mail clients, losing the END"
    assert "shortened" in long["body"]
    assert long["body"].count("word") > 50, "it is shortened, not discarded"
    assert "CA Priya Raghavan" in long["body"], "the identifying fields are never the ones dropped"
