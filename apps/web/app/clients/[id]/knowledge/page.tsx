"use client";

import { useState, useEffect, useCallback } from "react";
import { Library, Search, Plus, RefreshCw } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { usePermissions } from "@/lib/auth/AuthContext";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { PageLoader } from "@/components/ui/skeleton";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";

interface Article { id: string; title: string; current_version: number; tags?: string[]; updated_at?: string }

export default function ClientKnowledgePage() {
  const { clientId } = useClientNav();
  // Same gate the firm-wide Knowledge Base uses for its own create control —
  // knowledge:write, Manager+ (core/permissions.py). Not a new gate.
  const { can } = usePermissions();
  const canAuthor = can("knowledge", "write");
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ title: "", content: "", tags: "" });
  const [saving, setSaving] = useState(false);

  // Default (empty-query) load reads client-scoped articles directly from
  // Supabase — this is what kb.search_articles degenerates to when `query`
  // is empty: .eq("client_id", ...).eq("is_archived", false), ordered by
  // updated_at desc. Its internal-client (G1) defense-in-depth filter is
  // already enforced at the DB layer by the knowledge_articles RLS policies
  // (own-firm + assignment + *_internal_partner_only, migrations 073/074/079),
  // which this RLS-bound anon-key client is subject to — no need to
  // re-implement that check here. Once the CA types a real search query, that
  // becomes relevance-ranked search and stays backend-routed (same reasoning
  // as ServiceCataloguePicker).
  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true); setError(null);
    try {
      if (query) {
        const r = await api.knowledge.clientArticles(clientId, query) as ApiResp<Article[]>;
        setArticles(r.data ?? []);
      } else {
        const supabase = getSupabaseClient();
        const { data } = await selectAll(() =>
          supabase.from("knowledge_articles")
            .select("id, title, current_version, tags, updated_at")
            .eq("client_id", clientId)
            .eq("is_archived", false)
            .order("updated_at", { ascending: false }));
        setArticles((data as Article[]) ?? []);
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
    finally { setLoading(false); }
  }, [clientId, query]);
  useEffect(() => { load(); }, [load]);

  async function createArticle(e: React.FormEvent) {
    e.preventDefault();
    if (!clientId) return;
    setSaving(true);
    try {
      await api.knowledge.createArticle({
        scope: "client",
        client_id: clientId,
        title: form.title,
        content: form.content,
        tags: form.tags ? form.tags.split(",").map((t) => t.trim()).filter(Boolean) : [],
      });
      setShowForm(false);
      setForm({ title: "", content: "", tags: "" });
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Create failed"); }
    finally { setSaving(false); }
  }

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Library size={18} className="text-brand" />
          <h1 className="text-lg font-semibold text-brand">Client Knowledge</h1>
        </div>
        <div className="flex items-center gap-3">
          {canAuthor && (
            <button onClick={() => setShowForm((v) => !v)} className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-brand text-white">
              <Plus size={13} /> New article
            </button>
          )}
          <button onClick={load} className="text-gray-400 hover:text-brand"><RefreshCw size={14} /></button>
        </div>
      </div>
      <div className="flex items-center gap-2 flex-1 border border-gray-200 rounded-lg px-3 py-1.5 bg-white mb-4">
        <Search size={14} className="text-gray-400" />
        <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load()}
          placeholder="Search client articles…" className="flex-1 text-sm outline-none" />
      </div>
      {error && <div className="text-xs text-red-600 mb-2">{error}</div>}
      {showForm && canAuthor && (
        <form onSubmit={createArticle} className="mb-4 bg-white border border-ps-border rounded-xl p-4 space-y-2 text-sm">
          <input required placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="w-full border rounded-lg px-2 py-1.5" />
          <textarea placeholder="Content…" value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} className="w-full border rounded-lg px-2 py-1.5" rows={4} />
          <input placeholder="Tags (comma-separated)" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} className="w-full border rounded-lg px-2 py-1.5" />
          <button type="submit" disabled={saving} className="px-3 py-1.5 rounded-lg bg-brand text-white text-xs disabled:opacity-50">Create</button>
        </form>
      )}
      {loading ? <PageLoader /> : (
        <div className="space-y-2">
          {articles.length === 0 && <p className="text-xs text-gray-400">No client-scoped articles.</p>}
          {articles.map((a) => (
            <div key={a.id} className="bg-white border border-gray-200 rounded-xl px-4 py-3">
              <p className="text-sm font-medium text-brand">{a.title}</p>
              <p className="text-2xs text-gray-400 mt-0.5">v{a.current_version}{a.tags && a.tags.length ? ` · ${a.tags.join(", ")}` : ""}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
