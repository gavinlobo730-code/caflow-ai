/**
 * The options the browser error tracker is started with, and the only place they are decided (ops-09).
 *
 * WHAT THIS REPLACED. `sentry.client.config.ts` and `sentry.edge.config.ts` sat in this directory and
 * NOTHING IMPORTED EITHER: `@sentry/nextjs` loads those files through `withSentryConfig` in
 * next.config.mjs, and there was none, so the browser reported nothing while looking wired. They also
 * said `tracesSampleRate: 1.0` and a 10% session replay — a transaction quota spent on every page view
 * and a recording of screens holding PAN, payroll and bank figures, "masked" or not. Both files are
 * deleted: an unreachable config is worse than none, because it reads as a control.
 *
 * THIS IS AN ERROR-REPORTING INSTALL, NOT AN APM ONE — the same call apps/api/main.py makes for the
 * backend and for the same reason: a quota that runs out DROPS the errors the install exists to
 * capture. So, stated as the rule the guard holds:
 *
 *   * NO TRACING. `tracesSampleRate` is left UNSET, not zero: in Sentry's SDK a defined rate of 0
 *     still switches tracing on, installs the browser-tracing integration and attaches `sentry-trace`
 *     and `baggage` headers to outgoing requests, which are extra preflights to the API. The
 *     integration is also filtered out by name below.
 *   * NO REPLAY, at all — not "errors only with masking". A recording of a payroll or bank screen is a
 *     different risk from a stack trace, it is a decision for the owner and not a default, and
 *     enabling it means routes that must be blocked (payroll, bank, the client portal). Until that is
 *     decided there is no `replayIntegration` anywhere in apps/web and the guard says so.
 *   * NO DEFAULT PII, no user, no request headers or body (`scrub.ts`).
 *   * A BUDGET per page session (`EventBudget`).
 *
 * THE DSN IS A BUILD-TIME VARIABLE because this is a static export: `NEXT_PUBLIC_SENTRY_DSN`, inlined
 * into the bundle, as `NEXT_PUBLIC_API_URL` is. A DSN is a public identifier, like the Supabase anon
 * key beside it in wrangler.toml — it lets a browser SEND events to the project, not read them. With
 * none set nothing starts, nothing is fetched, and `buildSentryOptions` answers `null`.
 *
 * THE RELEASE is the commit Cloudflare built (`CF_PAGES_COMMIT_SHA`, which its build environment
 * documents as the value to pass to error reporting), carried in by next.config.mjs, so an issue says
 * which deploy threw it.
 *
 * Pure: takes the build values as an argument, imports nothing from the SDK, tested on Node.
 */
import { EventBudget, scrubBreadcrumb, scrubEvent } from "./scrub.ts";
import type { LooseBreadcrumb, LooseEvent } from "./scrub.ts";

export interface BuildEnv {
  dsn?: string;
  release?: string;
  environment?: string;
}

/** Integrations by the name the SDK gives them. Everything here is either a cost or a recording. */
export const DROPPED_INTEGRATIONS: readonly string[] = [
  "BrowserTracing",
  "Replay",
  "ReplayCanvas",
  "Feedback",
  "GraphQLClient",
  "BrowserProfiling",
  "LaunchDarkly",
  "Console",
  "CaptureConsole",
  // Release-health sessions: an envelope on every page load, for a crash-free-sessions figure nobody has
  // asked for. It is a decision to turn ON when somebody wants that number, not a default that spends a
  // request per navigation for every CA.
  "BrowserSession",
];

/** Noise that would spend the quota on nothing a developer can act on. */
export const IGNORED_ERRORS: Array<string | RegExp> = [
  /ResizeObserver loop (limit exceeded|completed with undelivered notifications)/,
  // The reason `lib/api` aborts a request at 45 s, and the reason the user sees a retry prompt.
  /^AbortError/,
  // A script a browser extension injected, which surfaces as an error with no frame of ours.
  /^Script error\.?$/,
];

export const DENIED_URLS: RegExp[] = [
  /^chrome-extension:\/\//i,
  /^moz-extension:\/\//i,
  /^safari(-web)?-extension:\/\//i,
];

export interface MonitoringOptions {
  dsn: string;
  release?: string;
  environment: string;
  sendDefaultPii: false;
  sampleRate: number;
  maxBreadcrumbs: number;
  attachStacktrace: true;
  ignoreErrors: Array<string | RegExp>;
  denyUrls: RegExp[];
  beforeSend: (event: LooseEvent) => LooseEvent | null;
  beforeBreadcrumb: (crumb: LooseBreadcrumb) => LooseBreadcrumb | null;
  /** Filters the SDK's defaults by name. Never adds one: what is added is decided in index.ts. */
  integrations: (defaults: Array<{ name: string }>) => Array<{ name: string }>;
  // Deliberately absent — and asserted absent by scripts/the-browser-reports-crashes-...test.ts:
  //   tracesSampleRate, tracePropagationTargets, replaysSessionSampleRate, replaysOnErrorSampleRate
}

/** The options, or `null` where no DSN was built in — in which case nothing starts. */
export function buildSentryOptions(env: BuildEnv, budget: EventBudget = new EventBudget()): MonitoringOptions | null {
  const dsn = (env.dsn ?? "").trim();
  if (!dsn) return null;
  return {
    dsn,
    release: env.release?.trim() || undefined,
    environment: env.environment?.trim() || "production",
    sendDefaultPii: false,
    // Every distinct error; what stops a loop is the budget, not sampling, because a sampled 10% of an
    // outage is how a first occurrence goes unreported.
    sampleRate: 1,
    maxBreadcrumbs: 20,
    attachStacktrace: true,
    ignoreErrors: IGNORED_ERRORS,
    denyUrls: DENIED_URLS,
    beforeSend: (event) => {
      const clean = scrubEvent(event);
      return budget.allow(clean) ? clean : null;
    },
    beforeBreadcrumb: scrubBreadcrumb,
    integrations: (defaults) => defaults.filter((i) => !DROPPED_INTEGRATIONS.includes(i.name)),
  };
}
