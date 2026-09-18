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
 *  ⚠️ "OUR STORY" IS THE HOMEPAGE'S OWN PANEL AND NOT A PAGE, WHICH REVERSES A
 *  DECISION TAKEN ON 16-09-2026. It pointed at `/#story` originally; that day it
 *  was given a page of its own, on the note that "our story is a big page if you
 *  see i guess we have to split it". The split was made by COPYING the homepage
 *  panel, the copy was never re-written, and for two days both pages carried the
 *  same section 02 heading and the same gold callout. The owner found it by
 *  clicking the logo and then this item and landing on the same panel twice, and
 *  settled it on 18-09-2026: *"at first the our story and the home were the same
 *  page right so our story must contain the homepage only not the existing our
 *  story page delete that page."*
 *
 *  So this is a FRAGMENT, deliberately, and the earlier objection to that is
 *  recorded rather than deleted: a fragment in the primary nav does nothing
 *  visible to a reader who is already on the homepage at that scroll position,
 *  and the browser restores it without a page change. That was the reason for
 *  the page; it is outranked by there being only one of this content. Anything
 *  still linking to `/story` is redirected in `public/_redirects`. */
export const NAV = [
  { label: "Our Story", href: "/#story" },
  { label: "Products", href: "/products" },
  { label: "Pricing", href: "/pricing" },
  { label: "Support", href: "/support" },
  { label: "Resources", href: "/resources" },
];

export const CONTACT = {
  email: "hello@practicesync.com",
  phone: "+91 80 4718 2200",
};
