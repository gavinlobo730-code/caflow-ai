import { withSentryConfig } from "@sentry/nextjs";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
};

export default withSentryConfig(nextConfig, {
  org: "jlgs-group",
  project: "practicesync",
  // Suppress source map upload warnings when SENTRY_AUTH_TOKEN is not set
  silent: true,
  // Disable server-side auto-instrumentation — static export only
  autoInstrumentServerFunctions: false,
  autoInstrumentMiddleware: false,
  widenClientFileUpload: true,
});
