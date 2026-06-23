"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  FileText,
  Edit3,
  Send,
  CheckCircle,
  LayoutTemplate,
} from "lucide-react";
import { cn } from "@/lib/utils";

const ENGAGEMENTS_ITEMS = [
  { href: "/engagements", label: "All Engagements", icon: FileText },
  { href: "/engagements?tab=draft", label: "Drafts", icon: Edit3 },
  { href: "/engagements?tab=sent", label: "Awaiting Signature", icon: Send },
  { href: "/engagements?tab=signed", label: "Signed", icon: CheckCircle },
  { href: "/engagements?tab=templates", label: "Templates", icon: LayoutTemplate },
];

export function EngagementsPanel() {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 shrink-0">
        <p className="text-[13px] font-semibold text-[#182350]">Engagements</p>
        <p className="text-[11px] text-gray-500 mt-0.5">
          Engagement Letters & Agreements
        </p>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-400 px-2 mb-1.5 mt-1">
          Navigate
        </p>
        <div className="space-y-0.5">
          {ENGAGEMENTS_ITEMS.map(({ href, label, icon: Icon }) => {
            const isEngagementsRoot = href === "/engagements";
            const active = isEngagementsRoot
              ? pathname === "/engagements"
              : pathname.startsWith("/engagements");
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] text-[12.5px] font-medium transition-all duration-75",
                  active
                    ? "bg-[#182350] text-white"
                    : "text-gray-600 hover:bg-[#F8FAFC] hover:text-[#182350]"
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

        <div className="mt-4 mx-2 p-2.5 rounded-[7px] bg-[#F8FAFC] border border-gray-200">
          <p className="text-[11px] text-gray-500 leading-relaxed">
            Create and manage{" "}
            <Link href="/engagements" className="text-blue-600 hover:underline">
              engagement letters
            </Link>{" "}
            for clients and prospects.
          </p>
        </div>
      </nav>
    </div>
  );
}
