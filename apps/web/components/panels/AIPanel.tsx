"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Sparkles, ShieldAlert, BarChart3 } from "lucide-react";
import { cn } from "@/lib/utils";

const AI_ITEMS = [
  { href: "/ai-assistant", label: "AI Assistant", icon: Sparkles },
  { href: "/risks", label: "Risk Intelligence", icon: ShieldAlert },
  { href: "/reports", label: "Reports", icon: BarChart3 },
];

export function AIPanel() {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-white/[0.06] shrink-0">
        <p className="text-[13px] font-semibold text-white/90">AI</p>
        <p className="text-[11px] text-white/30 mt-0.5">
          Intelligence & reports
        </p>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-white/30 px-2 mb-1.5 mt-1">
          Tools
        </p>
        <div className="space-y-0.5">
          {AI_ITEMS.map(({ href, label, icon: Icon }) => {
            const active =
              pathname === href || pathname.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] text-[12.5px] font-medium transition-all duration-75",
                  active
                    ? "bg-indigo-500/15 text-white/90"
                    : "text-white/50 hover:text-white/80 hover:bg-white/[0.04]"
                )}
              >
                <Icon
                  size={15}
                  className={cn(
                    "shrink-0",
                    active ? "text-indigo-400" : "text-white/30"
                  )}
                />
                <span className="truncate">{label}</span>
              </Link>
            );
          })}
        </div>

        <div className="mt-4 mx-2 p-2.5 rounded-[7px] bg-violet-500/10 border border-violet-500/20">
          <p className="text-[11px] text-violet-300/70 leading-relaxed">
            Powered by{" "}
            <span className="text-violet-300 font-medium">
              Groq llama-3.3-70b
            </span>
          </p>
        </div>
      </nav>
    </div>
  );
}
