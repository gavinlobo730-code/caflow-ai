"use client";

import { Suspense, useState, useEffect, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { Library, Search, Plus, History, RotateCcw, RefreshCw } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { usePermissions } from "@/lib/auth/AuthContext";
import { PageLoader } from "@/components/ui/skeleton";

interface Article {
  id: string; scope: string; department?: string | null; client_id?: string | null;
  title: string; current_version: number; tags?: string[]; is_archived?: boolean; updated_at?: string;
}
interface Version { version: number; changed_by?: string | null; changed_at?: string }

function KnowledgeInner() {
  const params = useSearchParams();
  // Was `(userRole ?? "Partner") === "Partner" || userRole === "Manager"` — a
  // hand-rolled copy of knowledge:write that also failed OPEN: an unresolved
  // role defaulted to Partner, so every user was briefly offered the authoring
  // controls on load. The permission map answers false until it resolves.
  const { can } = usePermissions();
  const canAuthor = can("knowledge", "write");

  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [content, setContent] = useState<string>("");
  const [versions, setVersions] = useState<Version[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ scope: "firm", title: "", content: "", department: "", tags: "" });

  const scope = params.get("scope") ?? undefined;

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const p: Record<string, string> = {};
      if (scope) p.scope = scope;
      if (query) p.query = query;
      const r = await api.knowledge.listArticles(p) as ApiResp<Article[]>;
      setArticles(r.data ?? []);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load articles"); }
    finally { setLoading(false); }
  }, [scope, query]);
  useEffect(() => { load(); }, [load]);

  async function open(id: string) {
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);
    try {
      const a = await api.knowledge.getArticle(id) as ApiResp<Article & { content?: string }>;
      setContent(a.data?.content ?? "");
      const v = await api.knowledge.listVersions(id) as ApiResp<Version[]>;
      setVersions(v.data ?? []);
    } catch { setContent(""); setVersions([]); }
  }

  async function createArticle(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.knowledge.createArticle({
        scope: form.scope, title: form.title, content: form.content,
        department: form.department || null,
        tags: form.tags ? form.tags.split(",").map((t) => t.trim()).filter(Boolean) : [],
      });
      setShowForm(false); setForm({ scope: "firm", title: "", content: "", department: "", tags: "" }); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Create failed"); }
  }

  async function restore(id: string, version: number) {
    try { await api.knowledge.restoreVersion(id, version); await open(id); await open(id); } catch { /* backend enforces */ }
  }

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Library size={18} className="text-[#182350]" />
          <h1 className="text-lg font-semibold text-[#182350]">Knowledge Base{scope ? ` — ${scope}` : ""}</h1>
          {!loading && !error && <span className="text-[12px] text-gray-400">{articles.length} article{articles.length === 1 ? "" : "s"}</span>}
        </div>
        <div className="flex items-center gap-3">
          {canAuthor && <button onClick={() => setShowForm((v) => !v)} className="flex items-center gap-1.5 text-[12px] px-3 py-1.5 rounded-lg bg-[#182350] text-white"><Plus size={13} /> New article</button>}
          <button onClick={load} className="text-gray-400 hover:text-[#182350]"><RefreshCw size={14} /></button>
        </div>
      </div>

      <div className="flex items-center gap-2 mb-4">
        <div className="flex items-center gap-2 flex-1 border border-gray-200 rounded-lg px-3 py-1.5 bg-white">
          <Search size={14} className="text-gray-400" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load()}
            placeholder="Search articles…" className="flex-1 text-sm outline-none" />
        </div>
      </div>

      {error && <div className="text-[12px] text-red-600 mb-2">{error}</div>}

      {showForm && canAuthor && (
        <form onSubmit={createArticle} className="mb-4 bg-white border border-gray-200 rounded-xl p-4 space-y-2 text-sm">
          <div className="flex gap-2">
            <select value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })} className="border rounded-lg px-2 py-1.5">
              <option value="firm">Firm</option><option value="department">Department</option>
            </select>
            <input placeholder="Department (optional)" value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} className="border rounded-lg px-2 py-1.5 flex-1" />
          </div>
          <input required placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="w-full border rounded-lg px-2 py-1.5" />
          <textarea placeholder="Content…" value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} className="w-full border rounded-lg px-2 py-1.5" rows={4} />
          <input placeholder="Tags (comma-separated)" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} className="w-full border rounded-lg px-2 py-1.5" />
          <button type="submit" className="px-3 py-1.5 rounded-lg bg-[#182350] text-white text-[12px]">Create</button>
        </form>
      )}

      {loading ? <PageLoader /> : (
        <div className="space-y-2">
          {articles.length === 0 && <p className="text-[12px] text-gray-400">No articles found.</p>}
          {articles.map((a) => (
            <div key={a.id} className="bg-white border border-gray-200 rounded-xl">
              <button onClick={() => open(a.id)} className="w-full flex items-center justify-between px-4 py-3 text-left">
                <div>
                  <p className="text-[13px] font-medium text-[#182350]">{a.title}</p>
                  <p className="text-[11px] text-gray-400 mt-0.5">
                    {a.scope}{a.department ? ` · ${a.department}` : ""} · v{a.current_version}
                    {a.tags && a.tags.length > 0 ? ` · ${a.tags.join(", ")}` : ""}
                  </p>
                </div>
                <History size={14} className="text-gray-400" />
              </button>
              {expanded === a.id && (
                <div className="border-t border-gray-100 px-4 py-3">
                  <p className="text-[13px] text-gray-700 whitespace-pre-wrap mb-3">{content || <span className="text-gray-400">No content.</span>}</p>
                  <p className="text-[11px] font-medium text-gray-500 uppercase mb-1">Version history</p>
                  <ul className="space-y-1">
                    {versions.map((v) => (
                      <li key={v.version} className="flex items-center justify-between text-[12px] text-gray-600">
                        <span>v{v.version}{v.changed_at ? ` · ${v.changed_at.slice(0, 10)}` : ""}</span>
                        {canAuthor && v.version !== a.current_version && (
                          <button onClick={() => restore(a.id, v.version)} className="flex items-center gap-1 text-blue-600 hover:underline"><RotateCcw size={11} /> Restore</button>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function KnowledgePage() {
  return (
    <Suspense fallback={<PageLoader />}>
      <KnowledgeInner />
    </Suspense>
  );
}
