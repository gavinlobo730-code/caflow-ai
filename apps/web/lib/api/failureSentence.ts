/**
 * What a request that failed outright says to a person (POST-A-406, POST-A-382).
 *
 * WHAT WAS WRONG. A save, a compute or a list that fails BEFORE the server's own answer has no sentence of the product's:
 * the browser throws, and the screen printed the browser's text. A dropped connection is `Failed to fetch` (Chrome),
 * `NetworkError when attempting to fetch resource.` (Firefox) or `Load failed` (Safari); a proxy's error page that arrives
 * with a 200 is `Unexpected token '<', "<html>…" is not valid JSON`. Both are true and neither can be acted on, and the
 * second is read as "the product is broken". The sentence also has to be honest about the thing a CA most needs to know after
 * pressing Save and seeing a failure: WHETHER IT WAS SAVED. A request that got no answer may or may not have reached the
 * server, so a write says that it is not known and what to look at, and never "nothing was changed".
 *
 * WHAT THIS IS. Pure functions and two thin wrappers over `fetch` and `Response.json`, so that a reader can throw the plain
 * sentence AT THE SOURCE and every screen that shows `e.message` is right without being edited, and a screen that catches
 * something it did not read itself (the auth client's token fetch, an unconverted reader) says the same words through
 * `failureSentence`. A refusal the SERVER wrote (a 4xx's `detail`, an envelope's `error`) is never touched: it is the
 * product's own sentence and `lib/api`'s `errorMessage` is its one reader.
 *
 * NO IMPORTS, so a test can run it under plain node and `lib/api/index.ts` can import it without a cycle.
 */

/** "read" is a request that changes nothing: a list, a lookup, and a compute that persists nothing. "write" may have changed something. */
export type Doing = "read" | "write";

/** A GET (or a HEAD) asks; everything else may change something. */
export function doingOf(method: string | null | undefined): Doing {
  const m = (method ?? "GET").toUpperCase();
  return m === "GET" || m === "HEAD" ? "read" : "write";
}

export const NO_ANSWER_READ =
  "The request did not get an answer from the server, so no result came back. Check your connection and try again.";
export const NO_ANSWER_WRITE =
  "The request did not get an answer from the server, so it is not known whether it went through. " +
  "Check your connection and, if this was a change, reload the page to see whether it was recorded before you try again.";
export const NOT_OURS_READ =
  "The server's answer was not the product's own (a network or gateway error page can do this), so no result came back. " +
  "Try again in a moment.";
export const NOT_OURS_WRITE =
  "The server's answer was not the product's own (a network or gateway error page can do this), so it is not known whether " +
  "the request went through. If this was a change, reload the page to see whether it was recorded before you try again.";

export function noAnswerSentence(doing: Doing): string {
  return doing === "read" ? NO_ANSWER_READ : NO_ANSWER_WRITE;
}

export function notOursSentence(doing: Doing): string {
  return doing === "read" ? NOT_OURS_READ : NOT_OURS_WRITE;
}

/** A failed status whose body is a page, not the product's JSON (a gateway's 502 while the API wakes, a proxy's 413). */
export function errorPageSentence(status: number): string {
  const head = `The server answered with an error page (error ${status}) instead of the product's own answer. `;
  // A gateway that is waking or overloaded (a 5xx) is worth another try, and a change may have gone through before it answered; a proxy that turned the request away (a 4xx) will turn it away again.
  return status >= 500
    ? head + "Try again in a moment; if this was a change, reload the page to see whether it was recorded first."
    : head + "Something between this screen and the product answered instead, and trying again is unlikely to help.";
}

/** The request was given up on because the server had not answered in time (`request()` bounds every request). A change may have gone through before the bound ran out. */
export function timedOutSentence(doing: Doing): string {
  return doing === "read"
    ? "This is taking longer than expected — the server didn't respond in time. Please try again."
    : "The server did not answer in time, so it is not known whether the request went through. " +
      "If this was a change, reload the page to see whether it was recorded before you try again.";
}

/** The request was sent a second time, after a dropped connection, and still got no answer. */
export function stillNoAnswerSentence(doing: Doing): string {
  return doing === "read"
    ? "The server is taking too long to respond (it may be waking up). Please retry in a moment."
    : NO_ANSWER_WRITE;
}

/**
 * A request model's own sentence without the framework's label (POST-A-392). Pydantic puts "Value error, " in front of what a validator raised and "Assertion failed, " in front of what an
 * assertion did, and the CA is shown a sentence that begins with a label for a programmer ("Value error, financial_year must look like 2025-26").
 */
export function modelSentence(message: string): string {
  return message.replace(/^\s*(?:value error|assertion failed),\s*/i, "").trim();
}

/** A body that opens as a document (HTML or XML), as a proxy's error page does. A JSON body, plain text and an empty body are not. */
export function looksLikeMarkup(body: string): boolean {
  return /^\s*<(?:!doctype\b|html\b|head\b|body\b|\?xml\b)/i.test(body);
}

// What each engine says when `fetch` rejects (the spec makes every network failure a TypeError and leaves the words to the
// engine): Chrome "Failed to fetch", Firefox "NetworkError when attempting to fetch resource.", Safari "Load failed" (and, older,
// "The request timed out.", "Could not connect to the server."), the engine under Node "fetch failed". Anchored to the WHOLE message
// so a sentence of the product's that happens to contain one of them is not rewritten.
// Phrases specific enough to be taken for the browser's whatever class of error carries them (a reader that rethrew them in a plain Error):
const NO_ANSWER_ANY =
  /^(?:failed to fetch|networkerror when attempting to fetch resource\.?|fetch failed|network request failed|the network connection was lost\.?|the internet connection appears to be offline\.?|the request timed out\.?|could not connect to the server\.?|a server with the specified hostname could not be found\.?)$/i;
// Common words, taken for the browser's only when a TypeError carries them (or the message says so with a prefix: the Supabase client words a failed fetch "TypeError: Load failed"):
const NO_ANSWER_TYPEERROR = /^(?:load failed|network error|terminated|error in body stream|cancelled)$/i;

// What each engine says when `Response.json` cannot read the body (old Safari: "The string did not match the expected pattern.").
const NOT_JSON_MESSAGE =
  /^(?:unexpected token\b[\s\S]*\bis not valid json|unexpected token\b[\s\S]*\bin json at position|unexpected end of json input|unexpected non-whitespace character after json|json\.parse:[\s\S]*|json parse error:[\s\S]*)$/i;
const NOT_JSON_SYNTAXERROR = /^(?:json\b[\s\S]*|[\s\S]*\bjson\b[\s\S]*|the string did not match the expected pattern\.?)$/i;

// The Supabase client (postgrest-js) words a failed fetch as "<error name>: <error message>", so the browser's words arrive behind a prefix that also says what kind of error it was.
const CLIENT_PREFIX = /^(typeerror|fetcherror|syntaxerror):\s*/i;

/**
 * The `code` of the error the browser's Supabase client hands back for a request that got no answer (`lib/supabase/plainRestFetch` answers in the server's place with it). The client returns a
 * PLAIN OBJECT, not an Error, whose `message` is already the product's sentence for what the request was; a screen that holds that object says it by this code, so that the words are the ones
 * for what the SCREEN was doing (a read or a change), as they are for every other failed request.
 */
export const NO_ANSWER_CODE = "PS_NO_ANSWER";

type ErrorLike = { name?: unknown; message?: unknown; code?: unknown };

function asErrorLike(e: unknown): ErrorLike | null {
  return e !== null && typeof e === "object" ? (e as ErrorLike) : null;
}

export type BrowserFailure = "no_answer" | "not_ours";

/** Whether `e` is the browser's own report that a request got no answer, or an answer that was not the product's. Anything else is null. */
export function browserFailureOf(e: unknown): BrowserFailure | null {
  const like = asErrorLike(e);
  if (!like) return null;
  if (like.code === NO_ANSWER_CODE) return "no_answer";
  let name = typeof like.name === "string" ? like.name : "";
  let message = typeof like.message === "string" ? like.message.trim() : "";
  // The auth client reports the same dropped connection under its own name when it tries to renew a session.
  if (name === "AbortError" || name === "TimeoutError" || name === "AuthRetryableFetchError") return "no_answer";
  const prefixed = CLIENT_PREFIX.exec(message);
  if (prefixed) {
    name = prefixed[1].toLowerCase() === "syntaxerror" ? "SyntaxError" : "TypeError";
    message = message.slice(prefixed[0].length);
  }
  if (NO_ANSWER_ANY.test(message)) return "no_answer";
  if (name === "TypeError" && NO_ANSWER_TYPEERROR.test(message)) return "no_answer";
  if (NOT_JSON_MESSAGE.test(message)) return "not_ours";
  // A SyntaxError that names JSON is the body not parsing, whatever an engine's wording is today. (Only a request's own `json()` should be handed to this: a local `JSON.parse` that fails reads the same.)
  if (name === "SyntaxError" && NOT_JSON_SYNTAXERROR.test(message)) return "not_ours";
  return null;
}

/**
 * The sentence to show for something a request threw: the plain sentence for the browser's own words, otherwise the error's
 * own message (the product's sentence, which the readers throw), otherwise `fallback`. `doing` is whether the request asked
 * or may have changed something; a write says that it is not known whether it went through.
 */
export function failureSentence(e: unknown, fallback: string, doing: Doing = "write"): string {
  const kind = browserFailureOf(e);
  if (kind === "no_answer") return noAnswerSentence(doing);
  if (kind === "not_ours") return notOursSentence(doing);
  if (e instanceof Error && e.message.trim()) return e.message;
  return fallback;
}

/**
 * What a reader throws for the browser's own report, in place of it. It is an Error whose message is the plain sentence, and it can be told from an Error the server's answer made: a screen
 * that asks "could I get an answer at all?" (the public page a client opens to sign a letter says "could not be loaded" and not "link unavailable") reads `instanceof PlainFailure`.
 */
export class PlainFailure extends Error {
  kind: BrowserFailure;
  constructor(kind: BrowserFailure, message: string, cause?: unknown) {
    super(message);
    this.name = "PlainFailure";
    this.kind = kind;
    if (cause !== undefined) (this as Error & { cause?: unknown }).cause = cause;
  }
}

/** `e`, or a PlainFailure saying the plain sentence in its place (the browser's error kept as `cause`) when `e` is the browser's own report. */
export function plainFailure(e: unknown, doing: Doing): unknown {
  const kind = browserFailureOf(e);
  if (!kind) return e;
  return new PlainFailure(kind, kind === "no_answer" ? noAnswerSentence(doing) : notOursSentence(doing), e);
}

/** `fetch`, whose rejection is already a sentence for a person. */
export async function fetchPlain(input: RequestInfo | URL, init: RequestInit | undefined, doing: Doing): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (e) {
    throw plainFailure(e, doing);
  }
}

/** What `Response.json()` itself hands back (the browser types it `any`), for the screens that read an answer's fields without a type of their own. */
export type UntypedJson = Awaited<ReturnType<Response["json"]>>;

/** The body of an answer that is meant to be JSON, or an Error saying that it was not the product's own answer. */
export async function jsonPlain<T = unknown>(res: Response, doing: Doing): Promise<T> {
  try {
    return (await res.json()) as T;
  } catch (e) {
    throw plainFailure(e, doing);
  }
}
