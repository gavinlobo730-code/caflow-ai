"use client";

import { useEffect, useState } from "react";
import { Globe, Copy, X } from "lucide-react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getClient } from "@/lib/data/clients";
import { getFirmId } from "@/lib/data/getFirmId";
import { writeTimelineEvent } from "@/lib/services/timeline";
import { api, type PortalContact } from "@/lib/api";
import type { Client } from "@/lib/types";

export default function PortalPage() {
  const { clientId, financialYear } = useClientNav();
  const [client, setClient] = useState<Client | null>(null);
  const [contacts, setContacts] = useState<PortalContact[]>([]);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteSent, setInviteSent] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Distinguishes "fetch failed" from "client genuinely has no invited
  // portal contacts yet" — without this, both the client record fetch and
  // the contacts fetch failing silently rendered the page identically to
  // "not enabled — client cannot log in yet," with no indication anything
  // went wrong.
  const [pageLoadError, setPageLoadError] = useState<string | null>(null);

  // Direct Supabase read (was api.portal.listContacts → backend select("*")
  // on client_portal_users). EXPLICIT column list only — this table also has
  // invite_token (a live, single-use invite secret; see
  // migrations/153_secure_invite_flows.sql) and invite_expires_at. A
  // browser-side query is a different trust boundary than a backend JSON
  // response: never select("*") here, or a live invite token lands on the
  // client's JS heap / devtools / network tab for anyone with portal-page
  // access to this client. Confirmed unused by this page today — the only
  // frontend read of invite_token is the one-time value returned inline by
  // api.portal.inviteContact()'s POST response, used immediately to build
  // the magic-link URL below, never persisted into `contacts` state.
  async function loadContacts(id: string): Promise<PortalContact[] | null> {
    try {
      const supabase = getSupabaseClient();
      const { data, error } = await supabase
        .from("client_portal_users")
        .select("id, client_id, email, name, status, invited_at")
        .eq("client_id", id)
        .order("created_at", { ascending: false });
      if (error) return null;
      return data as PortalContact[];
    } catch {
      return null;
    }
  }

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    async function load() {
      let clientFailed = false;
      const [c, contactsData] = await Promise.all([
        getClient(clientId).catch(() => { clientFailed = true; return null; }),
        loadContacts(clientId),
      ]);
      if (c) setClient(c);
      if (contactsData) {
        setContacts(contactsData);
      }
      setPageLoadError(
        clientFailed || contactsData === null
          ? "Couldn't load the client portal. Please try again."
          : null
      );
    }
    load();
  }, [clientId]);

  function handleOpenInvite() {
    setInviteEmail((client as (Client & { email?: string }) | null)?.email ?? "");
    setInviteSent(false);
    setInviteError(null);
    setShowInviteModal(true);
  }

  // F22 fix: invitations are now created server-side (audited, single-use,
  // expiring token — services/portal_access_service.py:invite_contact) instead
  // of a raw browser-side signInWithOtp + direct `clients` table write. The
  // Supabase magic link still performs the actual authentication; the token it
  // carries is what the client must separately, explicitly redeem (POST
  // /api/portal/accept-invite) to bind that identity to THIS ONE client — no
  // more auto-binding by email match.
  //
  // The link lands on /portal/activate (not /portal/dashboard directly) — that
  // page accepts the invite AND collects a password, so the client can sign
  // in any time afterward at /portal/login instead of needing a fresh email
  // link every visit.
  async function handleSendInvite() {
    if (!clientId || !inviteEmail.trim()) return;
    setLoading(true);
    setInviteError(null);
    try {
      const email = inviteEmail.trim();
      const res = await api.portal.inviteContact(clientId, { email });
      if (!res.success) throw new Error(res.error ?? "Failed to create the invite");
      const token = res.data.contact.invite_token;

      const supabase = getSupabaseClient();
      const portalUrl =
        (typeof window !== "undefined" ? window.location.origin : "") +
        "/portal/activate?invite=" + encodeURIComponent(token ?? "");
      const { error: otpErr } = await supabase.auth.signInWithOtp({
        email, options: { emailRedirectTo: portalUrl },
      });
      if (otpErr) throw new Error(otpErr.message);

      const refreshed = await loadContacts(clientId);
      if (refreshed) setContacts(refreshed);
      setInviteSent(true);

      try {
        const firmId = await getFirmId();
        await writeTimelineEvent({
          client_id: clientId,
          firm_id: firmId,
          financial_year: financialYear,
          category: "portal",
          event_type: "portal_invite_sent",
          severity: "info",
          title: "Portal invite sent",
          description: `Invite sent to ${email}`,
          actor_type: "user",
        });
      } catch { /* timeline is non-blocking */ }
    } catch (err) {
      setInviteError(err instanceof Error ? err.message : "Failed to send invite");
    } finally {
      setLoading(false);
    }
  }

  const portalUrl =
    typeof window !== "undefined" ? `${window.location.origin}/portal/login` : "/portal/login";

  const active = contacts.filter((c) => c.status === "active");
  const invited = contacts.filter((c) => c.status === "invited");
  const enabled = active.length > 0 || invited.length > 0;
  const mostRecentInvite = [...contacts].sort(
    (a, b) => new Date(b.invited_at ?? 0).getTime() - new Date(a.invited_at ?? 0).getTime()
  )[0];

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      {pageLoadError && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-2.5">
          <p className="text-xs text-red-700 font-medium">{pageLoadError}</p>
        </div>
      )}
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-6">
        <div className="flex items-start gap-3">
          <Globe className="w-5 h-5 text-blue-600 mt-0.5 shrink-0" />
          <div className="flex-1">
            <h2 className="text-sm font-semibold text-[#0F172A]">Client Portal</h2>
            <p className="text-xs text-[#64748B] mt-0.5">
              {enabled
                ? `${active.length} active, ${invited.length} pending · Last invited ${mostRecentInvite?.invited_at ? new Date(mostRecentInvite.invited_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : ""}`
                : "Not enabled — client cannot log in yet"}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span
              className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                enabled ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"
              }`}
            >
              {enabled ? "Active" : "Not enabled"}
            </span>
            <button
              onClick={handleOpenInvite}
              disabled={loading}
              className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {enabled ? "Invite Another Contact" : "Invite to Portal"}
            </button>
          </div>
        </div>

        {contacts.length > 0 && (
          <div className="mt-4 divide-y divide-[#F1F5F9] border border-[#F1F5F9] rounded-lg overflow-hidden">
            {contacts.map((c) => (
              <div key={c.id} className="px-4 py-2.5 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-xs font-medium text-[#0F172A] truncate">{c.name || c.email}</p>
                  {c.name && <p className="text-[11px] text-[#94A3B8] truncate">{c.email}</p>}
                </div>
                <span
                  className={`shrink-0 text-[11px] px-2 py-0.5 rounded-full font-medium ${
                    c.status === "active" ? "bg-green-100 text-green-700"
                      : c.status === "invited" ? "bg-amber-100 text-amber-700"
                      : "bg-[#F1F5F9] text-[#64748B]"
                  }`}
                >
                  {c.status}
                </span>
              </div>
            ))}
          </div>
        )}

        <div className="mt-4 bg-[#F8FAFC] rounded-lg px-4 py-3 flex items-center gap-3">
          <code className="text-xs text-[#475569] flex-1 break-all">{portalUrl}</code>
          <button
            onClick={() => navigator.clipboard.writeText(portalUrl)}
            className="shrink-0 text-[#94A3B8] hover:text-blue-600"
            title="Copy URL"
          >
            <Copy className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Invite Modal */}
      {showInviteModal && (
        <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-[#0F172A]">Invite to Portal</h3>
              <button onClick={() => setShowInviteModal(false)} className="text-[#94A3B8] hover:text-[#475569]">
                <X className="w-4 h-4" />
              </button>
            </div>

            {inviteSent ? (
              <div className="bg-green-50 border border-green-100 rounded-lg px-4 py-3">
                <p className="text-sm text-green-700 font-medium">Invite sent!</p>
                <p className="text-xs text-green-600 mt-0.5">
                  An invite has been sent to {inviteEmail}. They&apos;ll set a password and can sign in
                  any time afterward.
                </p>
              </div>
            ) : (
              <>
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1">Client email *</label>
                  <input
                    type="email"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    placeholder="client@example.com"
                    className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                {inviteError && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{inviteError}</p>}
                <div className="flex gap-3 justify-end">
                  <button
                    onClick={() => setShowInviteModal(false)}
                    className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSendInvite}
                    disabled={loading || !inviteEmail.trim()}
                    className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40"
                  >
                    {loading ? "Sending…" : "Send Invite"}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
