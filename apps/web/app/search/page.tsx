"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Search, Users, CheckSquare, FileText, Shield } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import Link from "next/link";

type SearchResult = {
  id: string;
  category: "clients" | "tasks" | "compliance" | "journals" | "accounts";
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
};

const CATEGORY_LABELS = {
  clients: "Clients",
  tasks: "Tasks",
  compliance: "Compliance",
  journals: "Journal Entries",
  accounts: "Accounts",
};

// M2: search goes through the backend /api/search, which enforces client
// assignment server-side. Unauthorized clients are never returned.
async function runSearch(query: string): Promise<{ results: SearchResult[]; error: string | null }> {
  if (!query.trim()) return { results: [], error: null };
  try {
    const res = await api.search(query.trim());
    if (!res.success) {
      return { results: [], error: res.error ?? "Search failed." };
    }
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
    return { results: [], error: e instanceof Error ? e.message : "Search failed. Please try again." };
  }
}

function SearchContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  // Distinguishes "search failed" from "no results found".
  const [searchError, setSearchError] = useState<string | null>(null);

  const search = useCallback(async (q: string) => {
    if (!q.trim()) { setResults([]); setSearchError(null); return; }
    setLoading(true);
    try {
      const { results: res, error } = await runSearch(q);
      setResults(res);
      setSearchError(error);
    } catch (e) {
      setResults([]);
      setSearchError(e instanceof Error ? e.message : "The search could not be run.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const q = searchParams.get("q") ?? "";
    setQuery(q);
    if (q) search(q);
  }, [searchParams, search]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    router.push(`/search?q=${encodeURIComponent(query)}`);
    search(query);
  }

  const grouped = results.reduce<Record<string, SearchResult[]>>((acc, r) => {
    if (!acc[r.category]) acc[r.category] = [];
    acc[r.category].push(r);
    return acc;
  }, {});

  return (
    <div className="min-h-screen bg-[#F8FAFC] p-8">
      <div className="max-w-3xl mx-auto">
        <h1 className="text-2xl font-bold text-[#0F172A] mb-6">Search</h1>
        <form onSubmit={handleSubmit} className="mb-8">
          <div className="relative">
            <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            <input
              autoFocus
              type="text"
              className="w-full pl-11 pr-4 py-3 border rounded-xl text-base bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              placeholder="Search clients, tasks, filings, journals..."
              value={query}
              onChange={e => setQuery(e.target.value)}
            />
          </div>
        </form>

        {loading && (
          <div className="space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="bg-white border rounded-lg px-4 py-3 space-y-1.5">
                <Skeleton className="h-3 w-2/3" />
                <Skeleton className="h-2.5 w-1/3" />
              </div>
            ))}
          </div>
        )}

        {!loading && query && searchError && (
          <Card>
            <CardContent className="py-12 text-center">
              <Search size={32} className="mx-auto mb-3 text-red-300" />
              <p className="text-sm text-red-600 font-medium">{searchError}</p>
              <button
                onClick={() => search(query)}
                className="mt-3 text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]"
              >
                Retry
              </button>
            </CardContent>
          </Card>
        )}

        {!loading && query && !searchError && results.length === 0 && (
          <Card>
            <CardContent className="py-12 text-center text-[#94A3B8]">
              <Search size={32} className="mx-auto mb-3 opacity-30" />
              <p>No results for &quot;{query}&quot;</p>
            </CardContent>
          </Card>
        )}

        {!loading && !query && (
          <p className="text-[#94A3B8] text-center mt-12">Search clients, tasks, filings, journals...</p>
        )}

        {Object.entries(grouped).map(([cat, items]) => {
          const Icon = CATEGORY_ICONS[cat as keyof typeof CATEGORY_ICONS] ?? FileText;
          return (
            <div key={cat} className="mb-6">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-[#64748B] mb-2 flex items-center gap-1.5">
                <Icon size={12} />{CATEGORY_LABELS[cat as keyof typeof CATEGORY_LABELS]}
              </h2>
              <div className="space-y-1.5">
                {items.map(item => (
                  <Link key={item.id} href={item.href}>
                    <div className="bg-white border rounded-lg px-4 py-3 hover:bg-blue-500/[0.08] hover:border-blue-500/20 transition-colors cursor-pointer">
                      <p className="font-medium text-[#0F172A] text-sm">{item.title}</p>
                      <p className="text-xs text-[#64748B] mt-0.5">{item.subtitle}</p>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center"><p className="text-[#64748B]">Loading...</p></div>}>
      <SearchContent />
    </Suspense>
  );
}
