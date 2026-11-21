"use client";

/**
 * TEAM SIGN-INS AND THE FIRM'S OWN PAYROLL, SIDE BY SIDE (POST-A-540).
 *
 * A member of the firm's staff is two records: a sign-in on the Team screen and, if the firm pays them here, an employee in
 * the firm's own payroll (My practice, Payroll). This panel is the one place that shows both, on the Team screen and on the
 * practice's Payroll page, and offers each from the other:
 *
 *   a sign-in with no payroll record   Add to payroll (the one employee form, with the name started from the sign-in),
 *                                      or link to a payroll record that is already there;
 *   a payroll record with no sign-in   Invite to Team (the server mails the invitation), or link to a sign-in already there;
 *   a linked pair                      both names, a word when they are spelt differently, and Remove link.
 *
 * A LINK, NEVER A MERGE. Nothing here copies one record into the other, and removing a link removes neither.
 *
 * A PARTNER'S ALONE. The firm's own payroll is (guardrail G4), so the host draws this panel for a Partner only and the
 * server refuses the reads to anybody else. The screen decides nothing: who may be linked to whom is the server's rule, and
 * its refusal is shown in its own words.
 */
import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { failureSentence } from "@/lib/api/failureSentence";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { SectionPlaceholder } from "@/components/ui/page-frame";
import { AddEmployeeModal } from "@/components/payroll/AddEmployeeModal";
import type { StaffLinks } from "@/lib/payroll/useStaffLinks";
import { staffRows, unlinked, type RosterEmployee, type StaffMember, type StaffRow } from "@/lib/payroll/staffLinks";

/** The roles a new sign-in may be given, as the Team screen's own invitation offers them. */
const INVITE_ROLES = ["Partner", "Manager", "Executive", "Reviewer"] as const;

type Notice = { tone: "done" | "problem"; text: string };

export function StaffLinksPanel({ links, side, onChanged }: {
  links: StaffLinks;
  /** Which screen is showing it: only the sentence under the heading and the link to the other screen differ. */
  side: "team" | "payroll";
  /** Called after anything is written, so the host reads its own list (and this panel's) again. */
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [adding, setAdding] = useState<StaffMember | null>(null);
  const [inviting, setInviting] = useState<RosterEmployee | null>(null);

  if (links.state === "idle") return null;
  if (links.state === "loading") {
    return side === "team" ? null : <SectionPlaceholder label="Reading the team sign-ins" shape="list" rows={2} className="mb-4" />;
  }
  if (links.state === "unread") {
    return (
      <section data-staff-links="unread" className="bg-white rounded-xl border border-ps-border p-4 mb-4">
        <h2 className="text-sm font-semibold text-ps-ink">Team sign-ins and the firm&apos;s own payroll</h2>
        <p role="alert" className="text-xs text-state-problem mt-1">{links.problem}</p>
      </section>
    );
  }

  const { roster, members } = links;
  // A firm that keeps no books of its own, or has never run its own payroll here, is shown nothing: there is no second record.
  if (!roster.practice_client_id) return null;
  if (roster.employees.length === 0 && roster.payroll_enabled !== true) return null;

  const rows = staffRows(roster, members);
  const free = unlinked(roster, members);
  const practiceId = roster.practice_client_id;
  const mayAdd = roster.payroll_enabled === true;

  async function write(key: string, action: () => Promise<unknown>, done: string, failed: string) {
    if (busy) return;
    setBusy(key);
    setNotice(null);
    try {
      const res = await action();
      const body = res as { success?: boolean; error?: string | null } | null;
      if (body && body.success === false) { setNotice({ tone: "problem", text: body.error ?? failed }); return; }
      setNotice({ tone: "done", text: done });
      setChoice({});
      onChanged();
    } catch (e) {
      setNotice({ tone: "problem", text: failureSentence(e, failed, "write") });
    } finally {
      setBusy(null);
    }
  }

  async function removeLink(row: Extract<StaffRow, { kind: "linked" | "member-gone" }>) {
    const who = row.kind === "linked" ? `${row.member.full_name}'s sign-in` : "a sign-in that is no longer on the Team list";
    if (!(await confirmDialog({
      message: `Remove the link between ${who} and the payroll record of ${row.employee.name}?\n\nNeither record is changed or removed. ` +
        "They are only no longer shown as one person.",
    }))) return;
    await write(`unlink:${row.employee.id}`, () => api.payroll.linkStaff(row.employee.id, null),
      `The link to the payroll record of ${row.employee.name} is removed. Both records are as they were.`,
      "The link was not removed.");
  }

  const linkTo = (employee: RosterEmployee, member: StaffMember, key: string) =>
    write(key, () => api.payroll.linkStaff(employee.id, member.id),
      `${member.full_name}'s sign-in is linked to the payroll record of ${employee.name}.`, "The link was not recorded.");

  const cell = "px-4 py-2.5 align-top";
  const small = "text-2xs px-2 py-1 border border-ps-border rounded-lg text-ps-body hover:bg-ps-muted disabled:opacity-50";

  return (
    <section data-staff-links="ready" className="bg-white rounded-xl border border-ps-border overflow-hidden mb-4">
      <div className="px-4 py-3 border-b border-ps-border">
        <h2 className="text-sm font-semibold text-ps-ink">Team sign-ins and the firm&apos;s own payroll</h2>
        <p className="text-xs text-ps-label mt-0.5">
          A person who works here can have two records: a sign-in on Team and an employee record in the firm&apos;s own payroll.
          They are kept separate and linked here, so each shows that the other exists. Only a Partner sees this list.{" "}
          {side === "team"
            ? <Link href={`/clients/${practiceId}/payroll/`} className="text-brand hover:underline">Open the firm&apos;s payroll</Link>
            : <Link href="/team/" className="text-brand hover:underline">Open Team</Link>}
        </p>
        {roster.payroll_enabled === false && (
          <p data-payroll-off className="text-xs text-ps-label mt-1">
            Payroll is switched off for the practice, so nobody can be added to it from here. A link can still be recorded or removed.
          </p>
        )}
        {roster.payroll_enabled === null && (
          <p data-payroll-unknown className="text-xs text-ps-label mt-1">
            Whether payroll is switched on for the practice could not be read, so adding somebody to it is not offered here.
          </p>
        )}
        {notice && (
          <p role={notice.tone === "problem" ? "alert" : "status"} data-staff-notice={notice.tone}
            className={`text-xs mt-2 ${notice.tone === "problem" ? "text-state-problem" : "text-state-ready"}`}>
            {notice.text}
          </p>
        )}
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-ps-border bg-ps-bg">
            {["Team sign-in", "Payroll record", ""].map((h, i) => (
              <th key={i} className="px-4 py-2 text-left text-3xs font-semibold uppercase tracking-wider text-ps-hint">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-ps-border">
          {rows.map((row) => {
            if (row.kind === "linked") {
              return (
                <tr key={`l:${row.employee.id}`} data-staff-row="linked">
                  <td className={cell}>
                    <p className="font-medium text-ps-ink">{row.member.full_name}</p>
                    <p className="text-2xs text-ps-hint">{row.member.email}</p>
                  </td>
                  <td className={cell}>
                    <p className="text-ps-ink">{row.employee.name}{row.employee.employee_code ? ` (${row.employee.employee_code})` : ""}</p>
                    {row.namesDiffer && (
                      <p data-names-differ className="text-2xs text-ps-label">The name is spelt differently on the two records. Neither is changed from here.</p>
                    )}
                    {row.employee.status && row.employee.status !== "active" && <p className="text-2xs text-ps-label">Payroll status: {row.employee.status}</p>}
                  </td>
                  <td className={`${cell} text-right`}>
                    <Button variant="plain" size="none" className={small} disabled={busy !== null} onClick={() => removeLink(row)}>Remove link</Button>
                  </td>
                </tr>
              );
            }
            if (row.kind === "member-gone") {
              return (
                <tr key={`g:${row.employee.id}`} data-staff-row="member-gone">
                  <td className={cell}><p className="text-ps-label">A sign-in that is no longer on the Team list</p></td>
                  <td className={cell}><p className="text-ps-ink">{row.employee.name}</p></td>
                  <td className={`${cell} text-right`}>
                    <Button variant="plain" size="none" className={small} disabled={busy !== null} onClick={() => removeLink(row)}>Remove link</Button>
                  </td>
                </tr>
              );
            }
            if (row.kind === "member-only") {
              const key = `m:${row.member.id}`;
              const picked = free.employees.find((e) => e.id === choice[key]);
              return (
                <tr key={key} data-staff-row="member-only">
                  <td className={cell}>
                    <p className="font-medium text-ps-ink">{row.member.full_name}</p>
                    <p className="text-2xs text-ps-hint">{row.member.email}</p>
                  </td>
                  <td className={cell}><p className="text-ps-label">Not in the firm&apos;s payroll</p></td>
                  <td className={`${cell} text-right`}>
                    <div className="flex flex-wrap justify-end items-center gap-1.5">
                      {mayAdd && (
                        <button type="button" className={small} disabled={busy !== null} onClick={() => { setNotice(null); setAdding(row.member); }}>
                          Add to payroll
                        </button>
                      )}
                      {free.employees.length > 0 && (
                        <>
                          <select aria-label={`A payroll record to link to ${row.member.full_name}`} value={choice[key] ?? ""}
                            onChange={(e) => setChoice((c) => ({ ...c, [key]: e.target.value }))}
                            className="text-2xs border border-ps-border rounded-lg px-1.5 py-1 max-w-[11rem]">
                            <option value="">Link to a payroll record…</option>
                            {free.employees.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
                          </select>
                          <Button variant="plain" size="none" className={small} disabled={busy !== null || !picked}
                            onClick={() => (picked ? linkTo(picked, row.member, key) : undefined)}>Link</Button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              );
            }
            const key = `e:${row.employee.id}`;
            const picked = free.members.find((m) => m.id === choice[key]);
            return (
              <tr key={key} data-staff-row="employee-only">
                <td className={cell}><p className="text-ps-label">No sign-in on Team</p></td>
                <td className={cell}>
                  <p className="text-ps-ink">{row.employee.name}{row.employee.employee_code ? ` (${row.employee.employee_code})` : ""}</p>
                  {row.employee.status && row.employee.status !== "active" && <p className="text-2xs text-ps-label">Payroll status: {row.employee.status}</p>}
                </td>
                <td className={`${cell} text-right`}>
                  <div className="flex flex-wrap justify-end items-center gap-1.5">
                    <button type="button" className={small} disabled={busy !== null} onClick={() => { setNotice(null); setInviting(row.employee); }}>
                      Invite to Team
                    </button>
                    {free.members.length > 0 && (
                      <>
                        <select aria-label={`A team sign-in to link to ${row.employee.name}`} value={choice[key] ?? ""}
                          onChange={(e) => setChoice((c) => ({ ...c, [key]: e.target.value }))}
                          className="text-2xs border border-ps-border rounded-lg px-1.5 py-1 max-w-[11rem]">
                          <option value="">Link to a sign-in…</option>
                          {free.members.map((m) => <option key={m.id} value={m.id}>{m.full_name}</option>)}
                        </select>
                        <Button variant="plain" size="none" className={small} disabled={busy !== null || !picked}
                          onClick={() => (picked ? linkTo(row.employee, picked, key) : undefined)}>Link</Button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {adding && (
        <AddEmployeeModal
          clients={[{ id: practiceId, client_name: "The firm's own payroll" }]}
          lockedClientId={practiceId}
          teamMember={{ id: adding.id, name: adding.full_name }}
          onClose={() => setAdding(null)}
          onSaved={() => {
            setNotice({ tone: "done", text: `${adding.full_name} is added to the firm's own payroll, linked to their sign-in.` });
            setAdding(null);
            onChanged();
          }}
        />
      )}
      {inviting && (
        <InviteEmployeeModal
          employee={inviting}
          onClose={() => setInviting(null)}
          onDone={(text, tone) => { setNotice({ tone, text }); setInviting(null); onChanged(); }}
        />
      )}
    </section>
  );
}

/** Invite somebody who is already in the firm's payroll to Team, and link the new sign-in to their payroll record. Two
 *  requests, in that order, and the second's failure is said as what it is: the invitation went and the link did not. */
function InviteEmployeeModal({ employee, onClose, onDone }: {
  employee: RosterEmployee;
  onClose: () => void;
  onDone: (text: string, tone: "done" | "problem") => void;
}) {
  const [name, setName] = useState(employee.name);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<(typeof INVITE_ROLES)[number]>("Executive");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (saving || !name.trim() || !email.trim()) return;
    setSaving(true);
    setError(null);
    let invited: { id: string; mailProblem: string | null } | null = null;
    try {
      const created = await api.identity.createUser(name.trim(), email.trim(), role);
      if (!created.success || !created.data) { setError(created.error ?? "The invitation could not be created."); return; }
      const mail = created.data.invite_mail;
      invited = { id: created.data.id, mailProblem: mail?.sent === true ? null : (mail?.problem ?? "The server did not say whether the email went.") };
    } catch (err) {
      setError(failureSentence(err, "The invitation could not be created.", "write"));
      return;
    } finally {
      if (!invited) setSaving(false);
    }
    const mailed = invited.mailProblem
      ? `${name.trim()} is on the Team list, but the invitation email did not go: ${invited.mailProblem} Send it again from Team.`
      : `${name.trim()} is invited to Team at ${email.trim()}.`;
    try {
      const linked = await api.payroll.linkStaff(employee.id, invited.id) as { success?: boolean; error?: string | null } | null;
      if (linked && linked.success === false) {
        onDone(`${mailed} The link to the payroll record was not recorded: ${linked.error ?? "the server refused it."} Link them from this list.`, "problem");
        return;
      }
      onDone(`${mailed} The sign-in is linked to the payroll record of ${employee.name}.`, invited.mailProblem ? "problem" : "done");
    } catch (err) {
      onDone(`${mailed} The link to the payroll record was not recorded: ${failureSentence(err, "the request failed.", "write")} Link them from this list.`, "problem");
    } finally {
      setSaving(false);
    }
  }

  const box = "w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand";
  return (
    <Modal title="Invite to Team" onClose={() => { if (!saving) onClose(); }}>
      <p className="text-xs text-ps-label mb-3">
        {employee.name} is in the firm&apos;s own payroll and has no sign-in. This sends them an invitation and links the new sign-in to
        their payroll record. The payroll record is not changed.
      </p>
      {error && <p role="alert" className="text-xs text-state-problem mb-2">{error}</p>}
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="text-xs font-medium text-ps-body block mb-1" htmlFor="invite-employee-name">Full Name</label>
          <input id="invite-employee-name" className={box} value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <div>
          <label className="text-xs font-medium text-ps-body block mb-1" htmlFor="invite-employee-email">Email Address</label>
          <input id="invite-employee-email" type="email" className={box} value={email} onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <div>
          <label className="text-xs font-medium text-ps-body block mb-1" htmlFor="invite-employee-role">Role</label>
          <select id="invite-employee-role" className={box} value={role} onChange={(e) => setRole(e.target.value as (typeof INVITE_ROLES)[number])}>
            {INVITE_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div className="flex gap-2 pt-2">
          <button type="button" onClick={onClose} disabled={saving}
            className="flex-1 border border-ps-border text-ps-label text-sm py-2 rounded-lg hover:bg-ps-bg disabled:opacity-50">Cancel</button>
          <button type="submit" disabled={saving || !name.trim() || !email.trim()}
            className="flex-1 bg-brand text-white text-sm py-2 rounded-lg hover:bg-brand-dark disabled:opacity-50">
            {saving ? "Sending…" : "Send invitation and link"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
