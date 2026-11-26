"use client";

import { Button } from "@/components/ui/button";
import { Suspense, useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { Library, Search, Plus, History, RotateCcw, RefreshCw } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { usePermissions } from "@/lib/auth/AuthContext";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/states";
import { EmptyStateAction, EmptyStateActions } from "@/components/ui/empty-state-action";
import { formatDate } from "@/lib/dates/format";
import { PagePlaceholder, SectionPlaceholder, pageFrameClass } from "@/components/ui/page-frame";

interface Article {
  id: string; scope: string; department?: string | null; client_id?: string | null;
  title: string; current_version: number; tags?: string[]; is_archived?: boolean; updated_at?: string;
  /** Where the searched words were found, when the list answers a search: the server reads the title and the current text. */
  matched_in?: string[];
}
interface Version { version: number; changed_by?: string | null; changed_at?: string }

/** The server found the searched words in this article's current text and not in its title, so the title alone does not
 *  show why it is listed. */
function foundInTextOnly(a: Article): boolean {
  return Array.isArray(a.matched_in) && a.matched_in.includes("text") && !a.matched_in.includes("title");
}

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
  // This row's request is in flight. These handlers had no loading state at
  // all, so the button was never disabled and a second click sent it again.
  const [rowBusy, setRowBusy] = useState(false);

  const scope = params.get("scope") ?? undefined;

  // The words the list on screen answers; empty when it is the plain list.
  const [answered, setAnswered] = useState("");

  // A search runs about 300ms after typing stops, and only the newest request's answer is shown. `load` used to re-run on
  // every keystroke and again on Enter, so an earlier, slower answer could land after a later one and list articles for
  // words the box no longer held (the client's knowledge screen had the same race and the same cure). The search now reads
  // each article's current text as well as its title, so a request costs more than a title match did.
  const latestRun = useRef(0);
  const load = useCallback(async (words: string) => {
    const run = ++latestRun.current;
    const wanted = words.trim();
    setLoading(true); setError(null);
    try {
      const p: Record<string, string> = {};
      if (scope) p.scope = scope;
      if (wanted) p.query = wanted;
      const r = await api.knowledge.listArticles(p) as ApiResp<Article[]>;
      if (run !== latestRun.current) return;
      setArticles(r.data ?? []);
      setAnswered(wanted);
    } catch (e) {
      if (run === latestRun.current) setError(e instanceof Error ? e.message : "Failed to load articles");
    } finally {
      if (run === latestRun.current) setLoading(false);
    }
  }, [scope]);
  // A new scope (or the first render) loads at once; typing waits for a pause.
  const loadedWith = useRef<typeof load | null>(null);
  useEffect(() => {
    if (loadedWith.current !== load) {
      loadedWith.current = load;
      void load(query);
      return;
    }
    const timer = setTimeout(() => { void load(query); }, 300);
    return () => clearTimeout(timer);
  }, [load, query]);

  async function open(id: string) {
    setRowBusy(true);
    try {
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);
    try {
      const a = await api.knowledge.getArticle(id) as ApiResp<Article & { content?: string }>;
      setContent(a.data?.content ?? "");
      const v = await api.knowledge.listVersions(id) as ApiResp<Version[]>;
      setVersions(v.data ?? []);
    } catch { setContent(""); setVersions([]); }
  } finally { setRowBusy(false); }
  }

  async function createArticle(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.knowledge.createArticle({
        scope: form.scope, title: form.title, content: form.content,
        department: form.department || null,
        tags: form.tags ? form.tags.split(",").map((t) => t.trim()).filter(Boolean) : [],
      });
      setShowForm(false); setForm({ scope: "firm", title: "", content: "", department: "", tags: "" }); await load(query);
    } catch (e) { setError(e instanceof Error ? e.message : "Create failed"); }
  }

  async function restore(id: string, version: number) {
    setRowBusy(true);
    setError("");
    try {
      // A refused restore (the backend enforces who may) is said, not swallowed: the page used to look as if the version had come back
      // (POST-A-515). `open` is asked once; it was asked twice.
      const res = (await api.knowledge.restoreVersion(id, version)) as { success?: boolean; error?: string | null } | null;
      if (res && res.success === false) {
        setError(res.error ?? "Couldn't restore that version.");
        return;
      }
      await open(id);
      // A restore writes a new current version, so the row's version and what a search finds in its text have moved.
      void load(query);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't restore that version.");
    } finally { setRowBusy(false); }
  }

  return (
    <div className={pageFrameClass("data")}>
      <PageHeader
        icon={<Library size={18} className="text-brand" />}
        title={`Knowledge Base${scope ? ` — ${scope}` : ""}`}
        meta={!loading && !error ? <span className="text-xs text-ps-hint">{articles.length} article{articles.length === 1 ? "" : "s"}</span> : undefined}
        actions={
          <>
            {canAuthor && <button onClick={() => setShowForm((v) => !v)} className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-brand text-white"><Plus size={13} /> New article</button>}
            <button aria-label="Refresh" onClick={() => { void load(query); }} className="text-ps-hint hover:text-brand"><RefreshCw size={14} /></button>
          </>
        }
        className="mb-4"
      />

      <div className="flex items-center gap-2 mb-4">
        <div className="flex items-center gap-2 flex-1 border border-gray-200 rounded-lg px-3 py-1.5 bg-white focus-within:ring-2 focus-within:ring-brand">
          <Search size={14} className="text-ps-hint" />
          {/* No Enter-key handler: the debounced effect above already covers every keystroke, Enter included. */}
          <input aria-label="Search articles" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="Search titles and text…" className="flex-1 text-sm outline-none" />
        </div>
      </div>

      {error && <div className="text-xs text-red-600 mb-2">{error}</div>}

      {showForm && canAuthor && (
        <form onSubmit={createArticle} className="mb-4 bg-white border border-gray-200 rounded-xl p-4 space-y-2 text-sm">
          <div className="flex gap-2">
            <select aria-label="Article scope" value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })} className="border rounded-lg px-2 py-1.5">
              <option value="firm">Firm</option><option value="department">Department</option>
            </select>
            <input aria-label="Department (optional)" placeholder="Department (optional)" value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} className="border rounded-lg px-2 py-1.5 flex-1" />
          </div>
          <input aria-label="Title" required placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="w-full border rounded-lg px-2 py-1.5" />
          <textarea aria-label="Content" placeholder="Content…" value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} className="w-full border rounded-lg px-2 py-1.5" rows={4} />
          <input aria-label="Tags, comma-separated" placeholder="Tags (comma-separated)" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} className="w-full border rounded-lg px-2 py-1.5" />
          <button type="submit" className="px-3 py-1.5 rounded-lg bg-brand text-white text-xs">Create</button>
        </form>
      )}

      {loading ? <SectionPlaceholder label="Loading articles" shape="list" onRetry={() => { void load(query); }} /> : (
        <div className="space-y-2">
          {articles.length === 0 && !answered && (
            <EmptyState
              className="py-10"
              icon={<Library size={32} />}
              title="No articles found"
              description="The firm's own articles are listed here. A Partner or Manager writes one with New article."
              action={
                <EmptyStateActions>
                  <EmptyStateAction requires={["knowledge", "write"]} icon={<Plus size={14} />} label="New article" onClick={() => setShowForm(true)} />
                </EmptyStateActions>
              }
            />
          )}
          {articles.length === 0 && answered && (
            <p className="text-xs text-ps-hint">
              No article in this list has every word of &ldquo;{answered}&rdquo; in its title or its current text.
            </p>
          )}
          {articles.map((a) => (
            <div key={a.id} className="bg-white border border-gray-200 rounded-xl">
              <button disabled={rowBusy} onClick={() => open(a.id)} className="w-full flex items-center justify-between px-4 py-3 text-left">
                <div>
                  <p className="text-sm font-medium text-brand">{a.title}</p>
                  <p className="text-2xs text-ps-hint mt-0.5">
                    {a.scope}{a.department ? ` · ${a.department}` : ""} · v{a.current_version}
                    {a.tags && a.tags.length > 0 ? ` · ${a.tags.join(", ")}` : ""}
                  </p>
                  {foundInTextOnly(a) && (
                    <p className="text-2xs text-ps-label mt-0.5" data-testid={`article-${a.id}-found-in-text`}>
                      The words are in the article&rsquo;s text, not its title.
                    </p>
                  )}
                </div>
                <History size={14} className="text-ps-hint" />
              </button>
              {expanded === a.id && (
                <div className="border-t border-ps-border px-4 py-3">
                  <p className="text-sm text-gray-700 whitespace-pre-wrap mb-3">{content || <span className="text-ps-hint">No content.</span>}</p>
                  <p className="text-2xs font-medium text-gray-500 uppercase mb-1">Version history</p>
                  <ul className="space-y-1">
                    {versions.map((v) => (
                      <li key={v.version} className="flex items-center justify-between text-xs text-gray-600">
                        <span>v{v.version}{v.changed_at ? ` · ${formatDate(v.changed_at)}` : ""}</span>
                        {canAuthor && v.version !== a.current_version && (
                          <Button variant="plain" size="none" spinner={false} disabled={rowBusy} onClick={() => restore(a.id, v.version)} className="flex items-center gap-1 text-blue-600 hover:underline"><RotateCcw size={11} /> Restore</Button>
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
    <Suspense fallback={<PagePlaceholder label="Loading the knowledge base" shape="list" />}>
      <KnowledgeInner />
    </Suspense>
  );
}
