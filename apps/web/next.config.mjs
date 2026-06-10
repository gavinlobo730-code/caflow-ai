import { setupDevPlatform } from "@cloudflare/next-on-pages/next-dev";

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Removed output: "export" — now using @cloudflare/next-on-pages for edge SSR
  // Dynamic client routes (/clients/[id]/*) require server-side rendering
  trailingSlash: true,
  // Images: disable optimization for Cloudflare Pages compatibility
  images: {
    unoptimized: true,
  },
};

// Enable dev platform bindings in local development
if (process.env.NODE_ENV === "development") {
  await setupDevPlatform();
}

export default nextConfig;
