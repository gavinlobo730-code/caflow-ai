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
  const now = new Date();
  const dateStr = now.toLocaleDateString("en-IN", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-white/[0.06] shrink-0">
        <p className="text-[13px] font-semibold text-white/85">Home</p>
        <p className="text-[11px] text-white/30 mt-0.5">{dateStr}</p>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-white/30 px-2 mb-1.5 mt-1">
          Navigate
        </p>
        <div className="space-y-0.5">
          {HOME_ITEMS.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/"
                ? pathname === "/"
                : pathname === href || pathname.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] text-[12.5px] font-medium transition-all duration-75",
                  active
                    ? "bg-blue-500/15 text-white/85"
                    : "text-white/50 hover:text-white/75 hover:bg-[#0F172A]/[0.04]"
                )}
              >
                <Icon
                  size={15}
                  className={cn(
                    "shrink-0",
                    active ? "text-blue-400" : "text-white/30"
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
