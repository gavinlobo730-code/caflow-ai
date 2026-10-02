/**
 * The id the server gave a failed request, worded for a person to quote (ops-11).
 *
 * WHY THIS EXISTS. The API puts `X-Request-ID` on every response and the same id on the one JSON log line it
 * writes for the request, so "it failed at 11:05" can be answered with one search instead of a read of
 * everything near 11:05. A CA only quotes what they can see: a 5xx whose body the server wrote already says
 * "(reference <id>)", and one a proxy or a framework answered carries the id only in the header, which
 * `lib/api` appends here.
 *
 * ONLY A SERVER-SIDE FAILURE. A 4xx is the CA's to fix and its sentence is already specific; a reference on
 * every refusal would be noise on the screens that are read most.
 *
 * The id is shown only when it has the shape the server generates or accepts, so a header set by something
 * between us and the browser is never rendered. That shape is pinned from the Python side
 * (`apps/api/tests/test_every_request_carries_an_id.py`), the way every other mirror in this app is: a guard
 * written here would compare this file with a copy of itself.
 *
 * NO NETWORK, NO IMPORTS, so a test can run it under plain node.
 */

/** Mirrors `core/request_context._REQUEST_ID`. */
const REQUEST_ID_SHAPE = /^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$/;

type HeaderReader = { get(name: string): string | null } | null | undefined;

/** The request id on a response's headers, or null when absent, unreadable or not the expected shape. */
export function requestIdOf(headers: HeaderReader): string | null {
  try {
    const value = headers?.get("X-Request-ID");
    return typeof value === "string" && REQUEST_ID_SHAPE.test(value) ? value : null;
  } catch {
    return null;
  }
}

/** `message`, with "(reference <id>)" after it for a server-side failure that does not already say so. */
export function withReference(message: string, status: number, headers: HeaderReader): string {
  if (!(status >= 500)) return message;
  const id = requestIdOf(headers);
  if (!id || message.includes(id)) return message;
  return `${message} (reference ${id})`;
}
