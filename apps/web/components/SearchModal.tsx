"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { Search, Users, UserPlus, CheckSquare, FileText, Shield, ShieldCheck, X, Compass } from "lucide-react";
import { api } from "@/lib/api";
import { useRouter, usePathname } from "next/navigation";
import { matchScreens, screenHref, isScreensOnly, SCREENS_ONLY_PREFIX } from "@/lib/navigation/screens";
import { Skeleton } from "@/components/ui/skeleton";

type SearchResult = {
  id: string;
  category:
    | "screens"
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
  screens: Compass,
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
  screens: "Go to",
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
  const pathname = usePathname() ?? "";
  // The open client, read off the URL — the same segment
  // `lib/workspace/clientPath` reads, so the palette and the switcher cannot
  // disagree about which client is open.
  const clientId =
    pathname.match(
      /^\/clients\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(\/|$)/i,
    )?.[1] ?? null;

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
    try {
      const { results: res, error } = await runSearch(q);
      setResults(res);
      setSearchError(error);
      setSelectedIndex(0);
    } catch (e) {
      setResults([]);
      setSearchError(e instanceof Error ? e.message : "The search could not be run.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // A screens-only query never reaches /api/search: `>` is not a term, and
    // sending it would run a round trip whose answer is thrown away.
    if (isScreensOnly(query)) { setResults([]); setSearchError(null); return; }
    const t = setTimeout(() => search(query), 300);
    return () => clearTimeout(t);
  }, [query, search]);

  // Screens match in the bundle, so they render on the FIRST keystroke while
  // the entity search is still debounced. That difference in COST is the whole
  // reason both can be shown at once instead of one hiding behind a prefix.
  const screenResults: SearchResult[] = useMemo(
    () =>
      matchScreens(query, clientId).map((sc) => {
        const href = screenHref(sc, clientId);
        return {
          id: `screen:${sc.scope}:${sc.href}`,
          category: "screens" as const,
          title: sc.name,
          subtitle: sc.scope === "client" ? `${sc.section} · this client` : sc.section,
          href: href ?? "",
        };
      })
      // `matchScreens` already withholds client screens when no client is
      // open, so this cannot fire today. It is here because the alternative
      // failure is a row that LOOKS like a destination and pushes "" — and a
      // guard that depends on two functions agreeing is one edit from not
      // holding.
      .filter((r) => r.href !== ""),
    [query, clientId],
  );

  // The highlighted row must exist. Screens re-match on every keystroke while
  // `setSelectedIndex(0)` only runs after the debounce, so a list that SHRINKS
  // under an arrowed-down selection would leave the index past the end —
  // nothing highlighted, and Enter falling through to the full-search page
  // instead of the row the CA is looking at.
  useEffect(() => {
    setSelectedIndex((i) => (i >= screenResults.length + results.length ? 0 : i));
  }, [screenResults.length, results.length]);

  // `>` restricts to screens. Entity results are dropped rather than not
  // fetched, because the fetch is already in flight by the time the caret
  // reaches the second character.
  const allResults = isScreensOnly(query) ? screenResults : [...screenResults, ...results];

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
      className="fixed inset-0 z-50 flex items-start justify-center pt-20 bg-ps-bg/75 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-[0_24px_60px_rgba(0,0,0,0.6),0_0_0_1px_rgba(255,255,255,0.03)] border border-ps-border w-full max-w-2xl mx-4 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-ps-border">
          <Search size={18} className="text-ps-hint shrink-0" />
          <input
            ref={inputRef}
            type="text"
            className="flex-1 text-base outline-none text-ps-ink placeholder:text-ps-hint bg-transparent"
            placeholder={`Go to a screen, or find a client, task or journal… (${SCREENS_ONLY_PREFIX} for screens only)`}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-ps-muted transition-colors"
          >
            <X size={15} className="text-ps-hint" />
          </button>
        </div>

        {/* Results */}
        <div className="max-h-96 overflow-y-auto">
          {loading && (
            <div className="py-2" role="status" aria-label="Loading results">
              {[1, 2, 3].map(i => (
                <div key={i} className="px-4 py-2.5 space-y-1.5">
                  <Skeleton className="h-3.5 w-40" />
                  <Skeleton className="h-2.5 w-24" />
                </div>
              ))}
            </div>
          )}

          {!loading && query && searchError && (
            <div className="py-12 text-center">
              <p className="text-sm text-red-600 font-medium">{searchError}</p>
              <button
                onClick={() => search(query)}
                className="mt-2 text-xs px-3 py-1 border border-ps-border rounded hover:bg-ps-bg text-ps-body"
              >
                Retry
              </button>
            </div>
          )}

          {!loading && query && !searchError && allResults.length === 0 && (
            <div className="py-12 text-center text-ps-hint">
              <p className="text-sm">No results for &quot;{query}&quot;</p>
            </div>
          )}

          {!loading && !query && (
            <div className="py-12 text-center text-ps-hint">
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
                      <span className="text-3xs font-semibold uppercase tracking-widest text-ps-hint flex items-center gap-1">
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
                          <p className="text-sm font-medium text-ps-ink">{item.title}</p>
                          <p className="text-xs text-ps-hint">{item.subtitle}</p>
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
        <div className="border-t border-ps-border px-4 py-2 flex items-center gap-4 text-xs text-ps-hint">
          <span><kbd className="font-mono">↑↓</kbd> navigate</span>
          <span><kbd className="font-mono">Enter</kbd> select</span>
          <span><kbd className="font-mono">Esc</kbd> close</span>
          <span className="ml-auto"><kbd className="font-mono">⌘K</kbd> to open</span>
        </div>
      </div>
    </div>
  );
}
