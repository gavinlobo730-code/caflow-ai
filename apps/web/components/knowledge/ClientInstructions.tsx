"use client";

import { useState, useEffect, useCallback } from "react";
import { StickyNote, Plus, Pin, Archive, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";

export interface Instruction {
  id: string; client_id: string; title: string; body: string;
  is_pinned: boolean; created_at?: string;
}

/**
 * Client standing instructions (Amendment v1.1 FR-KB-02). Display + actions only;
 * visibility/authoring is enforced by the backend (assignment-gated). When
 * `pinnedOnly` is set, renders a read-only pinned-card list (for the Overview).
 */
export function ClientInstructions({
  clientId, pinnedOnly = false, canWrite = true,
}: { clientId: string; pinnedOnly?: boolean; canWrite?: boolean }) {
  const [items, setItems] = useState<Instruction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ title: "", body: "", is_pinned: false });

  // Direct Supabase read (RLS-enforced: knowledge_articles_own_firm /
  // client_instructions_assignment / *_internal_partner_only policies mirror
  // the backend's _assert_client_access + G1 gate) — avoids a FastAPI
  // cold-start for a plain filtered select. Mirrors kb.list_client_instructions'
  // ordering (pinned first, then newest).
  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true); setError(null);
    try {
      const supabase = getSupabaseClient();
      const { data } = await selectAll(() =>
        supabase.from("client_instructions")
          .select("id, client_id, title, body, is_pinned, created_at")
          .eq("client_id", clientId)
          .order("is_pinned", { ascending: false })
          .order("created_at", { ascending: false }));
      setItems((data as Instruction[]) ?? []);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load instructions"); }
    finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { load(); }, [load]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    try { await api.instructions.create(clientId, form); setShowForm(false); setForm({ title: "", body: "", is_pinned: false }); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Create failed"); }
  }
  async function togglePin(i: Instruction) {
    try { await api.instructions.update(clientId, i.id, { is_pinned: !i.is_pinned }); await load(); } catch { /* backend enforces */ }
  }
  async function archive(i: Instruction) {
    try { await api.instructions.archive(clientId, i.id); await load(); } catch { /* backend enforces */ }
  }

  const visible = pinnedOnly ? items.filter((i) => i.is_pinned) : items;
  if (loading) return <div className="text-[12px] text-gray-400">Loading instructions…</div>;
  if (pinnedOnly && visible.length === 0) return null;

  return (
    <div>
      {!pinnedOnly && (
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <StickyNote size={16} className="text-[#182350]" />
            <h2 className="text-sm font-semibold text-[#182350]">Client Instructions</h2>
          </div>
          <div className="flex items-center gap-3">
            {canWrite && <button onClick={() => setShowForm((v) => !v)} className="flex items-center gap-1 text-[12px] px-2.5 py-1 rounded-lg bg-[#182350] text-white"><Plus size={12} /> Add</button>}
            <button onClick={load} className="text-gray-400 hover:text-[#182350]"><RefreshCw size={13} /></button>
          </div>
        </div>
      )}
      {error && <div className="text-[12px] text-red-600 mb-2">{error}</div>}
      {showForm && canWrite && (
        <form onSubmit={create} className="mb-3 bg-white border border-gray-200 rounded-lg p-3 space-y-2 text-sm">
          <input required placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="w-full border rounded-lg px-2 py-1.5" />
          <textarea placeholder="Standing instruction…" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} className="w-full border rounded-lg px-2 py-1.5" rows={2} />
          <label className="flex items-center gap-2 text-[12px] text-gray-600"><input type="checkbox" checked={form.is_pinned} onChange={(e) => setForm({ ...form, is_pinned: e.target.checked })} /> Pin to top</label>
          <button type="submit" className="px-3 py-1.5 rounded-lg bg-[#182350] text-white text-[12px]">Save</button>
        </form>
      )}
      <div className="space-y-2">
        {visible.map((i) => (
          <div key={i.id} className="bg-white border border-gray-200 rounded-lg p-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="text-[13px] font-medium text-[#182350] flex items-center gap-1.5">
                  {i.is_pinned && <Pin size={11} className="text-amber-500" />}{i.title}
                </p>
                {i.body && <p className="text-[12px] text-gray-600 mt-0.5 whitespace-pre-wrap">{i.body}</p>}
              </div>
              {!pinnedOnly && canWrite && (
                <div className="flex items-center gap-2 shrink-0">
                  <button onClick={() => togglePin(i)} title="Pin/unpin" className="text-gray-400 hover:text-amber-500"><Pin size={13} /></button>
                  <button onClick={() => archive(i)} title="Archive" className="text-gray-400 hover:text-red-500"><Archive size={13} /></button>
                </div>
              )}
            </div>
          </div>
        ))}
        {!pinnedOnly && visible.length === 0 && <p className="text-[12px] text-gray-400">No instructions yet.</p>}
      </div>
    </div>
  );
}
