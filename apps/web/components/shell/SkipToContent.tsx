/**
 * "Skip to content" — the first thing a keyboard user can reach, and invisible
 * to everyone else until they do.
 *
 * WHY IT EXISTS. Both shells put a top bar ahead of the page: the firm's
 * mega-menu and the client workspace's module bar are each a dozen or more tab
 * stops, and they come first on EVERY screen. Without this, a keyboard or
 * switch user tabs through all of them on every page load before reaching the
 * page they asked for (WCAG 2.4.1, Bypass Blocks). There was no such link
 * anywhere in the product.
 *
 * WHERE IT RENDERS. `AppShell`, inside the branch that draws a shell, and
 * nowhere else. The sign-in, sign-up, portal and onboarding screens return
 * bare children and have no navigation to skip, so a link there would point at
 * a landmark that is not on the page.
 *
 * THE TARGET IS `MAIN_CONTENT_ID`, AND BOTH SHELLS' `<main>` CARRY IT. It is one
 * constant, imported by the link and by each shell, so the two cannot drift
 * into a link to nothing. The landmark also takes `tabIndex={-1}`: a fragment
 * jump scrolls to a non-focusable element but does not move focus, and the
 * whole point is that the NEXT Tab lands inside the page. It is given
 * `outline-none` for the reason a dialog container is — it receives focus
 * programmatically and is not a control, and a ring around the entire page
 * body would say nothing useful.
 *
 * It is `sr-only` until focused and then `fixed` to the viewport corner, above
 * the shell's `h-screen overflow-hidden` frame, so it is neither clipped by it
 * nor pushes anything down.
 */
export const MAIN_CONTENT_ID = "main-content";

export function SkipToContent() {
  return (
    <a
      href={`#${MAIN_CONTENT_ID}`}
      className="sr-only print:hidden focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-ps-ink focus:shadow-lg focus:ring-2 focus:ring-brand"
    >
      Skip to content
    </a>
  );
}
