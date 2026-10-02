"use client";

import { useState, useEffect, useCallback, useRef, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Search, FileText } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import Link from "next/link";
import { PageHeader } from "@/components/ui/page-header";
// The palette's own client for /api/search — one request, one result shape,
// one set of category labels. This page used to carry a copy of each, and
// searched only on Enter while rendering "No results" off the text box: so a
// CA typing here saw "No results" for a term nobody had searched for.
import {
  runSearch,
  SEARCH_MIN_LENGTH,
  CATEGORY_ICONS,
  CATEGORY_LABELS,
  type SearchResult,
} from "@/components/SearchModal";

/** Same pause as the palette before a keystroke becomes a request. */
const DEBOUNCE_MS = 300;

function SearchContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  // Distinguishes "search failed" from "no results found".
  const [searchError, setSearchError] = useState<string | null>(null);
  // The term the results (or the error) on screen ANSWER. "No results" is
  // shown only when this equals what is typed — until then the answer for the
  // current term has not come back, and saying "none" would be a guess.
  const [searchedFor, setSearchedFor] = useState<string | null>(null);
  // Answers can arrive out of order; only the latest request's is kept.
  const latest = useRef(0);

  const search = useCallback(async (q: string) => {
    const term = q.trim();
    const seq = ++latest.current;
    if (term.length < SEARCH_MIN_LENGTH) {
      setResults([]);
      setSearchError(null);
      setSearchedFor(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const { results: res, error } = await runSearch(term);
      if (seq !== latest.current) return;
      setResults(res);
      setSearchError(error);
      setSearchedFor(term);
    } catch (e) {
      if (seq !== latest.current) return;
      setResults([]);
      setSearchError(e instanceof Error ? e.message : "The search could not be run.");
      setSearchedFor(term);
    } finally {
      if (seq === latest.current) setLoading(false);
    }
  }, []);

  // A link from the palette (Enter with no row selected) or a shared URL.
  useEffect(() => {
    setQuery(searchParams.get("q") ?? "");
  }, [searchParams]);

  // As the palette does: search as the CA types, after a pause.
  useEffect(() => {
    const t = setTimeout(() => search(query), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [query, search]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    // Keeps the URL shareable; the debounced search above does the fetching.
    router.replace(`/search?q=${encodeURIComponent(query)}`);
  }

  const term = query.trim();
  const tooShort = term.length > 0 && term.length < SEARCH_MIN_LENGTH;
  // Typed, but the answer for THIS term is not back yet (debounce or request).
  const pending = term.length >= SEARCH_MIN_LENGTH && (loading || searchedFor !== term);
  const answered = !pending && term.length >= SEARCH_MIN_LENGTH && searchedFor === term;

  const grouped = results.reduce<Record<string, SearchResult[]>>((acc, r) => {
    if (!acc[r.category]) acc[r.category] = [];
    acc[r.category].push(r);
    return acc;
  }, {});

  return (
    <div className="min-h-screen bg-ps-bg p-8">
      <div className="max-w-3xl mx-auto">
        <PageHeader title="Search" className="mb-6" />
        <form onSubmit={handleSubmit} className="mb-8">
          <div className="relative">
            <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-ps-hint" />
            <input
              autoFocus
              type="text"
              className="w-full pl-11 pr-4 py-3 border rounded-xl text-base bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
              placeholder="Search clients, tasks, filings, journals..."
              value={query}
              onChange={e => setQuery(e.target.value)}
            />
          </div>
        </form>

        {pending && (
          <div className="space-y-3" role="status" aria-label="Searching">
            {[1, 2, 3].map(i => (
              <div key={i} className="bg-white border rounded-lg px-4 py-3 space-y-1.5">
                <Skeleton className="h-3 w-2/3" />
                <Skeleton className="h-2.5 w-1/3" />
              </div>
            ))}
          </div>
        )}

        {answered && searchError && (
          <Card>
            <CardContent className="py-12 text-center">
              <Search size={32} className="mx-auto mb-3 text-red-300" />
              <p className="text-sm text-red-600 font-medium">{searchError}</p>
              <button
                onClick={() => search(query)}
                className="mt-3 text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg text-ps-body"
              >
                Retry
              </button>
            </CardContent>
          </Card>
        )}

        {answered && !searchError && results.length === 0 && (
          <Card>
            <CardContent className="py-12 text-center text-ps-hint">
              <Search size={32} className="mx-auto mb-3 opacity-30" />
              <p>No results for &quot;{term}&quot;</p>
            </CardContent>
          </Card>
        )}

        {tooShort && (
          <p className="text-ps-hint text-center mt-12">
            Type at least {SEARCH_MIN_LENGTH} characters to search.
          </p>
        )}

        {!term && (
          <p className="text-ps-hint text-center mt-12">Search clients, tasks, filings, journals...</p>
        )}

        {answered && !searchError && Object.entries(grouped).map(([cat, items]) => {
          const Icon = CATEGORY_ICONS[cat as keyof typeof CATEGORY_ICONS] ?? FileText;
          return (
            <div key={cat} className="mb-6">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-ps-label mb-2 flex items-center gap-1.5">
                <Icon size={12} />{CATEGORY_LABELS[cat as keyof typeof CATEGORY_LABELS]}
              </h2>
              <div className="space-y-1.5">
                {items.map(item => (
                  <Link key={item.id} href={item.href}>
                    <div className="bg-white border rounded-lg px-4 py-3 hover:bg-blue-500/[0.08] hover:border-blue-500/20 transition-colors cursor-pointer">
                      <p className="font-medium text-ps-ink text-sm">{item.title}</p>
                      <p className="text-xs text-ps-label mt-0.5">{item.subtitle}</p>
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
    <Suspense fallback={<div className="min-h-screen bg-ps-bg flex items-center justify-center"><p className="text-ps-label">Loading...</p></div>}>
      <SearchContent />
    </Suspense>
  );
}
