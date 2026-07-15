// Central config for the marketing site: where the actual app lives, and the
// cross-app links the marketing pages point at. The app is a separate origin
// (apps/web on app.practicesync.com), so every "log in / sign up" action is a
// plain link to that origin — the marketing site holds no auth logic itself.

export const APP_URL =
  process.env.NEXT_PUBLIC_APP_URL || "https://app.practicesync.com";

/** Cross-app destinations (routes that live in apps/web). */
export const appLinks = {
  /** Chartered Accountant / firm staff sign-in (email + password + TOTP MFA). */
  firmLogin: `${APP_URL}/login`,
  /** Client portal sign-in (magic-link, token-gated). */
  clientPortal: `${APP_URL}/portal/dashboard`,
  /** New-firm signup / free trial. */
  signup: `${APP_URL}/signup`,
};

/** Primary navigation shown in the site header. */
export const NAV = [
  { label: "Why PracticeSync", href: "/#why" },
  { label: "Products", href: "/products" },
  { label: "Pricing", href: "/pricing" },
  { label: "Support", href: "/support" },
  { label: "Resources", href: "/resources" },
];

export const CONTACT = {
  email: "hello@practicesync.com",
  phone: "+91 80 4718 2200",
};
