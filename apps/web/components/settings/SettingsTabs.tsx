"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth/AuthContext";
import { cn } from "@/lib/utils";
import {
  SETTINGS_GROUPS,
  groupForPage,
  groupHasContent,
  settingsTabHref,
} from "@/lib/settings/groups";

/**
 * The row of Settings tabs across the top of every Settings page (PRE-A-023).
 *
 * Across the top, not a left-hand panel: the owner asked on 16-11-2026 for Settings to follow the platform's own
 * navigation, which is a bar across the top of the window. The groups are `lib/settings/groups.ts`; a tab opens
 * the Settings home on that group (`/settings?tab=…`), and on any other Settings page the group that lists the
 * page is lit, so a person on Branding can see it sits under Invoices and documents and go back to the rest of it.
 *
 * On a phone the row scrolls sideways rather than wrapping into a second block of buttons. A tab with nothing
 * the person may open (a group of Partner-only screens, to a Manager) is not shown.
 */
export function SettingsTabs() {
  const pathname = usePathname() ?? "/settings";
  const tab = useSearchParams()?.get("tab") ?? null;
  const { userRole } = useAuth();
  const active = groupForPage(pathname, tab);

  return (
    <nav aria-label="Settings sections" className="border-b border-ps-border bg-white print:hidden">
      <div className="mx-auto flex max-w-5xl gap-1 overflow-x-auto px-4 md:px-6">
        {SETTINGS_GROUPS.filter((g) => groupHasContent(g, userRole)).map((g) => {
          const on = g.id === active;
          return (
            <Link
              key={g.id}
              href={settingsTabHref(g.id)}
              aria-current={on ? "page" : undefined}
              className={cn(
                "-mb-px shrink-0 whitespace-nowrap border-b-2 px-3 py-3 text-sm font-medium transition-colors",
                on
                  ? "border-brand text-ps-ink"
                  : "border-transparent text-ps-label hover:border-ps-border hover:text-ps-ink",
              )}
            >
              {g.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
