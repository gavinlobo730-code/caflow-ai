"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Building2, ShieldCheck, ClipboardList, Calendar, Shield } from "lucide-react";
import { cn } from "@/lib/utils";

const SETTINGS_NAV = [
  { href: "/settings", label: "Firm Profile", icon: Building2, exact: true },
  { href: "/settings/security", label: "Security / 2FA", icon: ShieldCheck },
  { href: "/settings/audit-log", label: "Audit Log", icon: ClipboardList },
  { href: "/settings/scheduled-reports", label: "Scheduled Reports", icon: Calendar },
  { href: "/settings/dsc-tracker", label: "DSC Tracker", icon: Shield },
];

export function SettingsPanel() {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-4 pb-3 border-b border-gray-100 shrink-0">
        <p className="text-[11px] font-semibold text-[#94A3B8] uppercase tracking-wider">
          Settings
        </p>
      </div>
      <nav className="px-2 py-2 flex flex-col gap-0.5">
        {SETTINGS_NAV.map(({ href, label, icon: Icon, exact }) => {
          const isActive = exact ? pathname === href : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] transition-colors",
                isActive
                  ? "bg-blue-50 text-blue-700 font-medium"
                  : "text-[#475569] hover:bg-[#F8FAFC]"
              )}
            >
              <Icon
                size={14}
                className={isActive ? "text-blue-600" : "text-[#94A3B8]"}
              />
              {label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
