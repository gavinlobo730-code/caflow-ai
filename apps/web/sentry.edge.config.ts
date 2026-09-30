import * as Sentry from "@sentry/nextjs";

// Not loaded today (see sentry.client.config.ts). The privacy values are pinned
// by scripts/a-session-replay-does-not-record-what-is-on-screen.test.ts.
Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NODE_ENV,
  sendDefaultPii: false,
  // 1.0 traced every request; the API's own default is 0.
  tracesSampleRate: 0,
  enabled: process.env.NODE_ENV === "production",
});
