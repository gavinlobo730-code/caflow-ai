"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Search, Users, CheckSquare, FileText, Shield, X } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { useRouter } from "next/navigation";

type SearchResult = {
  id: string;
  category: "clients" | "tasks" | "compliance" | "journals";
  title: string;
  subtitle: string;
  href: string;
};

const CATEGORY_ICONS = {
  clients: Users,
  tasks: CheckSquare,
  compliance: Shield,
  journals: FileText,
};

const CATEGORY_LABELS = {
  clients: "Clients",
  tasks: "Tasks",
  compliance: "Compliance",
  journals: "Journal Entries",
};

async function runSearch(query: string, firmId: string): Promise<SearchResult[]> {
  if (!query.trim()) return [];
  const sb = getSupabaseClient();
  const q = query.trim().toLowerCase();
  const results: SearchResult[] = [];

  const [clientsRes, tasksRes, complianceRes, journalsRes] = await Promise.all([
    sb.from("clients").select("id, client_name, entity_type, pan, gstin").eq("firm_id", firmId).limit(5),
    sb.from("tasks").select("id, title, status, due_date").eq("firm_id", firmId).limit(5),
    sb.from("compliance_items").select("id, compliance_type, due_date, clients(client_name)").eq("firm_id", firmId).limit(5),
    sb.from("journal_entries").select("id, narration, entry_date, reference_no").eq("firm_id", firmId).limit(5),
  ]);

  for (const c of (clientsRes.data ?? [])) {
    if (
      c.client_name?.toLowerCase().includes(q) ||
      c.pan?.toLowerCase().includes(q) ||
      c.gstin?.toLowerCase().includes(q)
    ) {
      results.push({
        id: c.id,
        category: "clients",
        title: c.client_name,
        subtitle: `${c.entity_type ?? "Client"} ${c.gstin ? `• ${c.gstin}` : ""}`,
        href: `/clients/${c.id}`,
      });
    }
  }

  for (const t of (tasksRes.data ?? [])) {
    if (t.title?.toLowerCase().includes(q)) {
      results.push({
        id: t.id,
        category: "tasks",
        title: t.title,
        subtitle: `${t.status ?? "todo"} ${t.due_date ? `• Due ${t.due_date}` : ""}`,
        href: `/tasks`,
      });
    }
  }

  for (const comp of (complianceRes.data ?? [])) {
    const clientName = (comp as { clients?: { client_name?: string } }).clients?.client_name ?? "";
    if (comp.compliance_type?.toLowerCase().includes(q) || clientName.toLowerCase().includes(q)) {
      results.push({
        id: comp.id,
        category: "compliance",
        title: comp.compliance_type,
        subtitle: `${clientName} ${comp.due_date ? `• Due ${comp.due_date}` : ""}`,
        href: `/compliance`,
      });
    }
  }

  for (const j of (journalsRes.data ?? [])) {
    const ref = (j as { reference_no?: string }).reference_no;
    if (j.narration?.toLowerCase().includes(q) || ref?.toLowerCase().includes(q)) {
      results.push({
        id: j.id,
        category: "journals",
        title: j.narration ?? "Journal Entry",
        subtitle: j.entry_date ?? "",
        href: `/accounting/journal`,
      });
    }
  }

  return results;
}

export function SearchModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [firmId, setFirmId] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  useEffect(() => {
    getFirmId().then(setFirmId).catch(() => {});
  }, []);

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
    if (!firmId || !q.trim()) { setResults([]); return; }
    setLoading(true);
    const res = await runSearch(q, firmId);
    setResults(res);
    setSelectedIndex(0);
    setLoading(false);
  }, [firmId]);

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
      className="fixed inset-0 z-50 flex items-start justify-center pt-20 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-[#16161f] rounded-2xl shadow-[0_24px_60px_rgba(0,0,0,0.6),0_0_0_1px_rgba(255,255,255,0.03)] border border-white/[0.08] w-full max-w-2xl mx-4 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-white/[0.06]">
          <Search size={18} className="text-white/30 shrink-0" />
          <input
            ref={inputRef}
            type="text"
            className="flex-1 text-base outline-none text-white/90 placeholder:text-white/30 bg-transparent"
            placeholder="Search clients, tasks, filings, journals..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-white/[0.05] transition-colors"
          >
            <X size={15} className="text-white/30" />
          </button>
        </div>

        {/* Results */}
        <div className="max-h-96 overflow-y-auto">
          {loading && (
            <div className="p-4 space-y-2">
              {[1, 2, 3].map(i => (
                <div key={i} className="h-12 bg-white/[0.06] rounded-lg animate-pulse" />
              ))}
            </div>
          )}

          {!loading && query && allResults.length === 0 && (
            <div className="py-12 text-center text-white/30">
              <p className="text-sm">No results for &quot;{query}&quot;</p>
            </div>
          )}

          {!loading && !query && (
            <div className="py-12 text-center text-white/30">
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
                      <span className="text-[10px] font-semibold uppercase tracking-widest text-white/30 flex items-center gap-1">
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
                              ? "bg-indigo-500/15"
                              : "hover:bg-indigo-500/10"
                          }`}
                          onClick={() => { router.push(item.href); onClose(); }}
                        >
                          <p className="text-sm font-medium text-white/90">{item.title}</p>
                          <p className="text-xs text-white/35">{item.subtitle}</p>
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
        <div className="border-t border-white/[0.06] px-4 py-2 flex items-center gap-4 text-xs text-white/30">
          <span><kbd className="font-mono">↑↓</kbd> navigate</span>
          <span><kbd className="font-mono">Enter</kbd> select</span>
          <span><kbd className="font-mono">Esc</kbd> close</span>
          <span className="ml-auto"><kbd className="font-mono">⌘K</kbd> to open</span>
        </div>
      </div>
    </div>
  );
}
