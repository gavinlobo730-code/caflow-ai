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
 *  Every entry is a PAGE. "Our Story" pointed at `/#story` until 16-09-2026 —
 *  an anchor onto a homepage panel — so the one nav item promising to explain
 *  the company scrolled you a screen and a half down the page you were already
 *  on. A fragment in the primary nav is also invisible to a reader who arrives
 *  from anywhere else, since the browser restores it without a page change. */
export const NAV = [
  { label: "Our Story", href: "/story" },
  { label: "Products", href: "/products" },
  { label: "Pricing", href: "/pricing" },
  { label: "Support", href: "/support" },
  { label: "Resources", href: "/resources" },
];

export const CONTACT = {
  email: "hello@practicesync.com",
  phone: "+91 80 4718 2200",
};
