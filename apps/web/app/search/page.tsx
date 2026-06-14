"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Search, Users, CheckSquare, FileText, Shield } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import Link from "next/link";

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
    sb.from("clients").select("id, client_name, entity_type, pan, gstin").eq("firm_id", firmId).eq("is_internal", false),
    sb.from("tasks").select("id, title, status, due_date, client_id").eq("firm_id", firmId),
    sb.from("compliance_items").select("id, compliance_type, due_date, client_id, clients(client_name)").eq("firm_id", firmId),
    sb.from("journal_entries").select("id, narration, entry_date, reference_no").eq("firm_id", firmId),
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
    if (
      comp.compliance_type?.toLowerCase().includes(q) ||
      clientName.toLowerCase().includes(q)
    ) {
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
    if (
      j.narration?.toLowerCase().includes(q) ||
      (j as { reference_no?: string }).reference_no?.toLowerCase().includes(q)
    ) {
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

function SearchContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [firmId, setFirmId] = useState<string | null>(null);

  useEffect(() => {
    getFirmId().then(setFirmId).catch(() => {});
  }, []);

  const search = useCallback(async (q: string) => {
    if (!firmId || !q.trim()) { setResults([]); return; }
    setLoading(true);
    const res = await runSearch(q, firmId);
    setResults(res);
    setLoading(false);
  }, [firmId]);

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
              <div key={i} className="h-14 bg-white/[0.08] rounded-lg animate-pulse" />
            ))}
          </div>
        )}

        {!loading && query && results.length === 0 && (
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
