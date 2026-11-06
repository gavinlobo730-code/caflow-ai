/**
 * What the browser's second data path says when a request gets no answer (POST-A-413).
 *
 * WHAT WAS WRONG. About two hundred screens read and write straight through the Supabase client (`.from()`), and when the
 * connection drops the client does not throw: it hands back `{ error: { message } }` and builds that message itself, as
 * "<error name>: <error message>" (postgrest-js 2.118). A CA whose connection dropped while a list loaded was shown
 * `TypeError: Failed to fetch` (Firefox: `TypeError: NetworkError when attempting to fetch resource.`, Safari: `TypeError: Load failed`), at 63 lines in 35 files
 * that throw that error or print its message, and a screen that printed it said nothing about whether a change it was making had been recorded.
 *
 * WHAT THIS DOES. It is the `fetch` the client is given. When the browser reports that a request to PostgREST (`/rest/v1/`) got no answer, it answers in
 * the server's place with the error PostgREST itself would have sent, whose `message` is the product's sentence (`lib/api/failureSentence`: a read says that
 * no result came back, a change says that it is not known whether it went through and to reload the page to see whether it was recorded) and whose `code` says
 * that it is this one (`NO_ANSWER_CODE`), so that a screen holding the error says it for what the SCREEN was doing. The client reads that as it reads any
 * refusal, so `error.message` is the sentence at every one of those places without editing them, the way `fetchPlain` does for `lib/api`.
 *
 * A DROP AFTER THE HEADERS ARRIVED IS THE SAME DROP. The client reads the body after the headers have come, and a connection that dies in between rejects
 * THERE, where the client words it as `TypeError: network error` with a status of 0. So the body is read here, inside the same try, and the client is handed
 * the answer rebuilt (the same status, status text and headers) or, if the body never came, the same sentence.
 *
 * WHY A RESPONSE AND NOT A THROW. The client wraps whatever `fetch` throws as "<name>: <message>", so a sentence thrown from here would arrive behind a
 * prefix. A response is read as it is. And it keeps the client's own policy for a dropped connection, which is why the status is 503: the client sends a
 * GET or a HEAD again, up to three times, one, two and four seconds apart, when `fetch` rejects and when the server answers 503; it never sends a change
 * twice. Each of those attempts comes through here, so a read that fails all four is answered once, with the sentence.
 *
 * WHAT IT LEAVES ALONE. A request that is not to PostgREST (sign-in goes to `/auth/v1/` and its screens read their own errors), a request somebody cancelled
 * or that ran out of time (`AbortError`, `TimeoutError`), and a rejection that is not the browser's report of a dropped connection (a programming error
 * stays the programming error it is). A `.rpc()` is a POST, so one that only reads would be worded as a change; nothing in the browser calls one.
 *
 * The only import is the sentence module, which imports nothing, so a test can run this under plain node.
 */
import { browserFailureOf, doingOf, NO_ANSWER_CODE, noAnswerSentence } from "../api/failureSentence.ts";

/** The path PostgREST answers on: every table read and write the browser makes. */
const REST_PATH = "/rest/v1/";

function addressOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

function methodOf(input: RequestInfo | URL, init: RequestInit | undefined): string {
  if (init?.method) return init.method;
  if (typeof input === "object" && !(input instanceof URL) && typeof input.method === "string") return input.method;
  return "GET";
}

/** `base`, which answers for a request to PostgREST that got no answer. `base` is a parameter so a test can make it fail. */
export function makePlainRestFetch(base: typeof fetch): typeof fetch {
  return async (input, init) => {
    const toPostgrest = addressOf(input).includes(REST_PATH);
    try {
      const res = await base(input, init);
      if (!toPostgrest) return res;
      // The body is read here so that a connection that dies after the headers is the drop it is. A status that carries no body (204, 205, 304) must be built with none.
      const text = await res.text();
      return new Response(text === "" ? null : text, { status: res.status, statusText: res.statusText, headers: res.headers });
    } catch (e) {
      if (!toPostgrest) throw e;
      const name = e !== null && typeof e === "object" ? (e as { name?: unknown }).name : undefined;
      if (name === "AbortError" || name === "TimeoutError") throw e;
      if (browserFailureOf(e) !== "no_answer") throw e;
      // The body is what PostgREST sends for a refusal: { message, details, hint, code }.
      const body = { message: noAnswerSentence(doingOf(methodOf(input, init))), details: "", hint: "", code: NO_ANSWER_CODE };
      return new Response(JSON.stringify(body), {
        status: 503,
        statusText: "Service Unavailable",
        headers: { "Content-Type": "application/json" },
      });
    }
  };
}

/** The `fetch` the browser's Supabase client is made with (`lib/supabase/client.ts`). */
export const plainRestFetch: typeof fetch = makePlainRestFetch((input, init) => fetch(input, init));
