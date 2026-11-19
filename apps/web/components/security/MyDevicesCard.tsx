"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, MonitorSmartphone } from "lucide-react";
import { api, type DeviceSummary } from "@/lib/api/index";
import { objectWithLists } from "@/lib/api/shape";
import { getSupabaseClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { LoadingRegion } from "@/components/ui/skeleton";
import { DeviceList } from "@/components/security/DeviceList";

/**
 * Where the person is signed in, and the way to end every other session without ending this one (POST-A-486).
 *
 * The list and its sentence are the server's. "Sign out my other sessions" does two things in a fixed order: the API stops the other
 * sessions' tokens at once (a mark on the person's row that spares this session), then this browser asks the sign-in service to end
 * their refresh tokens as well. If the second fails the screen says so: the others can no longer open anything here, and the
 * sign-in service may still hold them until they expire.
 */
export function MyDevicesCard() {
  const [summary, setSummary] = useState<DeviceSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (): Promise<DeviceSummary | null> => {
    try {
      const res = await api.identity.myDevices();
      if (!res.success) { setError(res.error || "Your devices could not be read just now."); return null; }
      const next = objectWithLists<DeviceSummary>(res.data, "devices");
      if (!next) { setError("The server answered with something unreadable."); return null; }
      setError(null);
      setSummary(next);
      return next;
    } catch {
      setError("Your devices could not be read just now.");
      return null;
    }
  }, []);

  // Opening this card is itself a sighting: this session says it is here while the list is read, and if the first answer left this
  // device out (a session that predates the feature, or whose sign-in record failed) the list is read once more. A read writes
  // nothing, which is why the sighting is its own call. A failure of the sighting only leaves the device unlisted, which the card says.
  useEffect(() => {
    let live = true;
    void Promise.all([api.identity.sessionSeen().catch(() => undefined), load()]).then(([, first]) => {
      if (live && first && first.can_keep_this_session !== false && first.this_device_listed === false) void load();
    });
    return () => { live = false; };
  }, [load]);

  async function signOutOthers() {
    if (busy) return;
    if (!(await confirmDialog({
      message: "Sign out every other session of your login? This device stays signed in. Anywhere else you are signed in, you will have to sign in again.",
      confirmLabel: "Sign out the others",
      danger: true,
    }))) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      const res = await api.identity.signOutOtherSessions();
      if (!res.success) { setError(res.error || "The other sessions could not be signed out."); return; }
      setSummary(null); // a failed re-read below must not leave the list from before the sign-out under a "signed out" notice
      let service = "";
      try {
        const { error: serviceError } = await getSupabaseClient().auth.signOut({ scope: "others" });
        if (serviceError) service = " The sign-in service could not be asked to end them as well, so it may keep them until they expire. PracticeSync's own server refuses them from now on.";
      } catch {
        service = " The sign-in service could not be asked to end them as well, so it may keep them until they expire. PracticeSync's own server refuses them from now on.";
      }
      setNotice(`Your other sessions were signed out.${service}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The other sessions could not be signed out.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div id="devices" className="scroll-mt-16 bg-white rounded-xl border border-ps-border overflow-hidden">
      <div className="flex items-center gap-2.5 px-5 py-4 border-b border-ps-border">
        <MonitorSmartphone size={15} className="text-blue-600" />
        <h2 className="text-sm font-semibold text-ps-ink">Where you are signed in</h2>
      </div>
      <div className="px-5 py-4 space-y-3">
        {error && (
          <p role="alert" className="text-xs text-state-problem flex items-start gap-1.5">
            <AlertCircle size={13} className="mt-0.5 shrink-0" /> {error}
          </p>
        )}
        {notice && (
          <p role="status" className="text-xs text-state-ready flex items-start gap-1.5">
            <CheckCircle2 size={13} className="mt-0.5 shrink-0" /> {notice}
          </p>
        )}
        {!summary && !error && (
          <LoadingRegion label="Reading where you are signed in" className="text-sm text-ps-label">Reading where you are signed in…</LoadingRegion>
        )}
        {summary && (
          <>
            {summary.can_keep_this_session === false ? (
              <p className="text-sm font-medium text-ps-ink">
                This device cannot be listed: this sign-in does not say which session it is.{" "}
                {summary.count > 0 ? `PracticeSync knows of ${summary.count} other ${summary.count === 1 ? "session" : "sessions"} on your login.` : "PracticeSync knows of no other session on your login."}
              </p>
            ) : (
              <p className="text-sm font-medium text-ps-ink">{summary.sentence}</p>
            )}
            {summary.can_keep_this_session !== false && summary.this_device_listed === false && (
              <p className="text-xs text-ps-label">This device is not recorded yet; it will be after a few minutes of use. The count above leaves it out.</p>
            )}
            {summary.devices.length > 0 && <DeviceList devices={summary.devices} />}
            <p className="text-xs text-ps-label">
              This lists the sessions PracticeSync has heard from in the last {summary.window_minutes} minutes, so a browser that was just closed
              can still be listed for a while. A session that has been quiet for longer is not listed but may still be signed in until you
              sign out of it or end it below. Each browser counts once: two browsers on one computer are two. Sessions are told apart by their
              sign-in, so a copy of this very session (a stolen sign-in) is not shown as another device; if you think that has happened, sign
              out here, sign in again and press the button below from the new session.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="plain" size="none" onClick={signOutOthers} disabled={busy || summary.can_keep_this_session === false}
                className="inline-flex items-center gap-1.5 rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-state-problem-hover disabled:opacity-60"
              >
                {busy ? <Loader2 size={13} className="animate-spin" /> : null} Sign out my other sessions
              </Button>
              {summary.can_keep_this_session === false && (
                <span className="text-xs text-ps-label">This sign-in does not say which session it is. Sign in again to use this.</span>
              )}
            </div>
          </>
        )}
        <p className="text-xs text-ps-label">
          PracticeSync records the address and the browser you sign in from and keeps them with your sign-in history, which your firm&apos;s
          Partners and Managers can read. Nothing limits how many devices one login can be used on; the firm&apos;s other Partners are told in the app
          when a second one signs in.
        </p>
      </div>
    </div>
  );
}
