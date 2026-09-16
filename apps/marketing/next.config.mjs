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
    // env), so production must resolve to the real app origin, not localhost.
    // Today the app lives on its Cloudflare Pages URL (the project is labeled
    // "practicesync-ai" in the dashboard, but its *.pages.dev subdomain is
    // locked to the name it was created under: caflow-ai). Once a custom
    // domain is attached, change this (or the Cloudflare build var) to
    // https://app.<domain>.
    NEXT_PUBLIC_APP_URL:
      process.env.NEXT_PUBLIC_APP_URL ||
      (process.env.NODE_ENV === "production"
        ? "https://caflow-ai.pages.dev"
        : "http://localhost:3000"),
    // The FastAPI backend (apps/api on Render). The marketing site reaches it
    // for exactly one thing — posting a "Book a demo" request to the public
    // /api/public/demo-request endpoint — because a static export has no
    // server of its own to send mail from. It holds no key and reads nothing:
    // that endpoint is unauthenticated by design and takes no tenant id.
    //
    // Inlined at build time like NEXT_PUBLIC_APP_URL above, so production must
    // resolve to the real API origin rather than localhost. When it is left at
    // the localhost default in a deployed build the form says so and offers the
    // mailto instead of failing silently — see app/(site)/demo/page.tsx.
    NEXT_PUBLIC_API_URL:
      process.env.NEXT_PUBLIC_API_URL ||
      (process.env.NODE_ENV === "production"
        ? "https://practicesync-api.onrender.com"
        : "http://localhost:8000"),
  },
};

export default nextConfig;
