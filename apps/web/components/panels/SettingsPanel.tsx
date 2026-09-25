"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Building2,
  ShieldCheck,
  ClipboardList,
  Calendar,
  Shield,
  Palette,
  Hash,
  FileText,
  Mail,
  Library,
  Coins,
  Scale,
  Globe2,
} from "lucide-react";
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
 * govern them. Branding is the one with a Partner-only section, and its guard
 * is ON THE PAGE where it can explain itself, which is better than a link
 * that silently is not there.
 */
const SETTINGS_GROUPS: Array<{
  heading: string | null;
  items: Array<{ href: string; label: string; icon: typeof Building2; exact?: boolean }>;
}> = [
  {
    heading: null,
    items: [{ href: "/settings", label: "Firm Profile", icon: Building2, exact: true }],
  },
  {
    heading: "Documents",
    items: [
      { href: "/settings/branding", label: "Branding", icon: Palette },
      { href: "/settings/invoice-settings", label: "Invoice Numbering", icon: Hash },
      { href: "/settings/invoice-templates", label: "Invoice Templates", icon: FileText },
      { href: "/settings/email-templates", label: "Email Templates", icon: Mail },
    ],
  },
  {
    heading: "Statutory",
    items: [
      { href: "/settings/statutory-values", label: "Statutory Values", icon: Scale },
      { href: "/settings/treaty-rates", label: "DTAA Treaty Rates", icon: Globe2 },
      { href: "/settings/firm-hsn-library", label: "HSN Library", icon: Library },
      { href: "/settings/multi-currency", label: "Multi-currency", icon: Coins },
      { href: "/settings/dsc-tracker", label: "DSC Tracker", icon: Shield },
    ],
  },
  {
    heading: "Firm",
    items: [
      { href: "/settings/security", label: "Security / 2FA", icon: ShieldCheck },
      { href: "/settings/audit-log", label: "Audit Log", icon: ClipboardList },
      { href: "/settings/scheduled-reports", label: "Scheduled Reports", icon: Calendar },
    ],
  },
];

export function SettingsPanel() {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-4 pb-3 border-b border-ps-border shrink-0">
        <p className="text-2xs font-semibold text-ps-hint uppercase tracking-wider">
          Settings
        </p>
      </div>
      <nav className="flex-1 overflow-y-auto px-2 py-2">
        {SETTINGS_GROUPS.map(({ heading, items }) => (
          <div key={heading ?? "_"} className={heading ? "mt-3 first:mt-0" : ""}>
            {heading && (
              <p className="px-3 pb-1 text-3xs font-semibold uppercase tracking-wider text-ps-hint">
                {heading}
              </p>
            )}
            <div className="flex flex-col gap-0.5">
              {items.map(({ href, label, icon: Icon, exact }) => {
                const isActive = exact
                  ? isExactPath(pathname, href)
                  : pathname.startsWith(href);
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
                    <Icon
                      size={14}
                      className={isActive ? "text-white" : "text-ps-hint"}
                    />
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
