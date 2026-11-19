"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Users,
  KanbanSquare,
  ExternalLink,
  FolderOpen,
  Search,
  ListChecks,
  Plus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { usePermissions } from "@/lib/auth/AuthContext";
import { ADD_CLIENT_HREF, ADD_CLIENT_LABEL } from "@/lib/clients/addClient";

const CLIENTS_ITEMS = [
  { href: "/clients", label: "All Clients", icon: Users },
  { href: "/pipeline", label: "Pipeline", icon: KanbanSquare },
  // THE CLIENT-ONBOARDING TRACKER (sweep-auth-and-public-05). It used to sit
  // at /onboarding/checklist, sharing a path prefix with the unrelated firm
  // SIGNUP wizard at /onboarding — which matched `AppShell`'s NO_SHELL entry
  // for that wizard and left it with no shell at all until both that entry
  // and the public-path one were made exact (see lib/auth/public-paths.ts).
  // It now lives under /clients, whose onboarding it tracks; the old URL is
  // a redirect stub kept for bookmarks (app/onboarding/checklist/page.tsx).
  { href: "/clients/onboarding", label: "Client Onboarding", icon: ListChecks },
  { href: "/client-portal", label: "Client Portal", icon: ExternalLink },
  // Two distinct document surfaces: /documents is the OCR/intelligence
  // pipeline; /clients/documents is expiry-tracked Storage-backed vault.
  { href: "/documents", label: "Documents", icon: FolderOpen },
  { href: "/clients/documents", label: "Document Vault", icon: FolderOpen },
];

interface ClientsPanelProps {
  onOpenSearch: () => void;
}

export function ClientsPanel({ onOpenSearch }: ClientsPanelProps) {
  const pathname = usePathname();
  // Offered to those the server lets add a client (a Manager or a Partner), by the permission map and not a role list here
  // (POST-A-488): a tester who looked here for a way to add a company found none.
  const { can } = usePermissions();
  const canAdd = can("client", "write");

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 shrink-0">
        <p className="text-sm font-semibold text-brand">Clients</p>
        <p className="text-2xs text-gray-500 mt-0.5">Client management</p>
      </div>

      {/* Search shortcut */}
      <div className="px-2 py-2 border-b border-gray-200 shrink-0">
        <button
          onClick={onOpenSearch}
          className="flex items-center gap-2 w-full px-2.5 py-1.5 rounded-[7px] bg-ps-bg border border-gray-200 text-xs text-gray-500 hover:text-brand hover:bg-gray-100 transition-all duration-75"
        >
          <Search size={12} className="shrink-0" />
          <span className="flex-1 text-left">Search clients...</span>
          <kbd className="text-3xs text-ps-disabled font-mono">⌘K</kbd>
        </button>
      </div>

      {canAdd && (
        <div className="px-2 pt-2 shrink-0">
          <Link
            href={ADD_CLIENT_HREF}
            className="flex items-center justify-center gap-2 w-full px-2.5 py-1.5 rounded-[7px] bg-brand text-xs font-medium text-white hover:bg-brand-dark transition-colors"
          >
            <Plus size={13} className="shrink-0" />
            <span>{ADD_CLIENT_LABEL}</span>
          </Link>
        </div>
      )}

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        <p className="text-3xs font-semibold uppercase tracking-[0.08em] text-ps-hint px-2 mb-1.5 mt-1">
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

        <div className="mt-4 mx-2 p-2.5 rounded-[7px] bg-ps-bg border border-gray-200">
          <p className="text-2xs text-gray-500 leading-relaxed">
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
