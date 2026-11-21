"use client";

/**
 * THE TWO READS BEHIND THE TEAM-AND-PAYROLL LIST (POST-A-540): the firm's own payroll roster and the Team list.
 *
 * A Partner's alone, so the hook asks only when it is told to (`enabled`); the server refuses anybody else whatever a screen
 * does. Three answers a screen must keep apart: still reading, could not be read (said in words, never drawn as an empty
 * payroll), and read. A later read (after a link is written) keeps what is on the screen until the new answer arrives.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { failureSentence } from "@/lib/api/failureSentence";
import { arrayOrEmpty, objectOrNull } from "@/lib/api/shape";
import { readStaffRoster, type StaffMember, type StaffRoster } from "@/lib/payroll/staffLinks";

export type StaffLinks =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "unread"; problem: string }
  | { state: "ready"; roster: StaffRoster; members: StaffMember[] };

const UNREAD = "The firm's own payroll could not be read, so this list cannot say who is on it.";

export function useStaffLinks(enabled: boolean): { links: StaffLinks; reload: () => void } {
  const [links, setLinks] = useState<StaffLinks>({ state: "idle" });
  const [turn, setTurn] = useState(0);
  const latest = useRef(0);
  const reload = useCallback(() => setTurn((n) => n + 1), []);

  useEffect(() => {
    if (!enabled) { setLinks({ state: "idle" }); return; }
    const mine = ++latest.current;
    setLinks((was) => (was.state === "ready" ? was : { state: "loading" }));
    Promise.all([api.payroll.practiceStaff(), api.identity.listUsers()])
      .then(([rosterRes, usersRes]) => {
        if (mine !== latest.current) return;
        const roster = readStaffRoster(rosterRes);
        const users = usersRes.success ? objectOrNull<{ users?: unknown }>(usersRes.data)?.users : null;
        if (!roster || !Array.isArray(users)) { setLinks({ state: "unread", problem: UNREAD }); return; }
        const members: StaffMember[] = arrayOrEmpty<{ id: string; full_name?: string; email?: string; role?: string; member_state?: string }>(users)
          .filter((u) => typeof u?.id === "string")
          .map((u) => ({ id: u.id, full_name: u.full_name ?? u.email ?? "", email: u.email ?? "", role: u.role, member_state: u.member_state }));
        setLinks({ state: "ready", roster, members });
      })
      .catch((e) => { if (mine === latest.current) setLinks({ state: "unread", problem: failureSentence(e, UNREAD, "read") }); });
  }, [enabled, turn]);

  return { links, reload };
}
