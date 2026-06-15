"use client";

import { useState, useEffect, useCallback } from "react";
import { Link2, Search, Check, Loader2, ShieldAlert } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { useAuth } from "@/lib/auth/AuthContext";

interface Member { id: string; full_name?: string; email?: string; role?: string }
interface Client { id: string; client_name?: string; entity_type?: string; gstin?: string }

// Module 9.0 M3 — Client Assignment Administration.
// Partner assigns clients to staff; this controls what each user can discover,
// view, search, be notified about, and use as AI context (enforced server-side).
export default function AssignmentsPage() {
  const { userRole } = useAuth();
  const isPartner = userRole === "Partner";

  const [members, setMembers] = useState<Member[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedUser, setSelectedUser] = useState<string | null>(null);
  const [assigned, setAssigned] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [t, c] = await Promise.all([
          api.team.list() as Promise<ApiResp<Member[] | { members: Member[] }>>,
          api.clients.list() as Promise<ApiResp<{ clients: Client[] }>>,
        ]);
        const mem = Array.isArray(t.data) ? t.data : (t.data?.members ?? []);
        setMembers(mem.filter((m) => m.role !== "Partner")); // Partners are firm-wide; no assignment needed
        setClients(c.data?.clients ?? []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const loadAssignments = useCallback(async (userId: string) => {
    setSelectedUser(userId);
    setAssigned(new Set());
    try {
      const r = await api.assignments.listForUser(userId);
      setAssigned(new Set(r.data?.client_ids ?? []));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load assignments");
    }
  }, []);

  async function toggle(clientId: string) {
    if (!selectedUser || !isPartner) return;
    setBusy(clientId); setError(null);
    const isAssigned = assigned.has(clientId);
    try {
      if (isAssigned) await api.assignments.remove(selectedUser, clientId);
      else await api.assignments.create(selectedUser, clientId);
      setAssigned((prev) => {
        const next = new Set(prev);
        if (isAssigned) next.delete(clientId); else next.add(clientId);
        return next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusy(null);
    }
  }

  const shownClients = clients.filter((c) =>
    !filter || (c.client_name ?? "").toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center gap-2 mb-1">
        <Link2 size={18} className="text-[#182350]" />
        <h1 className="text-lg font-semibold text-[#182350]">Client Assignments</h1>
      </div>
      <p className="text-[12px] text-gray-500 mb-4">
        Assign clients to staff. A user can only see, search, and be notified about clients assigned to them
        (Partners have firm-wide access and are not listed here).
      </p>

      {!isPartner && (
        <div className="flex items-center gap-2 text-[12px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4">
          <ShieldAlert size={14} /> View only — only a Partner can change assignments.
        </div>
      )}
      {error && <div className="text-[12px] text-red-600 mb-3">{error}</div>}

      {loading ? (
        <div className="text-sm text-gray-500">Loading…</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-4">
          {/* Staff list */}
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <div className="px-3 py-2 border-b border-gray-100 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
              Staff
            </div>
            {members.length === 0 && <p className="px-3 py-4 text-[12px] text-gray-400">No staff members.</p>}
            {members.map((m) => (
              <button
                key={m.id}
                onClick={() => loadAssignments(m.id)}
                className={`w-full text-left px-3 py-2.5 border-b border-gray-50 transition-colors ${
                  selectedUser === m.id ? "bg-[#182350] text-white" : "hover:bg-[#F8FAFC]"
                }`}
              >
                <p className="text-[13px] font-medium">{m.full_name || m.email || "—"}</p>
                <p className={`text-[11px] ${selectedUser === m.id ? "text-white/70" : "text-gray-400"}`}>{m.role}</p>
              </button>
            ))}
          </div>

          {/* Client assignment grid */}
          <div className="bg-white border border-gray-200 rounded-xl">
            {!selectedUser ? (
              <p className="px-4 py-10 text-center text-[12px] text-gray-400">Select a staff member to manage their clients.</p>
            ) : (
              <>
                <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-100">
                  <Search size={14} className="text-gray-400" />
                  <input
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    placeholder="Filter clients…"
                    className="flex-1 text-sm outline-none"
                  />
                  <span className="text-[11px] text-gray-400">{assigned.size} assigned</span>
                </div>
                <div className="max-h-[60vh] overflow-y-auto">
                  {shownClients.map((c) => {
                    const on = assigned.has(c.id);
                    return (
                      <button
                        key={c.id}
                        disabled={!isPartner || busy === c.id}
                        onClick={() => toggle(c.id)}
                        className="w-full flex items-center justify-between px-4 py-2.5 border-b border-gray-50 hover:bg-[#F8FAFC] disabled:opacity-60"
                      >
                        <div className="text-left">
                          <p className="text-[13px] text-[#182350]">{c.client_name}</p>
                          <p className="text-[11px] text-gray-400">{c.entity_type}{c.gstin ? ` · ${c.gstin}` : ""}</p>
                        </div>
                        <span className={`flex items-center justify-center w-5 h-5 rounded border ${
                          on ? "bg-[#182350] border-[#182350] text-white" : "border-gray-300"
                        }`}>
                          {busy === c.id ? <Loader2 size={12} className="animate-spin" /> : on ? <Check size={12} /> : null}
                        </span>
                      </button>
                    );
                  })}
                  {shownClients.length === 0 && <p className="px-4 py-6 text-[12px] text-gray-400">No clients.</p>}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
