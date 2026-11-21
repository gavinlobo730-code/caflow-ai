"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Calendar,
  CalendarDays,
  Bell,
  Lightbulb,
  MessageSquare,
  CheckSquare,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useScreenAccess } from "@/lib/access/useScreenAccess";

import { formatWeekdayDate, todayIstISO } from "@/lib/dates/format";
// Home is the launchpad, so two of these are the ROOT of another area, `/deadlines` and `/work`. That is deliberate (the two
// things due today are the deadline list and the work queue) and is recorded in `scripts/a-screen-has-one-home.test.ts`'s
// LISTED_TWICE. Each entry is offered by the one table the menu and the page gate ask (`lib/access/screenAccess.ts`,
// POST-A-543), so this panel cannot offer a screen whose own area the person does not hold.
const HOME_ITEMS = [
  { href: "/", label: "Morning Brief", icon: LayoutDashboard },
  { href: "/deadlines", label: "Deadlines", icon: Calendar },
  { href: "/calendar", label: "Calendar", icon: CalendarDays },
  { href: "/notifications", label: "Notifications", icon: Bell },
  { href: "/work", label: "Work Queue", icon: CheckSquare },
  { href: "/insights", label: "Insights", icon: Lightbulb },
  { href: "/notifications/whatsapp", label: "WhatsApp", icon: MessageSquare },
];

export function HomePanel() {
  const pathname = usePathname();
  const { offered } = useScreenAccess();
  const items = HOME_ITEMS.filter((i) => offered(i.href));
  const dateStr = formatWeekdayDate(todayIstISO());

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 shrink-0">
        <p className="text-sm font-semibold text-brand">Home</p>
        <p className="text-2xs text-gray-500 mt-0.5">{dateStr}</p>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        <p className="text-3xs font-semibold uppercase tracking-[0.08em] text-ps-hint px-2 mb-1.5 mt-1">
          Navigate
        </p>
        <div className="space-y-0.5">
          {items.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/"
                ? pathname === "/"
                : pathname === href || pathname.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] text-xs font-medium transition-all duration-75",
                  active
                    ? "bg-brand text-white"
                    : "text-gray-600 hover:bg-ps-bg hover:text-brand"
                )}
              >
                <Icon
                  size={15}
                  className={cn(
                    "shrink-0",
                    active ? "text-white" : "text-gray-500"
                  )}
                />
                <span className="truncate">{label}</span>
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
