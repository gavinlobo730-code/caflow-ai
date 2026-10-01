import type { MetadataRoute } from "next";
import { INDEXABLE_PATHS, pageUrl } from "@/lib/site";

// Written once at build to out/sitemap.xml — see the note in robots.ts.
export const dynamic = "force-static";

/**
 * One entry per page in INDEXABLE_PATHS, in the trailing-slash form the export
 * serves.
 *
 * NO `lastModified`, `changeFrequency` or `priority`. The first would be the
 * BUILD time of every page on every deploy — a claim that all six changed today
 * — and the other two are hints Google has said it ignores. A sitemap that
 * states only what is true is just the list of URLs.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  return INDEXABLE_PATHS.map((path) => ({ url: pageUrl(path) }));
}
