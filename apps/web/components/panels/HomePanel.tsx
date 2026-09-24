"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Calendar,
  CalendarDays,
  Bell,
  MessageSquare,
  CheckSquare,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth/AuthContext";
import { canAccessHref } from "@/lib/auth/permissions";

// Home is the launchpad, so two of these are the ROOT of another workspace —
// `/deadlines` and `/work`, each with its own rail tile. That is deliberate
// (the two things due today are the deadline list and the work queue) and is
// recorded in `scripts/a-screen-has-one-home.test.ts`'s LISTED_TWICE.
//
// ⚠️ WHICH MEANS THEY NEED THE SAME ROLE GATE THE RAIL APPLIES, and did not
// have it. `/deadlines` is in `STAFF_HIDDEN_HREFS` and the `deadlines` and
// `work` WORKSPACES are both in `STAFF_HIDDEN_WORKSPACES`, so the rail hides
// them from an Executive, a Reviewer and a Client — while this panel, which
// had no role filter at all, offered both to everyone. A hidden workspace
// reachable from the panel of another one is the hiding not working.
const HOME_ITEMS = [
  { href: "/", label: "Morning Brief", icon: LayoutDashboard },
  { href: "/deadlines", label: "Deadlines", icon: Calendar },
  { href: "/calendar", label: "Calendar", icon: CalendarDays },
  { href: "/notifications", label: "Notifications", icon: Bell },
  { href: "/work", label: "Work Queue", icon: CheckSquare },
  { href: "/notifications/whatsapp", label: "WhatsApp", icon: MessageSquare },
];

export function HomePanel() {
  const pathname = usePathname();
  const { userRole } = useAuth();
  const items = HOME_ITEMS.filter((i) => canAccessHref(i.href, userRole));
  const now = new Date();
  const dateStr = now.toLocaleDateString("en-IN", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 shrink-0">
        <p className="text-sm font-semibold text-brand">Home</p>
        <p className="text-2xs text-gray-500 mt-0.5">{dateStr}</p>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        <p className="text-3xs font-semibold uppercase tracking-[0.08em] text-gray-400 px-2 mb-1.5 mt-1">
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
