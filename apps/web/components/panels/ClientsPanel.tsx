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
      <div className="px-4 py-3 border-b border-gray-200 shrink-0">
        <p className="text-[13px] font-semibold text-[#182350]">Clients</p>
        <p className="text-[11px] text-gray-500 mt-0.5">Client management</p>
      </div>

      {/* Search shortcut */}
      <div className="px-2 py-2 border-b border-gray-200 shrink-0">
        <button
          onClick={onOpenSearch}
          className="flex items-center gap-2 w-full px-2.5 py-1.5 rounded-[7px] bg-[#F8FAFC] border border-gray-200 text-[12px] text-gray-500 hover:text-[#182350] hover:bg-gray-100 transition-all duration-75"
        >
          <Search size={12} className="shrink-0" />
          <span className="flex-1 text-left">Search clients...</span>
          <kbd className="text-[10px] text-[#CBD5E1] font-mono">⌘K</kbd>
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-400 px-2 mb-1.5 mt-1">
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
            Select a client from{" "}
            <Link href="/clients" className="text-blue-600 hover:underline">
              All Clients
            </Link>{" "}
            to view their GST, TDS, Income Tax and more.
          </p>
        </div>
      </nav>
    </div>
  );
}
