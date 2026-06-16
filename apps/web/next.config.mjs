/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
  env: {
    // Build-time guarantee for the public backend URL. NEXT_PUBLIC_* values are
    // INLINED at build time (a static export can't read runtime env), so a
    // production build that somehow lacks the env var must NOT silently fall
    // back to the localhost dev default — that would make every FastAPI call
    // (e.g. /platform's admin check) fail in the browser. An explicit
    // NEXT_PUBLIC_API_URL (Cloudflare build var / wrangler [vars]) always wins;
    // otherwise production gets the real backend and dev keeps localhost.
    NEXT_PUBLIC_API_URL:
      process.env.NEXT_PUBLIC_API_URL ||
      (process.env.NODE_ENV === "production"
        ? "https://practicesync-ai.onrender.com"
        : "http://localhost:8000"),
  },
};

export default nextConfig;
