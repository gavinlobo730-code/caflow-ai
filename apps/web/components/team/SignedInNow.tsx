"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Loader2, LogOut, MonitorSmartphone } from "lucide-react";
import { api, type FirmDeviceMember } from "@/lib/api/index";
import { objectWithLists } from "@/lib/api/shape";
import { Button } from "@/components/ui/button";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { LoadingRegion, SkeletonText } from "@/components/ui/skeleton";
import { DeviceList } from "@/components/security/DeviceList";

/**
 * Who in the firm is signed in on which devices right now (POST-A-486), for a Partner or a Manager. A member on more than one device
 * is marked, because that is what the owner asked to be told: it is not an accusation (an office computer and a phone is ordinary),
 * it is the thing to look at. A Partner can end a member's sessions from here with the existing sign-out, which ends every session of
 * theirs; a Partner's own sessions are ended from their Security page, where "this one" can be kept.
 */
export function SignedInNow({ canEnd }: { canEnd: boolean }) {
  const [members, setMembers] = useState<FirmDeviceMember[] | null>(null);
  const [minutes, setMinutes] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.identity.firmDevices();
      if (!res.success) { setError(res.error || "Who is signed in could not be read just now."); return; }
      const data = res.data as { members?: unknown; live_window_minutes?: number } | null;
      const body = objectWithLists<{ members: FirmDeviceMember[]; live_window_minutes?: number }>(data, "members");
      if (!body) { setError("The server answered with something unreadable."); return; }
      setError(null);
      setMembers(body.members);
      setMinutes(typeof body.live_window_minutes === "number" ? body.live_window_minutes : null);
    } catch {
      setError("Who is signed in could not be read just now.");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function signOut(member: FirmDeviceMember) {
    if (busyId) return;
    if (!(await confirmDialog({
      message: `Sign ${member.name || "this member"} out of PracticeSync everywhere? Every session of theirs stops working here, and they must sign in again.`,
      confirmLabel: "Sign them out",
      danger: true,
    }))) return;
    setBusyId(member.user_id); setError(null); setNotice(null);
    try {
      const res = await api.identity.forceLogout(member.user_id) as { success?: boolean; error?: string | null };
      if (res && res.success === false) { setError(res.error || "They could not be signed out."); return; }
      setNotice(`${member.name || "The member"} was signed out of PracticeSync everywhere.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "They could not be signed out.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section aria-label="Signed in now" className="mb-5 bg-white border border-ps-border rounded-xl overflow-hidden" data-signed-in-now="">
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-ps-border">
        <MonitorSmartphone size={15} className="text-brand" />
        <h2 className="text-sm font-semibold text-ps-ink">Signed in now</h2>
      </div>
      <div className="px-4 py-3 space-y-3">
        {error && (
          <p role="alert" className="text-xs text-state-problem flex items-start gap-1.5"><AlertCircle size={13} className="mt-0.5 shrink-0" /> {error}</p>
        )}
        {notice && <p role="status" className="text-xs text-state-ready">{notice}</p>}
        {!members && !error && (
          <LoadingRegion label="Reading who is signed in"><SkeletonText lines={3} /></LoadingRegion>
        )}
        {members && members.length === 0 && (
          <p className="text-xs text-ps-hint">Nobody has been heard from in the last {minutes ?? "few"} minutes.</p>
        )}
        {members && members.map((m) => (
          <div key={m.user_id} className="rounded-lg border border-ps-border px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0 text-sm">
                <span className="font-medium text-ps-ink">{m.name || "A member"}{m.is_you ? " (you)" : ""}</span>
                <span className="text-ps-label"> · {m.sentence}</span>
                {m.more_than_one && (
                  <span className="ml-2 rounded-full bg-state-attention-surface px-2 py-0.5 text-xs font-medium text-state-attention">More than one device</span>
                )}
              </div>
              {canEnd && !m.is_you && (
                <Button
                  variant="plain" size="none" onClick={() => signOut(m)} disabled={busyId !== null}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-red-300 px-2.5 py-1 text-xs text-red-600 hover:bg-state-problem-hover disabled:opacity-60"
                >
                  {busyId === m.user_id ? <Loader2 size={12} className="animate-spin" /> : <LogOut size={12} />} Sign out everywhere
                </Button>
              )}
            </div>
            <DeviceList devices={m.devices} />
          </div>
        ))}
        {members && (
          <p className="text-xs text-ps-label">
            Lists the sessions PracticeSync has heard from in the last {minutes ?? "few"} minutes; each browser counts once. The address is the one our own
            server saw; it does not say where the person is. The address and browser a person signs in from are kept with the sign-in history below.
          </p>
        )}
      </div>
    </section>
  );
}
