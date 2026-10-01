/**
 * What may leave the browser in an error report, and what may not (ops-09).
 *
 * WHY THIS EXISTS. A crash report is a copy of a moment in a CA's browser, and this product's moments
 * hold a PAN, a GSTIN, a bank account number, a payslip amount and — in the address bar — two
 * bearer tokens: an engagement-letter link is `/sign/?t=<token>`, and Supabase returns a session in
 * the URL FRAGMENT (`#access_token=…`). An error tracker captures the page URL, every navigation and
 * request URL as a breadcrumb, and the exception message. Left at its defaults it would have sent
 * all of them to a third party, from a site whose screens are read over a client's shoulder.
 *
 * SO THE RULE IS THE INVERSE OF A FILTER. A report carries the error's TYPE, its stack, the route
 * SHAPE and the build that threw it, and everything free-form is scrubbed before it leaves:
 *
 *   * a URL keeps its origin and path and loses the query and the fragment (`scrubUrl`). The PATH is
 *     kept whole, a client id in it included: the id is how a developer finds the row, and it is not
 *     a value anybody typed into a field;
 *   * a message has anything that could be an identifier, an amount, a token or an address replaced
 *     (`scrubText`) — by SHAPE, not by kind, which is deliberate: this module holds no PAN or GSTIN
 *     pattern, because those are statutory rules that live in `apps/api` and `lib/gst/gstin.ts`, and
 *     a second copy here would be a third place to keep in step. "Ten or more letters and digits
 *     with a digit among them" covers a PAN (10), an IFSC (11), a GSTIN (15) and a UAN or account
 *     number without knowing which it is, and it over-redacts a hashed file name, which costs
 *     nothing;
 *   * the user, the request headers, `extra` and the form of every breadcrumb that recorded a
 *     console line are dropped outright.
 *
 * WHAT IT CANNOT DO is read a free-text NAME out of a message. An error message is written by a
 * programmer, and `ModuleErrorBoundary` already refuses to print one on screen for the same reason.
 * That residue is named in docs/operations/error-tracking.md rather than promised away.
 *
 * `beforeSend` also spends a per-session BUDGET. Sentry's free tier is a monthly quota and an
 * exhausted quota drops the very errors this exists to catch (apps/api/main.py says the same of the
 * backend), so a render loop that throws sixty times a second must be one issue and not the month.
 *
 * Pure: no Sentry import, so it is tested on Node and cannot be dragged into a bundle by accident.
 */

/** A Sentry event, as much of it as this module touches. Loose on purpose: the SDK owns the real type. */
export interface LooseEvent {
  message?: string;
  logentry?: { message?: string; formatted?: string; params?: unknown[] };
  exception?: { values?: Array<{ type?: string; value?: string; stacktrace?: unknown }> };
  request?: { url?: string; query_string?: unknown; headers?: Record<string, string>; cookies?: unknown; data?: unknown };
  user?: unknown;
  extra?: unknown;
  breadcrumbs?: LooseBreadcrumb[];
  tags?: Record<string, unknown>;
  transaction?: string;
  contexts?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface LooseBreadcrumb {
  type?: string;
  category?: string;
  message?: string;
  data?: Record<string, unknown>;
  [key: string]: unknown;
}

const UUID = /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi;
const JWT = /\beyJ[\w-]+\.[\w-]+\.[\w-]+/g;
const BEARER = /\bBearer\s+\S+/gi;
const EMAIL = /[^\s@<>()"']+@[^\s@<>()"']+\.[A-Za-z]{2,}/g;
const URL_IN_TEXT = /\bhttps?:\/\/[^\s"'<>)]+/gi;
// Ten or more letters and digits, at least one of them a digit. See the header for why by shape.
// Lookarounds, not `\b`: an underscore is a word character, so `\b` would not split `gsk_` from the key behind it.
const LONG_IDENTIFIER = /(?<![A-Za-z0-9])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{10,}(?![A-Za-z0-9])/g;
// A run of seven or more digits, commas allowed: an amount in paise or rupees, a phone number.
const LONG_NUMBER = /\d[\d,]{5,}\d/g;

/** Origin and path; no query, no fragment. Anything that will not parse is cut at the first `?` or `#`. */
export function scrubUrl(raw: string): string {
  if (typeof raw !== "string") return "";
  try {
    const u = new URL(raw, "http://relative.invalid");
    const origin = u.origin === "http://relative.invalid" && !/^[a-z][a-z0-9+.-]*:/i.test(raw) ? "" : u.origin;
    return `${origin}${u.pathname}`;
  } catch {
    return raw.split(/[?#]/, 1)[0];
  }
}

/** A URL's path with every UUID and numeric segment made `:id`, so one screen is one issue group. */
export function routeShape(raw: string): string {
  return scrubUrl(raw)
    .replace(/^[a-z][a-z0-9+.-]*:\/\/[^/]+/i, "")
    .split("/")
    .map((seg) => (/^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(seg) || /^\d+$/.test(seg) ? ":id" : seg))
    .join("/") || "/";
}

/** Free text with anything that could identify a person, an account or a session replaced. */
export function scrubText(text: string): string {
  if (typeof text !== "string") return "";
  return text
    .replace(URL_IN_TEXT, (m) => scrubUrl(m))
    .replace(JWT, "[token]")
    .replace(BEARER, "Bearer [token]")
    .replace(EMAIL, "[email]")
    .replace(UUID, "[uuid]")
    .replace(LONG_IDENTIFIER, "[id]")
    .replace(LONG_NUMBER, "[number]");
}

/** Console lines are dropped entirely: `console.log(pan)` is the commonest way a value reaches a breadcrumb. */
export function scrubBreadcrumb(crumb: LooseBreadcrumb): LooseBreadcrumb | null {
  if (crumb.category === "console") return null;
  const out: LooseBreadcrumb = { ...crumb };
  if (typeof out.message === "string") out.message = scrubText(out.message);
  if (out.data && typeof out.data === "object") {
    const data: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(out.data)) {
      if (typeof value !== "string") {
        // A status code, a method, a duration. Bodies and headers are never recorded by the SDK, and
        // an object that turns up here anyway is dropped rather than walked.
        if (typeof value === "number" || typeof value === "boolean") data[key] = value;
        continue;
      }
      data[key] = key === "url" || key === "to" || key === "from" ? scrubUrl(value) : scrubText(value);
    }
    out.data = data;
  }
  return out;
}

/** The event that may be sent, or null when it must not be. */
export function scrubEvent(event: LooseEvent): LooseEvent {
  const out: LooseEvent = { ...event };

  delete out.user;
  delete out.extra;

  if (typeof out.message === "string") out.message = scrubText(out.message);
  if (out.logentry) {
    out.logentry = {
      ...out.logentry,
      message: typeof out.logentry.message === "string" ? scrubText(out.logentry.message) : out.logentry.message,
      formatted: typeof out.logentry.formatted === "string" ? scrubText(out.logentry.formatted) : out.logentry.formatted,
      params: undefined,
    };
  }
  if (out.exception?.values) {
    out.exception = {
      ...out.exception,
      values: out.exception.values.map((v) => ({
        ...v,
        value: typeof v.value === "string" ? scrubText(v.value) : v.value,
      })),
    };
  }

  if (out.request) {
    // URL only. Headers carry cookies and Authorization, the query string carries tokens, and a body
    // is somebody's form. The page that threw is the route, which is what a developer needs.
    out.request = typeof out.request.url === "string" ? { url: scrubUrl(out.request.url) } : {};
  }
  if (typeof out.transaction === "string") out.transaction = routeShape(out.transaction);

  if (out.breadcrumbs) {
    out.breadcrumbs = out.breadcrumbs
      .map(scrubBreadcrumb)
      .filter((b): b is LooseBreadcrumb => b !== null);
  }

  const url = event.request?.url;
  out.tags = { ...(out.tags ?? {}), ...(typeof url === "string" ? { route: routeShape(url) } : {}) };
  return out;
}

/** Drop what must not be counted twice and stop one bad page spending the month's quota. */
export class EventBudget {
  private sent = 0;
  private seen = new Map<string, number>();
  // Plain fields rather than constructor parameter properties: `node --experimental-strip-types` erases
  // types and cannot run a parameter property, and this module is tested on it.
  private readonly perSession: number;
  private readonly perFingerprint: number;

  constructor(perSession: number = 20, perFingerprint: number = 3) {
    this.perSession = perSession;
    this.perFingerprint = perFingerprint;
  }

  /** True if this event may be sent; counts it if so. */
  allow(event: LooseEvent): boolean {
    if (this.sent >= this.perSession) return false;
    const first = event.exception?.values?.[0];
    const key = `${first?.type ?? ""}|${first?.value ?? event.message ?? ""}`;
    const n = (this.seen.get(key) ?? 0) + 1;
    this.seen.set(key, n);
    if (n > this.perFingerprint) return false;
    this.sent += 1;
    return true;
  }
}
