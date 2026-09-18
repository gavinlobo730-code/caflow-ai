// Central config for the marketing site: where the actual app lives, and the
// cross-app links the marketing pages point at. The app is a separate origin
// (apps/web — dashboard-labeled "practicesync-ai", but its *.pages.dev
// subdomain is caflow-ai.pages.dev, fixed at project creation), so every
// "log in / sign up" action is a plain link to that origin — the marketing
// site holds no auth logic itself.

export const APP_URL =
  process.env.NEXT_PUBLIC_APP_URL || "https://caflow-ai.pages.dev";

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
