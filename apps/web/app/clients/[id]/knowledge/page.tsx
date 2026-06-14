"use client";

import { useState, useEffect, useCallback } from "react";
import { Library, Search, RefreshCw } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

interface Article { id: string; title: string; current_version: number; tags?: string[]; updated_at?: string }

export default function ClientKnowledgePage() {
  const { clientId } = useClientNav();
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true); setError(null);
    try {
      const r = await api.knowledge.clientArticles(clientId, query || undefined) as ApiResp<Article[]>;
      setArticles(r.data ?? []);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
    finally { setLoading(false); }
  }, [clientId, query]);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-6 max-w-3xl">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Library size={18} className="text-[#182350]" />
          <h1 className="text-lg font-semibold text-[#182350]">Client Knowledge</h1>
        </div>
        <button onClick={load} className="text-gray-400 hover:text-[#182350]"><RefreshCw size={14} /></button>
      </div>
      <div className="flex items-center gap-2 flex-1 border border-gray-200 rounded-lg px-3 py-1.5 bg-white mb-4">
        <Search size={14} className="text-gray-400" />
        <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load()}
          placeholder="Search client articles…" className="flex-1 text-sm outline-none" />
      </div>
      {error && <div className="text-[12px] text-red-600 mb-2">{error}</div>}
      {loading ? <div className="text-sm text-gray-500">Loading…</div> : (
        <div className="space-y-2">
          {articles.length === 0 && <p className="text-[12px] text-gray-400">No client-scoped articles.</p>}
          {articles.map((a) => (
            <div key={a.id} className="bg-white border border-gray-200 rounded-xl px-4 py-3">
              <p className="text-[13px] font-medium text-[#182350]">{a.title}</p>
              <p className="text-[11px] text-gray-400 mt-0.5">v{a.current_version}{a.tags && a.tags.length ? ` · ${a.tags.join(", ")}` : ""}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
