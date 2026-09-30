import type { MetadataRoute } from "next";
import { fileUrl } from "@/lib/site";

// `output: "export"` has no server to answer /robots.txt from, so this is
// evaluated once at build and written to out/robots.txt. Next refuses a
// metadata route in a static export unless it says so.
export const dynamic = "force-static";

/**
 * Everything is open to crawlers, and the sitemap is named so they find it.
 *
 * Nothing is disallowed on purpose. The only page that does not belong in a
 * results list — the `/access` sign-in chooser — is left out of the SITEMAP
 * rather than blocked here: a URL blocked in robots.txt can still be listed
 * (without a description) if another page links to it, which is the opposite of
 * what blocking is for. See INDEXABLE_PATHS in lib/site.ts.
 *
 * The sitemap URL is built from SITE_URL, which is overridable for a custom
 * domain, so this stays right the day the site moves off *.pages.dev.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/" }],
    sitemap: fileUrl("/sitemap.xml"),
  };
}
