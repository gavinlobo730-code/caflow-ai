"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Users,
  KanbanSquare,
  ExternalLink,
  FolderOpen,
  Search,
} from "lucide-react";
import { cn } from "@/lib/utils";

const CLIENTS_ITEMS = [
  { href: "/clients", label: "All Clients", icon: Users },
  { href: "/pipeline", label: "Pipeline", icon: KanbanSquare },
  { href: "/client-portal", label: "Client Portal", icon: ExternalLink },
  { href: "/documents", label: "Documents", icon: FolderOpen },
];

interface ClientsPanelProps {
  onOpenSearch: () => void;
}

export function ClientsPanel({ onOpenSearch }: ClientsPanelProps) {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-white/[0.06] shrink-0">
        <p className="text-[13px] font-semibold text-white/85">Clients</p>
        <p className="text-[11px] text-white/30 mt-0.5">Client management</p>
      </div>

      {/* Search shortcut */}
      <div className="px-2 py-2 border-b border-white/[0.06] shrink-0">
        <button
          onClick={onOpenSearch}
          className="flex items-center gap-2 w-full px-2.5 py-1.5 rounded-[7px] bg-[#0F172A]/[0.04] border border-white/[0.06] text-[12px] text-white/30 hover:text-white/50 hover:bg-[#0F172A]/[0.06] transition-all duration-75"
        >
          <Search size={12} className="shrink-0" />
          <span className="flex-1 text-left">Search clients...</span>
          <kbd className="text-[10px] text-white/20 font-mono">⌘K</kbd>
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-white/30 px-2 mb-1.5 mt-1">
          Navigate
        </p>
        <div className="space-y-0.5">
          {CLIENTS_ITEMS.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/clients"
                ? pathname === "/clients" || pathname.startsWith("/clients/")
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

        <div className="mt-4 mx-2 p-2.5 rounded-[7px] bg-[#0F172A]/[0.03] border border-white/[0.06]">
          <p className="text-[11px] text-white/30 leading-relaxed">
            Select a client from{" "}
            <Link href="/clients" className="text-blue-400 hover:underline">
              All Clients
            </Link>{" "}
            to view their GST, TDS, Income Tax and more.
          </p>
        </div>
      </nav>
    </div>
  );
}
