// Central config for the marketing site: where the actual app lives, and the
// cross-app links the marketing pages point at. The app is a separate origin
// (apps/web — dashboard-labeled "practicesync-ai", but its *.pages.dev
// subdomain is caflow-ai.pages.dev, fixed at project creation), so every
// "log in / sign up" action is a plain link to that origin — the marketing
// site holds no auth logic itself.

export const APP_URL =
  process.env.NEXT_PUBLIC_APP_URL || "https://caflow-ai.pages.dev";

/**
 * This site's own origin, which `metadataBase` needs before a relative social
 * image can resolve to an absolute URL.
 *
 * Every consumer of an Open Graph tag fetches the image from its own servers,
 * from a URL it has never seen a page for — so `/og.jpg` on its own resolves
 * against nothing and the preview is dropped. Next warns about a missing
 * `metadataBase` in dev and then silently falls back to localhost, which is why
 * this is worth stating rather than leaving to a default.
 *
 * Overridable, the same way APP_URL is, for a custom domain later — the
 * marketing project's *.pages.dev subdomain is `practicesync`, which is NOT the
 * app's (`caflow-ai`); the two are separate Cloudflare Pages projects.
 */
export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://practicesync.pages.dev";

/**
 * THE PAGES A SEARCH ENGINE IS ASKED TO LIST — the sitemap's whole content, and
 * the one list it is built from (market_and_trust-29).
 *
 * It is a list and not a walk of `app/` because a static export has no
 * filesystem to read at run time and a sitemap must be written at build time,
 * but it is not left to memory either:
 * apps/api/tests/test_the_site_can_be_found_and_says_which_page_is_which.py
 * compares it with the page files under `app/(site)/`, so a page added without
 * an entry here — or an entry whose page was deleted — fails there.
 *
 * `/access` is deliberately NOT here. It is the sign-in chooser (firm workspace
 * or client portal): it has nothing for a search to rank and listing it invites
 * people to land on a login gateway from a results page. It is not blocked in
 * robots.txt either — a blocked URL that other pages link to can still be
 * listed, with no description, which is worse than a page that simply is not
 * offered.
 */
export const INDEXABLE_PATHS = [
  "/",
  "/products",
  "/pricing",
  "/support",
  "/resources",
  "/demo",
  "/privacy",
] as const;

/**
 * The absolute URL of a PAGE on this site, in the form the static export
 * serves it: with a trailing slash (`trailingSlash: true` in next.config.mjs),
 * because `/products` answers with a redirect to `/products/` and a sitemap or
 * canonical that names the redirecting form asks a crawler to start from a hop.
 */
export function pageUrl(path: string): string {
  const withSlash = path.endsWith("/") ? path : `${path}/`;
  return new URL(withSlash, SITE_URL).toString();
}

/** The absolute URL of a FILE at the root (robots.txt, sitemap.xml) — no
 *  trailing slash, which would name a path that does not exist. */
export function fileUrl(path: string): string {
  return new URL(path, SITE_URL).toString();
}

/** Cross-app destinations (routes that live in apps/web). */
export const appLinks = {
  /** Chartered Accountant / firm staff sign-in (email + password + TOTP MFA). */
  firmLogin: `${APP_URL}/login`,
  /** Client portal sign-in (email + password; access is provisioned by the CA,
   *  who sends an invite the client uses once to set their password). */
  clientPortal: `${APP_URL}/portal/login`,
  /** Employee portal sign-in — payslips, leave, Form 12BB and tax deducted, for
   *  the staff of a client whose payroll runs here. The SAME sign-in page as
   *  the client portal: one password login serves both, and apps/web routes the
   *  identity to the right portal after it resolves who they are. Named
   *  separately so the two are distinguishable in copy and analytics even
   *  though the URL is shared today. */
  employeePortal: `${APP_URL}/portal/login`,
  /** New-firm signup / free trial. */
  signup: `${APP_URL}/signup`,
};

/** Primary navigation shown in the site header.
 *
 *  ⚠️ "OUR STORY" IS THE HOMEPAGE — THE WHOLE OF IT, FROM THE TOP — AND THIS
 *  HAS NOW MOVED THREE TIMES. It was `/#story`, an anchor onto a homepage
 *  panel; on 16-09-2026 it became a page of its own, on the note "our story is
 *  a big page if you see i guess we have to split it"; on 18-09-2026 that page
 *  was deleted, because it had been made by COPYING the homepage panel and the
 *  copy was never re-written, so both carried the same heading and the same
 *  callout — *"our story must contain the homepage only not the existing our
 *  story page delete that page."*
 *
 *  It pointed at `/#story` for a few hours after that, which put the reader a
 *  screen and a half down the page, and the owner said what they actually
 *  wanted: *"when we click the our story it its starting from below the
 *  heropage it should gp tp the hero right directly?"* So it is `/` — the top
 *  of the homepage, hero first.
 *
 *  THE LOGO GOES TO THE SAME PLACE, and that is accepted rather than
 *  overlooked: two doors onto one destination is the consequence of Our Story
 *  BEING the homepage. `id="story"` stays on the panel because `/#story` is a
 *  link people already hold, and `/story` is a 301 in `public/_redirects`,
 *  but nothing on the site points at either any more. */
export const NAV = [
  { label: "Our Story", href: "/" },
  { label: "Products", href: "/products" },
  { label: "Pricing", href: "/pricing" },
  { label: "Support", href: "/support" },
  { label: "Resources", href: "/resources" },
];

export const CONTACT = {
  email: "hello@practicesync.com",
  phone: "+91 80 4718 2200",
};
