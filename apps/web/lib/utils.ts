import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** True when `pathname` (from usePathname()) is exactly the route `href`
 * points to, tolerating the trailing slash this app's next.config.mjs
 * (`trailingSlash: true`) always appends to every real route — a bare
 * `pathname === href` can never match once Next.js appends it, so a sidebar
 * panel's "root/index" item never lit up as active. Use for an exact-match
 * nav item; a route with sub-pages should keep using
 * `pathname.startsWith(href + "/")`, unaffected by this since the extra
 * slash is already a valid prefix. */
export function isExactPath(pathname: string, href: string): boolean {
  return pathname === href || pathname === `${href}/`;
}
