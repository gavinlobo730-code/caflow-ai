/**
 * The browser error tracker's one entry point (ops-09). Nothing else in apps/web imports `@sentry/*`
 * — `scripts/the-browser-reports-crashes-without-recording-screens.test.ts` holds that — so what is
 * sent, and what is scrubbed first, is decided in `options.ts` and `scrub.ts` and nowhere else.
 *
 * TWO WAYS A CRASH REACHES IT, and the second is the one that matters here:
 *
 *   1. The SDK's own global handlers (`window.onerror`, unhandled rejections) — installed by `init`.
 *   2. `reportClientError`, called by the error BOUNDARIES. A React error boundary CATCHES the throw,
 *      so the global handler never sees it: without this call every render crash in the product —
 *      which is what `app/error.tsx` and its per-module siblings exist for — would show the CA an
 *      error screen and tell nobody. Wiring the SDK alone would have reported the rare case and
 *      missed the common one.
 *
 * NOTHING HERE MAY TAKE THE APP DOWN. Every path swallows its own failure: a report that cannot be
 * sent, a chunk that will not load, an ad blocker that blocks the ingest host — all of those end with
 * the page exactly as it was. And with no DSN built in, `start` returns before it imports anything,
 * so the SDK is a lazy chunk that is never fetched.
 *
 * The SDK is imported LAZILY, after hydration starts, so it is never on the critical path of a page a
 * CA is waiting for. The cost is a window of a few hundred milliseconds in which a throw is not
 * captured by the global handler; a boundary-caught throw is not lost in that window, because
 * `reportClientError` waits for the SDK rather than dropping the error.
 */
import { buildSentryOptions } from "./options.ts";
import type { BuildEnv } from "./options.ts";

type SentryModule = typeof import("@sentry/nextjs");

/** Read here, and only here, so Next can inline each `NEXT_PUBLIC_*` at build time. */
function buildEnv(): BuildEnv {
  return {
    dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
    release: process.env.NEXT_PUBLIC_SENTRY_RELEASE,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT,
  };
}

let ready: Promise<SentryModule | null> | null = null;

async function start(): Promise<SentryModule | null> {
  const options = buildSentryOptions(buildEnv());
  if (!options) return null;
  try {
    const Sentry = await import("@sentry/nextjs");
    Sentry.init({
      ...options,
      // The defaults, minus what options.ts drops by name, with the breadcrumb integration swapped for
      // one that never records a console line (the scrubber would drop it anyway; not collecting it
      // is the stronger half).
      integrations: (defaults: Array<{ name: string }>) => [
        ...options.integrations(defaults).filter((i) => i.name !== "Breadcrumbs"),
        Sentry.breadcrumbsIntegration({ console: false }),
      ],
    } as unknown as Parameters<typeof Sentry.init>[0]);
    return Sentry;
  } catch {
    return null;
  }
}

/** Resolves to the SDK once started, or null where it is not configured, not in a browser, or failed. */
export function monitoringReady(): Promise<SentryModule | null> {
  if (typeof window === "undefined") return Promise.resolve(null);
  ready ??= start();
  return ready;
}

export function initMonitoring(): void {
  void monitoringReady();
}

/**
 * Report an error an error boundary caught. `where` names the boundary (a module name or "root layout"),
 * and is the only free-text this adds; the error itself goes through `beforeSend` like any other.
 */
export function reportClientError(error: unknown, where: string): void {
  const digest = (error as { digest?: unknown } | null)?.digest;
  void monitoringReady()
    .then((Sentry) =>
      Sentry?.captureException(error, {
        tags: { boundary: where, ...(typeof digest === "string" ? { digest } : {}) },
      }),
    )
    .catch(() => undefined);
}
