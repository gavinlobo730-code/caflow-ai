"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useScreenAccess } from "@/lib/access/useScreenAccess";
import { SETTINGS_GROUPS, groupHasContent, linkShownTo, settingsTabHref } from "@/lib/settings/groups";
import { cn, isExactPath } from "@/lib/utils";

/**
 * ⚠️ THIS PANEL LISTED FIVE OF SETTINGS' THIRTEEN SCREENS AND
 * `app/settings/page.tsx` LINKED EIGHT OTHERS — DISJOINT SETS, so which half
 * of their own settings a CA could reach depended on which surface they
 * navigated by. From `/settings/branding` there was no way to
 * `/settings/invoice-templates`, which is the very next thing somebody
 * customising their documents wants; the eight included Statutory Values (the
 * PT slabs) and DTAA Treaty Rates, both of which change what the product
 * WITHHOLDS.
 *
 * The rule is in `components/panels/AccountingPanel.tsx`'s header and held by
 * `scripts/a-module-shows-all-of-itself.test.ts`: the panel is the surface
 * present on every page of the module, so the panel lists the whole module.
 * The landing page keeps its own richer sections — it explains each of these,
 * which a 220px rail cannot.
 *
 * NO `requires` HERE, and that is measured rather than assumed: every one of
 * these pages reads its own data over PostgREST or through an endpoint the
 * Settings screens already reach, so RLS and each page's own `RoleGuard`
 * govern them. WHAT IT DOES FILTER ON IS THAT GUARD (POST-A-447): it listed
 * every page to everyone, so a Manager, an Executive or a Reviewer was offered
 * ten pages whose guard sent them straight back to the home page. A link is now
 * shown only to the roles its page's guard admits (`roles` in the groups, held
 * equal to each page's guard by `lib/settings/groups.test.ts`).
 */
/**
 * THE GROUPS ARE `lib/settings/groups.ts` (PRE-A-023), the same list the tab row across every Settings page and
 * the Settings home read, so this panel cannot drift from them. Each heading is a tab of the Settings home, and
 * under it are the group's Settings screens; a link that leaves Settings (Team, which the Team panel owns) is not
 * repeated here.
 */
const PANEL_GROUPS = SETTINGS_GROUPS.map((g) => ({
  group: g,
  id: g.id,
  heading: g.label,
  tabHref: settingsTabHref(g.id),
  items: g.links
    .map((l) => ({ href: l.href.split("#")[0], label: l.label, link: l }))
    .filter((l, i, all) => l.href.startsWith("/settings") && all.findIndex((o) => o.href === l.href) === i),
}));

export function SettingsPanel() {
  const pathname = usePathname();
  const access = useScreenAccess();
  const groups = PANEL_GROUPS
    .filter(({ group }) => groupHasContent(group, access))
    .map((g) => ({ ...g, items: g.items.filter(({ link }) => linkShownTo(link, access)) }));

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-4 pb-3 border-b border-ps-border shrink-0">
        <p className="text-2xs font-semibold text-ps-hint uppercase tracking-wider">
          Settings
        </p>
      </div>
      <nav className="flex-1 overflow-y-auto px-2 py-2">
        {groups.map(({ id, heading, tabHref, items }) => (
          <div key={id} className="mt-3 first:mt-0">
            <Link
              href={tabHref}
              className="block px-3 pb-1 text-3xs font-semibold uppercase tracking-wider text-ps-hint hover:text-ps-ink"
            >
              {heading}
            </Link>
            <div className="flex flex-col gap-0.5">
              {items.map(({ href, label }) => {
                const isActive = isExactPath(pathname, href) || (href !== "/settings" && pathname.startsWith(href));
                return (
                  <Link
                    key={href}
                    href={href}
                    className={cn(
                      "flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors",
                      isActive
                        ? "bg-brand text-white font-medium"
                        : "text-ps-label hover:bg-ps-bg"
                    )}
                  >
                    {label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
    </div>
  );
}
