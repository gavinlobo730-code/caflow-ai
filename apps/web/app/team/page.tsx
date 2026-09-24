"use client";

import { useState, useEffect, useCallback } from "react";
import { arrayOrEmpty, objectOrNull } from "@/lib/api/shape";
import { Users, UserPlus, Shield, Mail, MoreVertical, X, AlertCircle, Lock, SlidersHorizontal } from "lucide-react";
import MemberAccessDrawer from "@/components/team/MemberAccessDrawer";
import { getSupabaseClient } from "@/lib/supabase/client";
import { api } from "@/lib/api";

// Module 9.0 / M1 — canonical staff roles (single source of truth = backend Role enum).
// Client is external (uses the portal) and is not a team member here.
type Role = "Partner" | "Manager" | "Executive" | "Reviewer";

// The modules this screen names, and the backend resource each one IS.
//
// A LABEL, NOT A MATRIX. What each role can reach comes from
// GET /api/identity/role-matrix, served straight out of core/permissions.py's
// PERMISSIONS. This file used to hold its own ROLE_DEFAULTS — eleven modules
// by four roles, "mirrors permissions.ts logic" said the comment — and it had
// drifted in the direction that matters most: it showed an Executive as having
// Clients and Tasks only, when the backend grants them Accounting, GST, Income
// Tax, MCA, Reports and TDS too, and it showed a Manager with Billing they do
// not have and without the Reports and Settings they do.
const MODULES: { label: string; resource: string }[] = [
  { label: "Accounting", resource: "accounting" },
  { label: "GST", resource: "gst" },
  { label: "Income Tax", resource: "income_tax" },
  { label: "TDS", resource: "tds" },
  { label: "MCA", resource: "mca" },
  { label: "Payroll", resource: "payroll" },
  { label: "Billing", resource: "billing" },
  { label: "Reports", resource: "report" },
  { label: "Settings", resource: "settings" },
  { label: "Clients", resource: "client" },
  { label: "Tasks", resource: "task" },
];

/** The served matrix: role → resource → the actions that role may take. */
type RoleMatrix = Record<string, Record<string, string[]>>;

/** Whether `role` may reach `resource` at all, per the server. */
function roleReaches(matrix: RoleMatrix, role: string, resource: string): boolean {
  return (matrix[role]?.[resource]?.length ?? 0) > 0;
}

/**
 * The per-member override store, kept ONLY to clear it.
 *
 * This screen used to write a member→module→boolean map into
 * localStorage["practicesync_permissions_<firm>"] and render it as an access
 * matrix whose header read "Toggle access per member per module. Changes are
 * saved instantly. Overrides the role default for that individual."
 *
 * Every clause of that was false. The map reached no other user, no other
 * device and no server; `core/permissions.py` has no per-member override
 * concept, so nothing could have honoured it; and `rbac()` decides every
 * request from the ROLE alone. A Partner who unticked Payroll for an Executive
 * believed they had removed access. They had not, anywhere.
 *
 * The grid is REAL now — migration 403 gave `rbac()` a per-person answer and
 * `user_permissions` stores it, so a tick reaches the server, every other
 * device and every request. What survives from the read-only era is this
 * purge: the browser-local map is still cleared on load, because a member it
 * marks "custom" was never restricted anywhere, and carrying it forward into a
 * screen that now MEANS something would silently reassert a decision the firm
 * made against a control that did nothing. It is deliberately not migrated
 * into `user_permissions` for the same reason — nobody can tell, at this
 * distance, which of those ticks was a real intention and which was somebody
 * finding out what the control did.
 */
const LEGACY_OVERRIDE_KEY = (firmId: string) => `practicesync_permissions_${firmId}`;

function purgeLegacyOverrides(firmId: string): void {
  if (typeof window === "undefined") return;
  try { localStorage.removeItem(LEGACY_OVERRIDE_KEY(firmId)); } catch { /* private window */ }
}

interface TeamMember {
  id: string;
  full_name: string;
  email: string;
  role: Role;
  is_active?: boolean;
  created_at?: string;
  auth_user_id?: string;
  firm_id?: string;
}

const ROLES: Role[] = ["Partner", "Manager", "Executive", "Reviewer"];

const ROLE_COLORS: Record<Role, string> = {
  Partner: "bg-purple-100 text-purple-700",
  Manager: "bg-blue-100 text-blue-700",
  Executive: "bg-state-attention-border text-state-attention",
  Reviewer: "bg-ps-muted text-ps-label",
};

// ---- Invite Modal ----
interface InviteModalProps {
  onClose: () => void;
  onInvite: (name: string, email: string, role: Role) => Promise<void>;
}

function InviteModal({ onClose, onInvite }: InviteModalProps) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("Executive");
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !email.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await onInvite(name.trim(), email.trim(), role);
      setSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send invitation");
    } finally {
      setSaving(false);
    }
  }

  if (success) {
    return (
      <div className="fixed inset-0 bg-ps-ink/60 z-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4 text-center">
          <div className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center mx-auto">
            <Mail className="w-6 h-6 text-green-600" />
          </div>
          <h3 className="text-sm font-semibold text-ps-ink">Invitation Sent</h3>
          <p className="text-xs text-ps-label">
            Invite sent! {name} will receive a magic link at {email}. They&apos;ll be added as {role}.
          </p>
          <button onClick={onClose} className="w-full bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700">
            Done
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-ps-ink/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ps-ink">Invite Team Member</h3>
          <button onClick={onClose} className="text-ps-hint hover:text-ps-label"><X className="w-4 h-4" /></button>
        </div>

        {error && (
          <div role="alert" className="bg-state-problem-surface border border-red-100 rounded-lg px-3 py-2 flex gap-2 text-xs text-money-out">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="text-xs font-medium text-ps-body block mb-1">Full Name</label>
            <input
              className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
              placeholder="e.g. Priya Sharma"
              value={name}
              onChange={e => setName(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="text-xs font-medium text-ps-body block mb-1">Email Address</label>
            <input
              type="email"
              className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
              placeholder="priya@firm.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="text-xs font-medium text-ps-body block mb-1">Role</label>
            <select
              className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
              value={role}
              onChange={e => setRole(e.target.value as Role)}
            >
              {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose} className="flex-1 border border-ps-border text-ps-label text-sm py-2 rounded-lg hover:bg-ps-bg">
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving || !name.trim() || !email.trim()}
              className="flex-1 bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Send Invitation"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---- Edit Role Modal ----
interface EditRoleModalProps {
  member: TeamMember;
  onClose: () => void;
  onSave: (id: string, role: Role) => Promise<void>;
}

function EditRoleModal({ member, onClose, onSave }: EditRoleModalProps) {
  const [role, setRole] = useState<Role>(member.role);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await onSave(member.id, role);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update role");
    } finally {
      // The success path relied on onClose() unmounting this modal to retire
      // the flag. One release covers both exits and does not depend on that.
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-ps-ink/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ps-ink">Edit Role</h3>
          <button onClick={onClose} className="text-ps-hint hover:text-ps-label"><X className="w-4 h-4" /></button>
        </div>
        <p className="text-xs text-ps-label">{member.full_name} · {member.email}</p>

        {error && (
          <div role="alert" className="bg-state-problem-surface border border-red-100 rounded-lg px-3 py-2 flex gap-2 text-xs text-money-out">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <div>
          <label className="text-xs font-medium text-ps-body block mb-1">Role</label>
          <select
            className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
            value={role}
            onChange={e => setRole(e.target.value as Role)}
          >
            {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div className="flex gap-2 pt-2">
          <button onClick={onClose} className="flex-1 border border-ps-border text-ps-label text-sm py-2 rounded-lg hover:bg-ps-bg">Cancel</button>
          <button
            disabled={saving || role === member.role}
            onClick={handleSave}
            className="flex-1 bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---- Actions Dropdown ----
interface ActionsMenuProps {
  member: TeamMember;
  onEdit: () => void;
  onDeactivate: () => void;
}

function ActionsMenu({ member, onEdit, onDeactivate }: ActionsMenuProps) {
  const [open, setOpen] = useState(false);
  const isActive = member.is_active !== false;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="p-1 rounded hover:bg-ps-muted text-ps-hint hover:text-ps-label"
      >
        <MoreVertical className="w-4 h-4" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 mt-1 w-40 bg-white border border-ps-muted rounded-lg shadow-lg z-20 py-1">
            <button
              onClick={() => { setOpen(false); onEdit(); }}
              className="w-full text-left px-3 py-2 text-xs text-ps-body hover:bg-ps-bg flex items-center gap-2"
            >
              <Shield className="w-3.5 h-3.5" />
              Edit Role
            </button>
            <button
              onClick={() => { setOpen(false); onDeactivate(); }}
              className={`w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-ps-bg ${
                isActive ? "text-state-problem" : "text-green-600"
              }`}
            >
              <Users className="w-3.5 h-3.5" />
              {isActive ? "Deactivate" : "Activate"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ---- Role Permissions Info Card ----
//
// SERVED, like the matrix below it and for the same reason. This rendered
// ROLE_DEFAULTS, the browser's own copy of core/permissions.py, and told a
// Partner an Executive could reach Clients and Tasks only — when the backend
// grants them Accounting, GST, Income Tax, MCA, Reports and TDS besides. It
// also carried the line "Admins can override these per person in the matrix
// above", which described a capability that has never existed.
function RolePermissionsCard() {
  const [matrix, setMatrix] = useState<RoleMatrix | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.identity.roleMatrix()
      .then((r) => {
        if (cancelled) return;
        if (r.success && r.data) { setMatrix(r.data.matrix); setError(null); }
        else { setMatrix(null); setError(r.error ?? "Couldn't load role permissions."); }
      })
      .catch(() => { if (!cancelled) { setMatrix(null); setError("Couldn't load role permissions."); } });
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="bg-white rounded-xl border border-ps-muted p-5 space-y-4">
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-lg bg-violet-100 flex items-center justify-center">
          <Lock className="w-3.5 h-3.5 text-violet-600" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-ps-ink">Role Permissions</h3>
          <p className="text-xs text-ps-hint">
            Read from the server. Access is decided by role — there is no per-person override.
          </p>
        </div>
      </div>

      {error && <p className="text-xs text-state-problem">{error}</p>}
      {!matrix && !error && <p className="text-xs text-ps-hint">Loading…</p>}

      {matrix && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {ROLES.map(role => {
            const allowed = MODULES.filter(m => roleReaches(matrix, role, m.resource));
            const denied = MODULES.filter(m => !roleReaches(matrix, role, m.resource));
            return (
              <div key={role} className="border border-ps-muted rounded-lg p-3 space-y-2">
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ROLE_COLORS[role]}`}>
                  {role}
                </span>
                <div className="space-y-1">
                  {allowed.map(m => (
                    <div key={m.resource} className="flex items-center gap-1.5 text-xs text-money-in">
                      <span className="w-1.5 h-1.5 rounded-full bg-green-400 shrink-0" />
                      {m.label}
                    </div>
                  ))}
                  {denied.map(m => (
                    <div key={m.resource} className="flex items-center gap-1.5 text-xs text-ps-hint">
                      <span className="w-1.5 h-1.5 rounded-full bg-gray-200 shrink-0" />
                      {m.label}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---- Permissions Matrix Tab ----
interface PermissionsMatrixProps {
  members: TeamMember[];
  firmId: string;
}

function PermissionsMatrix({ members, firmId }: PermissionsMatrixProps) {
  // THE MATRIX IS SERVED, AND THE GRID IS READ-ONLY.
  //
  // It used to be a per-member toggle grid backed by localStorage, under a
  // header that read "Toggle access per member per module. Changes are saved
  // instantly. Overrides the role default for that individual." None of that
  // was true — see LEGACY_OVERRIDE_KEY at the top of this file. A control that
  // does nothing is the dead-control fault; one that does nothing while
  // looking like access control is worse, because a Partner acts on it.
  const [matrix, setMatrix] = useState<RoleMatrix | null>(null);
  const [matrixError, setMatrixError] = useState<string | null>(null);
  // Per-member EFFECTIVE access, keyed by user id. The matrix used to render
  // `roleReaches(matrix, member.role, …)` — the role's own template — which is
  // now only half the answer: an Executive granted payroll would have shown as
  // having none. Missing means "not loaded yet", which falls back to the role
  // template rather than to an empty row, because every box unticked reads as
  // "this person can reach nothing" and that is a statement.
  const [effective, setEffective] = useState<Record<string, Record<string, string[]>>>({});
  const [accessFor, setAccessFor] = useState<string | null>(null);

  useEffect(() => {
    // Any overrides this browser is still carrying are removed, so nobody sees
    // a member marked "custom" for a restriction that never existed anywhere.
    purgeLegacyOverrides(firmId);
  }, [firmId]);

  useEffect(() => {
    let cancelled = false;
    api.identity.roleMatrix()
      .then((r) => {
        if (cancelled) return;
        if (r.success && r.data) { setMatrix(r.data.matrix); setMatrixError(null); }
        // Shown, never replaced by an empty grid: every box unticked reads as
        // "nobody can reach anything", which is a statement and a false one.
        else { setMatrix(null); setMatrixError(r.error ?? "Couldn't load the access matrix."); }
      })
      .catch(() => { if (!cancelled) { setMatrix(null); setMatrixError("Couldn't load the access matrix."); } });
    return () => { cancelled = true; };
  }, []);

  const activeMembers = members.filter(m => m.is_active !== false);

  // One request per active member. A firm has a handful of staff, so this is
  // proportional to the ANSWER rather than to anything that grows — the rule
  // this codebase applies to reports, applied to a screen. A member whose
  // request fails is simply absent from the map and renders against their role
  // template, which is what they had before anybody overrode anything.
  const loadEffective = useCallback(async () => {
    const ids = activeMembers.map(m => m.id);
    if (ids.length === 0) return;
    const answers = await Promise.all(ids.map(async (id) => {
      try {
        const r = await api.identity.memberPermissions(id);
        return r.success && r.data ? ([id, r.data.effective] as const) : null;
      } catch { return null; }
    }));
    setEffective(Object.fromEntries(answers.filter(Boolean) as [string, Record<string, string[]>][]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMembers.map(m => m.id).join(",")]);

  useEffect(() => { void loadEffective(); }, [loadEffective]);

  /** What this member may ACTUALLY reach — their own answer where we have it,
   *  their role's template where we do not. */
  const reaches = useCallback((member: TeamMember, resource: string): boolean => {
    const own = effective[member.id];
    if (own) return (own[resource]?.length ?? 0) > 0;
    return matrix ? roleReaches(matrix, member.role, resource) : false;
  }, [effective, matrix]);

  /** True where this member's access differs from what their role alone gives.
   *  Rendered differently, because an inherited permission and a decision
   *  should not look the same — that is the whole point of the grid. */
  const differsFromRole = useCallback((member: TeamMember, resource: string): boolean => {
    if (!matrix || !effective[member.id]) return false;
    return reaches(member, resource) !== roleReaches(matrix, member.role, resource);
  }, [effective, matrix, reaches]);

  if (activeMembers.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-ps-muted p-10 text-center">
        <Users className="w-8 h-8 text-gray-200 mx-auto mb-2" />
        <p className="text-sm text-ps-hint">No active team members to configure</p>
      </div>
    );
  }

  if (matrixError) {
    return (
      <div className="bg-white rounded-xl border border-ps-muted p-6 text-center">
        <p className="text-sm text-state-problem">{matrixError}</p>
      </div>
    );
  }
  if (!matrix) {
    return (
      <div className="bg-white rounded-xl border border-ps-muted p-6 text-center">
        <p className="text-sm text-ps-hint">Loading access matrix…</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Matrix table */}
      <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <h2 className="text-sm font-semibold text-ps-ink">Module Access</h2>
          <p className="text-xs text-ps-hint mt-0.5">
            What each member can actually reach, read from the server. A role sets
            the starting point; select a member to allow or block anything for
            that person alone. An <span className="text-orange-600 font-medium">amber</span> cell
            differs from what their role gives them.
          </p>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-50 bg-ps-bg/50">
                <th className="text-left text-xs font-medium text-ps-label px-4 py-3 min-w-[180px] sticky left-0 bg-ps-bg/80 backdrop-blur-sm z-10">
                  Member
                </th>
                {MODULES.map(mod => (
                  <th
                    key={mod.resource}
                    className="text-center text-xs font-medium text-ps-label px-2 py-3 min-w-[70px]"
                  >
                    <span className="block">{mod.label.split(" ")[0]}</span>
                    {mod.label.includes(" ") && (
                      <span className="block text-ps-hint">{mod.label.split(" ").slice(1).join(" ")}</span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-ps-bg">
              {activeMembers.map(member => {
                const initials = member.full_name
                  .split(" ")
                  .filter(Boolean)
                  .slice(0, 2)
                  .map(n => n[0])
                  .join("")
                  .toUpperCase();

                return (
                  <tr key={member.id} className="hover:bg-ps-bg/40">
                    {/* Sticky member name column */}
                    <td className="px-4 py-3 sticky left-0 bg-white hover:bg-ps-bg/40 z-10">
                      <div className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded-full bg-blue-700 text-white flex items-center justify-center text-xs font-semibold shrink-0">
                          {initials}
                        </div>
                        <div className="min-w-0">
                          <p className="text-xs font-medium text-ps-ink truncate max-w-[110px]">
                            {member.full_name}
                          </p>
                          <div className="flex items-center gap-1 mt-0.5">
                            <span className={`text-xs px-1.5 py-px rounded-full font-medium ${ROLE_COLORS[member.role]}`}>
                              {member.role}
                            </span>
                            <button
                              type="button"
                              onClick={() => setAccessFor(member.id)}
                              title={`Set what ${member.full_name} can reach`}
                              className="inline-flex items-center gap-0.5 text-xs text-blue-700 hover:underline"
                            >
                              <SlidersHorizontal className="w-3 h-3" />
                              Edit
                            </button>
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* What this member ACTUALLY reaches. Still a dot rather
                        than a checkbox, and deliberately: a module has several
                        actions (GST has read, compute and approve) and one tick
                        cannot express "may compute, may not approve". The
                        toggles live in the drawer, at the action level, where
                        they can say what they mean. */}
                    {MODULES.map(mod => {
                      const enabled = reaches(member, mod.resource);
                      const overridden = differsFromRole(member, mod.resource);
                      const actions = (effective[member.id]?.[mod.resource]
                        ?? matrix[member.role]?.[mod.resource] ?? []);
                      return (
                        <td key={mod.resource} className="px-2 py-3 text-center">
                          <span
                            title={[
                              enabled
                                ? `Can reach ${mod.label} (${actions.join(", ")})`
                                : `Cannot reach ${mod.label}`,
                              overridden ? "— set for this person, not by their role" : "",
                            ].filter(Boolean).join(" ")}
                            className={[
                              "inline-flex w-5 h-5 rounded items-center justify-center border",
                              enabled
                                ? overridden
                                  ? "bg-orange-500 border-orange-500"
                                  : "bg-blue-600 border-blue-600"
                                : overridden
                                  ? "border-orange-400 border-dashed bg-white"
                                  : "border-ps-border bg-white",
                            ].join(" ")}
                          >
                            {enabled && (
                              <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 12 12">
                                <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                            )}
                          </span>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Legend */}
        <div className="px-5 py-3 border-t border-gray-50 bg-ps-bg/30 flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-1.5 text-xs text-ps-label">
            <span className="w-4 h-4 rounded bg-blue-600 inline-block" />
            Access granted (role default)
          </div>
          <div className="flex items-center gap-1.5 text-xs text-ps-label">
            <span className="w-4 h-4 rounded bg-orange-500 inline-block" />
            Allowed for this person
          </div>
          <div className="flex items-center gap-1.5 text-xs text-ps-label">
            <span className="w-4 h-4 rounded border border-dashed border-orange-400 bg-white inline-block" />
            Blocked for this person
          </div>
          <div className="flex items-center gap-1.5 text-xs text-ps-label">
            <span className="w-4 h-4 rounded border border-ps-border bg-white inline-block" />
            No access
          </div>
        </div>
      </div>

      {/* Role defaults info card */}
      <RolePermissionsCard />

      {accessFor && (
        <MemberAccessDrawer
          userId={accessFor}
          onClose={() => setAccessFor(null)}
          // Re-read from the SERVER's answer rather than patching local state
          // from what was sent: the resolver applies a Partner floor, so what
          // was asked for and what took effect are not always the same, and a
          // screen that showed the request would be showing a change that did
          // not happen.
          onSaved={(grid) => setEffective(e => ({ ...e, [grid.user_id]: grid.effective }))}
        />
      )}
    </div>
  );
}

// ---- Main Page ----
export default function TeamPage() {
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [firmId, setFirmId] = useState<string | null>(null);
  const [showInvite, setShowInvite] = useState(false);
  const [editMember, setEditMember] = useState<TeamMember | null>(null);
  const [activeTab, setActiveTab] = useState<"members" | "permissions">("members");

  const loadTeam = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const supabase = getSupabaseClient();

      // Get current session
      const { data: sessionData } = await supabase.auth.getSession();
      const session = sessionData?.session;

      if (!session) {
        // No session — show empty state gracefully
        setLoading(false);
        return;
      }

      const authUserId = session.user.id;
      setCurrentUserId(authUserId);

      // Get current user's firm_id
      const { data: currentUserRow, error: userErr } = await supabase
        .from("users")
        .select("id, full_name, email, role, is_active, created_at, firm_id, auth_user_id")
        .eq("auth_user_id", authUserId)
        .maybeSingle();

      if (userErr) throw new Error(userErr.message);
      if (!currentUserRow?.firm_id) {
        // No firm yet — just show current user alone
        if (currentUserRow) {
          setMembers([{
            id: currentUserRow.id,
            full_name: currentUserRow.full_name ?? session.user.email ?? "You",
            email: currentUserRow.email ?? session.user.email ?? "",
            role: (currentUserRow.role as Role) ?? "Reviewer",
            is_active: currentUserRow.is_active !== false,
            created_at: currentUserRow.created_at,
            auth_user_id: authUserId,
            firm_id: currentUserRow.firm_id,
          }]);
        }
        setLoading(false);
        return;
      }

      const fId = currentUserRow.firm_id as string;
      setFirmId(fId);

      // Load all team members for this firm via the audited backend (team:read,
      // Manager+). A direct `.from("users")` select here would be RLS-starved —
      // migration 153 makes `users` SELECT-only for the caller's OWN row.
      const res = await api.identity.listUsers();
      if (!res.success) throw new Error(res.error ?? "Failed to load team");

      // `res.data.users` was read straight off the payload: a backend that
      // has not deployed this shape, or a 200 carrying `{}`, made `members`
      // undefined and the next render threw. `lib/api/shape.ts` exists for
      // this and its docstring counts thirteen screens.
      setMembers(arrayOrEmpty<NonNullable<typeof res.data>["users"][number]>(
        objectOrNull<{ users?: unknown }>(res.data)?.users,
      ).map(r => ({
        id: r.id,
        full_name: r.full_name ?? r.email ?? "—",
        email: r.email ?? "",
        role: (r.role as Role) ?? "Reviewer",
        is_active: r.is_active !== false,
        created_at: r.created_at,
        auth_user_id: r.auth_user_id,
        firm_id: r.firm_id,
      })));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load team");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTeam();
  }, [loadTeam]);

  // M6: identity mutations now go through the audited, Partner-only backend
  // (api.identity) instead of direct Supabase writes from the browser. The user
  // row is created server-side; the magic link is still sent for self-onboarding.
  // F21 fix: the join link now carries the server-issued, single-use invite
  // token (never firm_id/role) — /join exchanges it via POST accept-invite.
  async function handleInvite(name: string, email: string, role: Role) {
    const created = await api.identity.createUser(name, email, role);
    const joinUrl =
      (typeof window !== "undefined" ? window.location.origin : "") +
      "/join?token=" + encodeURIComponent(created.data.invite_token);
    const supabase = getSupabaseClient();
    await supabase.auth.signInWithOtp({ email, options: { emailRedirectTo: joinUrl } }).catch(() => {});
    await loadTeam();
  }

  async function handleEditRole(id: string, role: Role) {
    await api.identity.changeRole(id, role);   // audited server-side
    setMembers(ms => ms.map(m => m.id === id ? { ...m, role } : m));
  }

  async function handleDeactivate(member: TeamMember) {
    const reactivating = member.is_active === false;
    try {
      if (reactivating) await api.identity.reactivate(member.id);
      else await api.identity.suspend(member.id);   // also revokes the user's sessions
      setMembers(ms => ms.map(m => m.id === member.id ? { ...m, is_active: reactivating } : m));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : `Failed to ${reactivating ? "reactivate" : "deactivate"} team member`);
    }
  }

  // Summary counts
  const activeMembers = members.filter(m => m.is_active !== false);
  const partners = members.filter(m => m.role === "Partner").length;
  const managers = members.filter(m => m.role === "Manager").length;
  const articlesStaff = members.filter(m => m.role === "Executive" || m.role === "Reviewer").length;

  const SUMMARY_CARDS = [
    {
      label: "Total Members",
      value: members.length,
      icon: Users,
      gradient: "bg-gradient-to-br from-blue-600 to-blue-500",
      sub: `${activeMembers.length} active`,
    },
    {
      label: "Partners",
      value: partners,
      icon: Shield,
      gradient: "bg-gradient-to-br from-violet-500 to-purple-600",
      sub: "Senior leadership",
    },
    {
      label: "Managers",
      value: managers,
      icon: Users,
      gradient: "bg-gradient-to-br from-blue-500 to-blue-600",
      sub: "Team leads",
    },
    {
      label: "Articles / Staff",
      value: articlesStaff,
      icon: Users,
      gradient: "bg-gradient-to-br from-amber-400 to-orange-500",
      sub: "Support staff",
    },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ps-ink">Team</h1>
          <p className="text-sm text-ps-label mt-0.5">Manage your firm&apos;s team members and their roles</p>
        </div>
        <button
          onClick={() => setShowInvite(true)}
          className="flex items-center gap-1.5 bg-blue-600 text-white text-sm px-3 py-2 rounded-lg hover:bg-blue-700"
        >
          <UserPlus className="w-4 h-4" />
          Invite Member
        </button>
      </div>

      {error && (
        <div role="alert" className="bg-state-problem-surface border border-red-100 rounded-lg px-4 py-3 flex gap-2 text-sm text-money-out">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {SUMMARY_CARDS.map(card => (
          <div key={card.label} className="bg-white rounded-xl border border-ps-muted p-4">
            <div className="flex items-center gap-2 mb-3">
              <div className={`w-8 h-8 rounded-xl ${card.gradient} flex items-center justify-center shadow-sm`}>
                <card.icon className="w-4 h-4 text-white" />
              </div>
              <span className="text-xs text-ps-label">{card.label}</span>
            </div>
            <p className="text-lg font-semibold text-ps-ink">{loading ? "—" : card.value}</p>
            <p className="text-xs text-ps-hint mt-0.5">{card.sub}</p>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-ps-muted">
        <button
          onClick={() => setActiveTab("members")}
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
            activeTab === "members"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-ps-label hover:text-ps-body"
          }`}
        >
          Team Members
        </button>
        <button
          onClick={() => setActiveTab("permissions")}
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px flex items-center gap-1.5 ${
            activeTab === "permissions"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-ps-label hover:text-ps-body"
          }`}
        >
          <Lock className="w-3.5 h-3.5" />
          Permissions
        </button>
      </div>

      {/* Tab: Team Members */}
      {activeTab === "members" && (
        <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50">
            <h2 className="text-sm font-semibold text-ps-ink">Team Members</h2>
            <p className="text-xs text-ps-hint mt-0.5">All staff registered under your firm</p>
          </div>

          {loading ? (
            <div className="px-5 py-10 text-center text-sm text-ps-hint">Loading…</div>
          ) : members.length === 0 ? (
            <div className="px-5 py-10 text-center">
              <Users className="w-8 h-8 text-gray-200 mx-auto mb-2" />
              <p className="text-sm text-ps-hint">No team members yet</p>
              <p className="text-xs text-ps-disabled mt-1">Invite someone to get started</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-50">
                    <th className="text-left text-xs font-medium text-ps-hint px-5 py-3">Name</th>
                    <th className="text-left text-xs font-medium text-ps-hint px-3 py-3">Email</th>
                    <th className="text-left text-xs font-medium text-ps-hint px-3 py-3">Role</th>
                    <th className="text-left text-xs font-medium text-ps-hint px-3 py-3">Status</th>
                    <th className="text-left text-xs font-medium text-ps-hint px-3 py-3">Joined</th>
                    <th className="px-5 py-3 w-10"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ps-bg">
                  {members.map(member => {
                    const isCurrentUser = member.auth_user_id === currentUserId;
                    const isActive = member.is_active !== false;
                    const initials = member.full_name
                      .split(" ")
                      .filter(Boolean)
                      .slice(0, 2)
                      .map(n => n[0])
                      .join("")
                      .toUpperCase();
                    const joinedDate = member.created_at
                      ? new Date(member.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
                      : "—";

                    return (
                      <tr key={member.id} className={`hover:bg-ps-bg/50 ${!isActive ? "opacity-60" : ""}`}>
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 rounded-full bg-blue-700 text-white flex items-center justify-center text-xs font-semibold shrink-0">
                              {initials}
                            </div>
                            <div>
                              <p className="text-sm font-medium text-ps-ink">
                                {member.full_name}
                                {isCurrentUser && (
                                  <span className="ml-1.5 text-xs text-blue-500 font-normal">(You)</span>
                                )}
                              </p>
                            </div>
                          </div>
                        </td>
                        <td className="px-3 py-3">
                          <div className="flex items-center gap-1.5 text-xs text-ps-label">
                            <Mail className="w-3 h-3 shrink-0 text-ps-disabled" />
                            {member.email}
                          </div>
                        </td>
                        <td className="px-3 py-3">
                          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ROLE_COLORS[member.role] ?? "bg-ps-muted text-ps-label"}`}>
                            {member.role}
                          </span>
                        </td>
                        <td className="px-3 py-3">
                          <span className={`text-xs px-2 py-0.5 rounded-full ${isActive ? "bg-green-100 text-money-in" : "bg-ps-muted text-ps-label"}`}>
                            {isActive ? "Active" : "Inactive"}
                          </span>
                        </td>
                        <td className="px-3 py-3 text-xs text-ps-label">{joinedDate}</td>
                        <td className="px-5 py-3">
                          {!isCurrentUser && (
                            <ActionsMenu
                              member={member}
                              onEdit={() => setEditMember(member)}
                              onDeactivate={() => handleDeactivate(member)}
                            />
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Tab: Permissions */}
      {activeTab === "permissions" && (
        loading ? (
          <div className="bg-white rounded-xl border border-ps-muted px-5 py-10 text-center text-sm text-ps-hint">
            Loading…
          </div>
        ) : (
          <PermissionsMatrix
            members={members}
            firmId={firmId ?? "local"}
          />
        )
      )}

      {/* Modals */}
      {showInvite && (
        <InviteModal
          onClose={() => setShowInvite(false)}
          onInvite={handleInvite}
        />
      )}
      {editMember && (
        <EditRoleModal
          member={editMember}
          onClose={() => setEditMember(null)}
          onSave={handleEditRole}
        />
      )}
    </div>
  );
}
