/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export — deployed to Cloudflare Pages exactly like apps/web.
  output: "export",
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
  env: {
    // The URL of the actual application (apps/web). The marketing site never
    // imports app code — it only *links* to it (login, client portal, signup),
    // so everything the app needs is reachable through this one origin.
    // NEXT_PUBLIC_* is inlined at build time (a static export can't read runtime
    // env), so production must resolve to the real app subdomain, not localhost.
    NEXT_PUBLIC_APP_URL:
      process.env.NEXT_PUBLIC_APP_URL ||
      (process.env.NODE_ENV === "production"
        ? "https://app.practicesync.com"
        : "http://localhost:3000"),
  },
};

export default nextConfig;
