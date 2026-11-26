"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Library, Search, Plus, RefreshCw } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { usePermissions } from "@/lib/auth/AuthContext";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { SectionPlaceholder } from "@/components/ui/page-frame";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { PageHeader } from "@/components/ui/page-header";

interface Article {
  id: string; title: string; current_version: number; tags?: string[]; updated_at?: string;
  /** Where the searched words were found, when the list answers a search: the server reads the title and the current text. */
  matched_in?: string[];
}

/** The server found the searched words in this article's current text and not in its title, so the title alone does not
 *  show why it is listed. */
function foundInTextOnly(a: Article): boolean {
  return Array.isArray(a.matched_in) && a.matched_in.includes("text") && !a.matched_in.includes("title");
}

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
  // The words the list on screen answers (empty for the plain list), set with the list itself so the empty sentence below
  // describes the answer shown, not the box, which runs ahead of it while a search is waiting or in flight.
  const [answered, setAnswered] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ title: "", content: "", tags: "" });
  const [saving, setSaving] = useState(false);

  // apex-overview-practice-07(d): `load` used to close over `query` and run
  // from a `useEffect([load])` — so it re-ran on EVERY keystroke with no
  // debounce, and a SEPARATE Enter-key handler fired it again on top. Two
  // requests in flight at once raced: an earlier, slower keystroke's
  // response could land AFTER a later, faster one's and overwrite it with
  // results for a query the box no longer shows.
  //
  // `latestQuery` is the stale-response guard: `load` is now given the exact
  // query text it was asked to search for, and applies its result only if
  // that text still matches what the input holds by the time the response
  // comes back — an in-flight request for an old query can never clobber a
  // newer one.
  const latestQuery = useRef(query);
  useEffect(() => { latestQuery.current = query; }, [query]);

  // Default (empty-query) load reads client-scoped articles directly from
  // Supabase — this is what kb.search_articles degenerates to when `query`
  // is empty: .eq("client_id", ...).eq("is_archived", false), ordered by
  // updated_at desc. Its internal-client (G1) defense-in-depth filter is
  // already enforced at the DB layer by the knowledge_articles RLS policies
  // (own-firm + assignment + *_internal_partner_only, migrations 073/074/079),
  // which this RLS-bound anon-key client is subject to — no need to
  // re-implement that check here. Once the CA types a search, it goes to the
  // server, which reads each article's title and its CURRENT text (the text
  // lives in the version rows, which this screen does not read) and lists the
  // matches newest first, with no ranking.
  const load = useCallback(async (q: string) => {
    if (!clientId) return;
    setLoading(true); setError(null);
    try {
      let result: Article[];
      if (q) {
        const r = await api.knowledge.clientArticles(clientId, q) as ApiResp<Article[]>;
        result = r.data ?? [];
      } else {
        const supabase = getSupabaseClient();
        const { data, error } = await selectAll(() =>
          supabase.from("knowledge_articles")
            .select("id, title, current_version, tags, updated_at")
            .eq("client_id", clientId)
            .eq("is_archived", false)
            .order("updated_at", { ascending: false }));
        // The pager hands a failure back as `error` and does not throw: a list that stopped partway is not the client's articles.
        if (error) throw new Error("The articles could not be read.");
        result = (data as Article[]) ?? [];
      }
      if (latestQuery.current === q) { setArticles(result); setAnswered(q.trim()); }
    } catch (e) {
      if (latestQuery.current === q) setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      if (latestQuery.current === q) setLoading(false);
    }
  }, [clientId]);

  // Loads immediately when the client changes (no debounce — there is
  // nothing to wait for, unlike a keystroke), then debounces ~300ms behind
  // further typing so a fast typist fires one request per pause rather than
  // one per character.
  const isFirstLoadForThisClient = useRef(true);
  useEffect(() => {
    isFirstLoadForThisClient.current = true;
  }, [clientId]);
  useEffect(() => {
    if (!clientId) return;
    if (isFirstLoadForThisClient.current) {
      isFirstLoadForThisClient.current = false;
      load(query);
      return;
    }
    const timer = setTimeout(() => load(query), 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `load` is
    // stable per clientId (see its own deps); including it here would fire
    // this effect on every render for no reason.
  }, [clientId, query]);

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
      await load(query);
    } catch (e) { setError(e instanceof Error ? e.message : "Create failed"); }
    finally { setSaving(false); }
  }

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <PageHeader
        icon={<Library size={18} className="text-brand" />}
        title="Client Knowledge"
        actions={
          <div className="flex items-center gap-3">
            {canAuthor && (
              <button onClick={() => setShowForm((v) => !v)} className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-brand text-white">
                <Plus size={13} /> New article
              </button>
            )}
            <button onClick={() => load(query)} aria-label="Reload" title="Reload" className="text-gray-400 hover:text-brand"><RefreshCw size={14} aria-hidden="true" /></button>
          </div>
        }
        className="mb-4"
      />
      <div className="flex items-center gap-2 flex-1 border border-gray-200 rounded-lg px-3 py-1.5 bg-white mb-4 focus-within:ring-2 focus-within:ring-brand">
        <Search size={14} className="text-gray-400" />
        {/* No Enter-key handler: the debounced effect above already covers
            every keystroke, Enter included, ~300ms after typing stops. */}
        <input aria-label="Search client articles" value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder="Search this client's titles and text…" className="flex-1 text-sm outline-none" />
      </div>
      {error && <div className="text-xs text-red-600 mb-2">{error}</div>}
      {showForm && canAuthor && (
        <form onSubmit={createArticle} className="mb-4 bg-white border border-ps-border rounded-xl p-4 space-y-2 text-sm">
          <input aria-label="Title" required placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="w-full border rounded-lg px-2 py-1.5" />
          <textarea aria-label="Content" placeholder="Content…" value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} className="w-full border rounded-lg px-2 py-1.5" rows={4} />
          <input aria-label="Tags, comma-separated" placeholder="Tags (comma-separated)" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} className="w-full border rounded-lg px-2 py-1.5" />
          <button type="submit" disabled={saving} className="px-3 py-1.5 rounded-lg bg-brand text-white text-xs disabled:opacity-50">Create</button>
        </form>
      )}
      {loading ? <SectionPlaceholder label="Loading this client's knowledge" shape="list" rows={4} onRetry={() => { void load(query); }} /> : (
        <div className="space-y-2">
          {articles.length === 0 && !answered && <p className="text-xs text-gray-600">No client-scoped articles.</p>}
          {articles.length === 0 && answered && (
            <p className="text-xs text-gray-600">
              No article of this client has every word of &ldquo;{answered}&rdquo; in its title or its current text.
            </p>
          )}
          {articles.map((a) => (
            <div key={a.id} className="bg-white border border-gray-200 rounded-xl px-4 py-3">
              <p className="text-sm font-medium text-brand">{a.title}</p>
              <p className="text-2xs text-gray-400 mt-0.5">v{a.current_version}{a.tags && a.tags.length ? ` · ${a.tags.join(", ")}` : ""}</p>
              {foundInTextOnly(a) && (
                <p className="text-2xs text-ps-label mt-0.5" data-testid={`article-${a.id}-found-in-text`}>
                  The words are in the article&rsquo;s text, not its title.
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
