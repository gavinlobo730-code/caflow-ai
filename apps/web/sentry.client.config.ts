import * as Sentry from "@sentry/nextjs";

// WHAT THIS FILE IS FOR, AND WHAT IT IS NOT.
//
// The privacy settings below are the ones that apply the day the browser SDK is
// switched on. Nothing loads this file today — next.config.mjs has no
// `withSentryConfig` and there is no `instrumentation-client.ts` — so the browser
// sends nothing to Sentry. That is a decision for the owner (Sentry is a
// sub-processor and its region is not recorded, see docs/compliance/
// 01-what-exists-today.md §2), not something a configuration edit should make by
// accident. `scripts/a-session-replay-does-not-record-what-is-on-screen.test.ts`
// pins the values so that wiring it up does not start from the old ones.
//
// Why each is what it is. A practice's screens carry a CLIENT's invoices, bank
// statements, payslips and PAN/GSTIN — third-party personal data the practice
// holds under a duty of confidence (DPDP Act 2023; ICAI Code of Ethics).
//   - blockAllMedia: a scanned bill or statement shown for extraction is an
//     <img>/<object>/<embed>, and with it off the picture itself is recorded and
//     uploaded. Text masking does nothing for pixels.
//   - maskAllInputs / maskAllText: already the SDK defaults; written out so a
//     reader can see they are decisions and a change to one shows in a diff.
//   - networkCaptureBodies false, no allow-listed URLs: request and response
//     bodies are the API's JSON, which is the ledger.
//   - replaysSessionSampleRate 0: recording ordinary sessions at random is the
//     exposure with no diagnostic payoff; a replay is kept only around an error.
//   - tracesSampleRate 0: matches the API (SENTRY_TRACES_SAMPLE_RATE defaults to
//     0), and 1.0 would record every page load and every API call's URL.
//   - sendDefaultPii false: the API already says so (main.py), the browser
//     should not be the one place that does not.
Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NODE_ENV,
  sendDefaultPii: false,
  tracesSampleRate: 0,
  replaysSessionSampleRate: 0,
  replaysOnErrorSampleRate: 0.25,
  integrations: [
    Sentry.replayIntegration({
      maskAllText: true,
      maskAllInputs: true,
      blockAllMedia: true,
      networkDetailAllowUrls: [],
      networkCaptureBodies: false,
    }),
  ],
  // Only enable in production
  enabled: process.env.NODE_ENV === "production",
});
