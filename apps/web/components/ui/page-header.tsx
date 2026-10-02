import * as React from "react";
import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * THE TITLE OF A SCREEN, AND WHERE ITS PRIMARY ACTION SITS (frontend_ux-13).
 *
 * There was no such component. 125 `<h1>` in 119 files carried 28 different
 * class strings — `text-xl font-semibold text-ps-ink` on 55 of them, then
 * `text-lg` in brand navy, `text-2xl font-bold`, `text-base` and the rest — so
 * a CA moving between Payroll, GST and Practice saw the screen's name change
 * size, weight and colour, and the screen's main button change corner. The
 * "back" affordance was five different things (an icon-only chevron that no
 * reader could name, a labelled link above the title, a breadcrumb, an
 * outlined button, a text arrow) and the primary action sat beside the title,
 * under it or inside a band of its own.
 *
 * ONE TITLE STYLE. No size prop and no tone: a screen has a name and the name
 * is the same size and colour everywhere, however important the page feels. A
 * screen that wants a different heading is a screen that is not using this, and
 * says why in the frozen list that guards it.
 *
 * WHERE THINGS GO
 *   back / breadcrumbs  above the title, as a LABELLED link (an icon alone has no
 *                       accessible name). `breadcrumbs` wins where both are given.
 *   icon, title, meta   one row: `meta` is what belongs beside the name — a count,
 *                       a status pill — never a second heading.
 *   subtitle            under it, one line of what the screen is for.
 *   children            under the subtitle, inside the title block: a sub-navigation
 *                       row, a notice that belongs to the heading.
 *   actions             top right, level with the title, and wrapping BELOW it on a
 *                       narrow screen instead of squeezing the name. The primary
 *                       action goes first.
 *
 * WHAT IT DOES NOT DO: it loads nothing, decides nothing and carries no data. It
 * is the heading of a page whose body the page still owns, which is why migrating
 * a screen to it never touches that screen's loading, empty or error states.
 *
 * The PRINT-ONLY heading of a report, the card headings on the sign-in, sign-up,
 * engagement-signing and employee-activation screens (a different shell, with no
 * navigation around them) and an entity page still styled for a dark surface the
 * shell does not provide are not this component's job, and
 * `scripts/a-screen-names-itself-through-one-component.test.ts` names each with
 * its reason.
 */

export interface PageHeaderCrumb {
  label: string;
  /** Absent on the last crumb: the page you are on is not a link. */
  href?: string;
}

export interface PageHeaderProps {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  /** A small icon before the title. Decorative: it is hidden from assistive tech. */
  icon?: React.ReactNode;
  /** The screen one step up, as a labelled link: `{ href: "/settings", label: "Settings" }`. */
  back?: { href: string; label: string };
  breadcrumbs?: PageHeaderCrumb[];
  /** Beside the title on the same line: a count, a status pill. */
  meta?: React.ReactNode;
  /** The screen's actions, top right. The primary one first. */
  actions?: React.ReactNode;
  /** Under the subtitle, inside the title block (sub-navigation, a heading-level note). */
  children?: React.ReactNode;
  className?: string;
}

// The one `<h1>` class string in the product's screens. It is a constant rather
// than a literal at the element so that a census of literal `<h1 className="…">`
// in the tree counts the screens that still write their own.
const TITLE_CLASS = "text-xl font-semibold text-ps-ink";
const SUBTITLE_CLASS = "mt-0.5 max-w-3xl text-sm text-ps-label";

const BACK_CLASS =
  "mb-1 inline-flex items-center gap-1 text-xs text-ps-hint transition-colors hover:text-ps-label";

export function PageHeader({
  title,
  subtitle,
  icon,
  back,
  breadcrumbs,
  meta,
  actions,
  children,
  className,
}: PageHeaderProps) {
  const hasCrumbs = Array.isArray(breadcrumbs) && breadcrumbs.length > 0;
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-x-4 gap-y-3", className)}>
      <div className="min-w-0 flex-1 basis-64">
        {hasCrumbs ? (
          <nav aria-label="Breadcrumb" className="mb-1 flex flex-wrap items-center gap-1 text-xs text-ps-hint">
            {breadcrumbs.map((crumb, i) => (
              <React.Fragment key={`${i}-${crumb.label}`}>
                {i > 0 && <ChevronRight size={12} aria-hidden="true" />}
                {crumb.href ? (
                  <Link href={crumb.href} className="transition-colors hover:text-ps-label">
                    {crumb.label}
                  </Link>
                ) : (
                  <span aria-current="page">{crumb.label}</span>
                )}
              </React.Fragment>
            ))}
          </nav>
        ) : back ? (
          <Link href={back.href} className={BACK_CLASS}>
            <ChevronLeft size={13} aria-hidden="true" /> {back.label}
          </Link>
        ) : null}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          {icon && <span aria-hidden="true" className="inline-flex shrink-0 items-center">{icon}</span>}
          <h1 className={TITLE_CLASS}>{title}</h1>
          {meta}
        </div>
        {subtitle !== undefined && subtitle !== null && subtitle !== false && (
          // A string is a paragraph; anything richer may hold a block element, and a
          // block inside a <p> is invalid nesting.
          typeof subtitle === "string"
            ? <p className={SUBTITLE_CLASS}>{subtitle}</p>
            : <div className={SUBTITLE_CLASS}>{subtitle}</div>
        )}
        {children}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
