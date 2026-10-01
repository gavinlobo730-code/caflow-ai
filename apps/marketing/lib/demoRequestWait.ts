/**
 * What the "Book a demo" form does while a slow API makes it wait — the timing,
 * the wording and the email fallback, kept apart from the component so each can
 * be run without a browser.
 *
 * WHY THIS EXISTS (market_and_trust-17). The form posts to apps/api on Render's
 * free tier, which sleeps. A visitor who arrives after an idle spell and submits
 * quickly waits for a cold start — measured at 56.55 s — with a button reading
 * "Sending…" and nothing else on the page. To that visitor the form is dead, and
 * the demo request is the main way a new customer reaches the practice.
 *
 * Three things fix what they SEE, none of which changes what is SENT:
 *
 *   1. The wait is named the moment it starts (`WAITING_COPY`), including that
 *      it can take up to a minute, so a long wait reads as expected.
 *   2. After `SLOW_AFTER_MS` the email fallback appears BESIDE the running
 *      request, with what the visitor typed already in the message. The request
 *      is NOT cancelled to show it: the visitor can keep waiting, and a late
 *      success still lands as a success.
 *   3. After `GIVE_UP_AFTER_MS` the request is abandoned, so a dead connection
 *      cannot leave the button on "Sending…" for as long as the browser cares to
 *      wait, and the failure says plainly that nobody can tell whether it
 *      arrived.
 *
 * THERE IS DELIBERATELY NO AUTOMATIC RETRY, although the finding asked for one.
 * `POST /api/public/demo-request` is not idempotent: every call that passes the
 * checks sends the team an email, and the endpoint carries no request id to
 * recognise a repeat by. A client that gives up and sends again cannot know
 * whether the first request was dropped when it disconnected or is still queued
 * behind the waking instance — and if it is still queued, both arrive: one
 * visitor becomes two leads and spends two of their three sends in the per-IP
 * window. The same shape CLAUDE.md records for a filing: a retry needs the
 * reference recorded first, never a blind resend. Making one safe means an
 * idempotency key the server dedupes on, which is an API change and an owner
 * decision; until then the visitor's own choices — keep waiting, email, or press
 * the button again after being told nobody can tell — are the retry.
 *
 * (The page's own `GET …/options` call on load already starts the wake-up, so a
 * visitor who takes a minute over the form rarely meets the cold start at all;
 * the exposure is the fast submitter and a fast returning visitor.)
 *
 * NOTHING HERE IMPORTS `@/…`, so `node --experimental-strip-types` can load it:
 * apps/marketing has no test runner, and
 * apps/api/tests/test_the_demo_form_does_not_look_dead_while_the_api_wakes.py
 * drives this file from the side that does.
 */

/** When the email fallback appears beside the running request. */
export const SLOW_AFTER_MS = 12_000;

/** When the request is abandoned. A measured cold start is 56.55 s; this leaves
 *  a margin over it and still ends well before a browser's own network timeout. */
export const GIVE_UP_AFTER_MS = 90_000;

/** Shown from the instant "Request a demo" is pressed. The second sentence is
 *  the expectation-setting the finding asked for; it is worded as a possibility
 *  ("can take"), because a warm server answers in a second. */
export const WAITING_COPY =
  "Sending your request. If our server has been idle, the first request can take up to a minute — please keep this page open.";

/** Shown beside the running request after `SLOW_AFTER_MS`; the address follows. */
export const SLOW_COPY =
  "Still working. You can keep waiting, or email us instead — your details are filled in for you:";

/** The failure after `GIVE_UP_AFTER_MS`. It does NOT claim the request failed:
 *  it may have arrived, and a visitor told "it failed" resends it. */
export const TIMEOUT_COPY =
  "We didn't get a reply from our server in time, so we can't tell whether your request reached us. The surest way is to email us — your details are filled in for you:";

export interface Timers {
  set: (fn: () => void, ms: number) => unknown;
  clear: (id: unknown) => void;
}

const REAL_TIMERS: Timers = {
  set: (fn, ms) => setTimeout(fn, ms),
  clear: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
};

export interface SlowRequestHandlers {
  /** The request is taking longer than it should; show the email fallback. */
  onSlow: () => void;
  /** Stop waiting; the caller aborts the request. */
  onGiveUp: () => void;
}

/**
 * Start the two clocks for one request. `stop()` cancels both and is safe to
 * call twice; nothing fires after it, so a response that arrives at 11.9 s never
 * sees the fallback and one that arrives at 40 s never sees the abort.
 *
 * `timers` and `after` are parameters so a test drives it with a fake clock.
 */
export function watchSlowRequest(
  handlers: SlowRequestHandlers,
  timers: Timers = REAL_TIMERS,
  after: { slowMs?: number; giveUpMs?: number } = {},
): { stop: () => void } {
  let stopped = false;
  const slow = timers.set(() => {
    if (!stopped) handlers.onSlow();
  }, after.slowMs ?? SLOW_AFTER_MS);
  const giveUp = timers.set(() => {
    if (!stopped) handlers.onGiveUp();
  }, after.giveUpMs ?? GIVE_UP_AFTER_MS);
  return {
    stop() {
      stopped = true;
      timers.clear(slow);
      timers.clear(giveUp);
    },
  };
}

export interface DemoFields {
  name: string;
  firm_name: string;
  email: string;
  phone: string | null;
  firm_size: string | null;
  message: string | null;
}

/** Many mail clients cut a `mailto:` URL somewhere near 2,000 characters, and a
 *  cut URL loses the END — the message. */
export const MAILTO_MAX_LENGTH = 1800;

const SHORTENED_NOTE = " … (shortened — the full text is still in the form)";

/**
 * The `mailto:` link that carries what the visitor typed, so the fallback is
 * "send this" and not "start again". Lines are joined with CRLF, which is what
 * RFC 6068 asks of a mailto body.
 *
 * Only the message can be long (the other fields are capped at a few hundred
 * characters by the form), so it is the one that is shortened, from the end, to
 * keep the whole URL within `maxLength` — and the shortening says so.
 */
export function buildDemoMailto(
  to: string,
  f: DemoFields,
  maxLength: number = MAILTO_MAX_LENGTH,
): string {
  const head = [
    "Hello,",
    "",
    "I asked for a demo through your website and am sending the details by email instead.",
    "",
    `Name: ${f.name}`,
    `Firm: ${f.firm_name}`,
    `Email: ${f.email}`,
    ...(f.phone ? [`Phone: ${f.phone}`] : []),
    ...(f.firm_size ? [`Practice size: ${f.firm_size}`] : []),
  ];
  const href = (message: string | null): string => {
    const body = [...head, ...(message ? ["", "What I would like to see:", message] : [])].join("\r\n");
    return `mailto:${to}?subject=${encodeURIComponent("Demo request")}&body=${encodeURIComponent(body)}`;
  };

  let message: string | null = f.message && f.message.trim() ? f.message : null;
  let shortened = false;
  const render = () => href(message && shortened ? `${message}${SHORTENED_NOTE}` : message);
  let url = render();
  while (url.length > maxLength && message) {
    shortened = true;
    message = message.slice(0, Math.floor(message.length * 0.8));
    if (!message.trim()) message = null;
    url = render();
  }
  return url;
}
