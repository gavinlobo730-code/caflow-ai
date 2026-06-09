"use client";

import { useEffect, useState } from "react";
import { Globe, Copy, X } from "lucide-react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getClient } from "@/lib/data/clients";
import type { Client } from "@/lib/types";

interface PortalState {
  enabled: boolean;
  invitedAt: string | null;
}

export default function PortalPage() {
  const { clientId } = useClientNav();
  const [client, setClient] = useState<Client | null>(null);
  const [portal, setPortal] = useState<PortalState | null>(null);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteSent, setInviteSent] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    async function load() {
      const [c] = await Promise.all([getClient(clientId).catch(() => null)]);
      if (c) setClient(c);

      const supabase = getSupabaseClient();
      const { data } = await supabase
        .from("clients")
        .select("portal_enabled, portal_invited_at")
        .eq("id", clientId)
        .maybeSingle();
      if (data) setPortal({ enabled: !!data.portal_enabled, invitedAt: data.portal_invited_at ?? null });
    }
    load();
  }, [clientId]);

  function handleOpenInvite() {
    setInviteEmail((client as (Client & { email?: string }) | null)?.email ?? "");
    setInviteSent(false);
    setInviteError(null);
    setShowInviteModal(true);
  }

  async function handleSendInvite() {
    if (!clientId || !inviteEmail.trim()) return;
    setLoading(true);
    setInviteError(null);
    try {
      const supabase = getSupabaseClient();
      const portalUrl =
        (typeof window !== "undefined" ? window.location.origin : "") +
        "/portal?client=" +
        encodeURIComponent(clientId);
      const { error: otpErr } = await supabase.auth.signInWithOtp({
        email: inviteEmail.trim(),
        options: { emailRedirectTo: portalUrl },
      });
      if (otpErr) throw new Error(otpErr.message);
      await supabase
        .from("clients")
        .update({ portal_enabled: true, portal_invited_at: new Date().toISOString() })
        .eq("id", clientId);
      setPortal({ enabled: true, invitedAt: new Date().toISOString() });
      setInviteSent(true);
    } catch (err) {
      setInviteError(err instanceof Error ? err.message : "Failed to send invite");
    } finally {
      setLoading(false);
    }
  }

  const portalUrl =
    typeof window !== "undefined" ? `${window.location.origin}/portal` : "/portal";

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      <div className="bg-white rounded-xl border border-gray-100 p-6">
        <div className="flex items-start gap-3">
          <Globe className="w-5 h-5 text-blue-600 mt-0.5 shrink-0" />
          <div className="flex-1">
            <h2 className="text-sm font-semibold text-gray-900">Client Portal</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {portal?.enabled
                ? `Active · Invited ${portal.invitedAt ? new Date(portal.invitedAt).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : ""}`
                : "Not enabled — client cannot log in yet"}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span
              className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                portal?.enabled ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
              }`}
            >
              {portal?.enabled ? "Active" : "Not enabled"}
            </span>
            <button
              onClick={handleOpenInvite}
              disabled={loading}
              className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {portal?.enabled ? "Resend Invite" : "Invite to Portal"}
            </button>
          </div>
        </div>

        <div className="mt-4 bg-gray-50 rounded-lg px-4 py-3 flex items-center gap-3">
          <code className="text-xs text-gray-600 flex-1 break-all">{portalUrl}</code>
          <button
            onClick={() => navigator.clipboard.writeText(portalUrl)}
            className="shrink-0 text-gray-400 hover:text-blue-600"
            title="Copy URL"
          >
            <Copy className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Invite Modal */}
      {showInviteModal && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-900">Invite to Portal</h3>
              <button onClick={() => setShowInviteModal(false)} className="text-gray-400 hover:text-gray-600">
                <X className="w-4 h-4" />
              </button>
            </div>

            {inviteSent ? (
              <div className="bg-green-50 border border-green-100 rounded-lg px-4 py-3">
                <p className="text-sm text-green-700 font-medium">Invite sent!</p>
                <p className="text-xs text-green-600 mt-0.5">
                  A magic link has been sent to {inviteEmail}. The client can use it to log in.
                </p>
              </div>
            ) : (
              <>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Client email *</label>
                  <input
                    type="email"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    placeholder="client@example.com"
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                {inviteError && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{inviteError}</p>}
                <div className="flex gap-3 justify-end">
                  <button
                    onClick={() => setShowInviteModal(false)}
                    className="text-xs px-4 py-2 border border-gray-200 rounded-lg hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSendInvite}
                    disabled={loading || !inviteEmail.trim()}
                    className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40"
                  >
                    {loading ? "Sending…" : "Send Magic Link"}
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
