"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Search, Users, UserPlus, CheckSquare, FileText, Shield, ShieldCheck, X } from "lucide-react";
import { api } from "@/lib/api";
import { useRouter } from "next/navigation";

type SearchResult = {
  id: string;
  category:
    | "clients"
    | "tasks"
    | "compliance"
    | "journals"
    | "accounts"
    | "leads"
    | "engagements"
    | "documents"
    | "dsc";
  title: string;
  subtitle: string;
  href: string;
};

const CATEGORY_ICONS = {
  clients: Users,
  tasks: CheckSquare,
  compliance: Shield,
  journals: FileText,
  accounts: FileText,
  leads: UserPlus,
  engagements: FileText,
  documents: FileText,
  dsc: ShieldCheck,
};

const CATEGORY_LABELS = {
  clients: "Clients",
  tasks: "Tasks",
  compliance: "Compliance",
  journals: "Journal Entries",
  accounts: "Accounts",
  leads: "Leads",
  engagements: "Engagements",
  documents: "Documents",
  dsc: "DSC",
};

// M2: search now goes through the backend /api/search, which enforces client
// assignment server-side. The browser no longer queries Supabase directly, so a
// user can only discover entities for clients they are authorized to access.
async function runSearch(query: string): Promise<{ results: SearchResult[]; error: string | null }> {
  if (!query.trim() || query.length < 2) return { results: [], error: null };
  try {
    const res = await api.search(query.trim());
    if (!res.success) return { results: [], error: res.error ?? "Search failed." };
    return {
      results: (res.data?.results ?? []).map((r) => ({
        id: r.id,
        category: (r.category as SearchResult["category"]) ?? "clients",
        title: r.title,
        subtitle: r.subtitle ?? "",
        href: r.href,
      })),
      error: null,
    };
  } catch (e) {
    // Distinguishes "search failed" from "no results" — a masked failure
    // previously rendered identically to a genuine zero-match search.
    return { results: [], error: e instanceof Error ? e.message : "Search failed." };
  }
}

export function SearchModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  // Distinguishes "search failed" from "no results found".
  const [searchError, setSearchError] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (open) {
      setQuery("");
      setResults([]);
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // Escape to close — open is controlled by parent via onOpenSearch
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && open) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const search = useCallback(async (q: string) => {
    if (!q.trim()) { setResults([]); setSearchError(null); return; }
    setLoading(true);
    const { results: res, error } = await runSearch(q);
    setResults(res);
    setSearchError(error);
    setSelectedIndex(0);
    setLoading(false);
  }, []);

  useEffect(() => {
    const t = setTimeout(() => search(query), 300);
    return () => clearTimeout(t);
  }, [query, search]);

  const allResults = results;

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex(i => Math.min(i + 1, allResults.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex(i => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      if (allResults[selectedIndex]) {
        router.push(allResults[selectedIndex].href);
        onClose();
      } else {
        router.push(`/search?q=${encodeURIComponent(query)}`);
        onClose();
      }
    }
  }

  if (!open) return null;

  const grouped = allResults.reduce<Record<string, SearchResult[]>>((acc, r) => {
    if (!acc[r.category]) acc[r.category] = [];
    acc[r.category].push(r);
    return acc;
  }, {});

  let flatIndex = 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-20 bg-[#F8FAFC]/75 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-[0_24px_60px_rgba(0,0,0,0.6),0_0_0_1px_rgba(255,255,255,0.03)] border border-[#E2E8F0] w-full max-w-2xl mx-4 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[#E2E8F0]">
          <Search size={18} className="text-[#94A3B8] shrink-0" />
          <input
            ref={inputRef}
            type="text"
            className="flex-1 text-base outline-none text-[#1E293B] placeholder:text-[#94A3B8] bg-transparent"
            placeholder="Search clients, tasks, filings, journals..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-[#F1F5F9] transition-colors"
          >
            <X size={15} className="text-[#94A3B8]" />
          </button>
        </div>

        {/* Results */}
        <div className="max-h-96 overflow-y-auto">
          {loading && (
            <div className="p-4 space-y-2">
              {[1, 2, 3].map(i => (
                <div key={i} className="h-12 bg-[#F1F5F9] rounded-lg animate-pulse" />
              ))}
            </div>
          )}

          {!loading && query && searchError && (
            <div className="py-12 text-center">
              <p className="text-sm text-red-600 font-medium">{searchError}</p>
              <button
                onClick={() => search(query)}
                className="mt-2 text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]"
              >
                Retry
              </button>
            </div>
          )}

          {!loading && query && !searchError && allResults.length === 0 && (
            <div className="py-12 text-center text-[#94A3B8]">
              <p className="text-sm">No results for &quot;{query}&quot;</p>
            </div>
          )}

          {!loading && !query && (
            <div className="py-12 text-center text-[#94A3B8]">
              <p className="text-sm">Search clients, tasks, filings, journals...</p>
            </div>
          )}

          {!loading && allResults.length > 0 && (
            <div className="py-2">
              {Object.entries(grouped).map(([cat, items]) => {
                const Icon = CATEGORY_ICONS[cat as keyof typeof CATEGORY_ICONS] ?? FileText;
                return (
                  <div key={cat}>
                    <div className="px-4 py-1.5">
                      <span className="text-[10px] font-semibold uppercase tracking-widest text-[#94A3B8] flex items-center gap-1">
                        <Icon size={10} />
                        {CATEGORY_LABELS[cat as keyof typeof CATEGORY_LABELS]}
                      </span>
                    </div>
                    {items.map(item => {
                      const idx = flatIndex++;
                      return (
                        <button
                          key={item.id}
                          className={`w-full text-left px-4 py-2.5 transition-colors ${
                            idx === selectedIndex
                              ? "bg-[#DBEAFE]"
                              : "hover:bg-[#DBEAFE]"
                          }`}
                          onClick={() => { router.push(item.href); onClose(); }}
                        >
                          <p className="text-sm font-medium text-[#1E293B]">{item.title}</p>
                          <p className="text-xs text-[#94A3B8]">{item.subtitle}</p>
                        </button>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-[#E2E8F0] px-4 py-2 flex items-center gap-4 text-xs text-[#94A3B8]">
          <span><kbd className="font-mono">↑↓</kbd> navigate</span>
          <span><kbd className="font-mono">Enter</kbd> select</span>
          <span><kbd className="font-mono">Esc</kbd> close</span>
          <span className="ml-auto"><kbd className="font-mono">⌘K</kbd> to open</span>
        </div>
      </div>
    </div>
  );
}
