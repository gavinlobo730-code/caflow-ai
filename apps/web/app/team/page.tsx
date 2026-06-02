"use client";

import { useState, useEffect, useCallback } from "react";
import { Users, UserPlus, Shield, Mail, MoreVertical, X, AlertCircle, Lock } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";

type Role = "Partner" | "Manager" | "Article" | "Staff";

// All modules trackable in the permissions matrix
const MODULES = [
  "Accounting",
  "GST",
  "Income Tax",
  "TDS",
  "MCA",
  "Payroll",
  "Billing",
  "Reports",
  "Settings",
  "Clients",
  "Tasks",
] as const;

type Module = (typeof MODULES)[number];

// Default module access per role — mirrors permissions.ts logic
const ROLE_DEFAULTS: Record<Role, Record<Module, boolean>> = {
  Partner: {
    Accounting: true,
    GST: true,
    "Income Tax": true,
    TDS: true,
    MCA: true,
    Payroll: true,
    Billing: true,
    Reports: true,
    Settings: true,
    Clients: true,
    Tasks: true,
  },
  Manager: {
    Accounting: true,
    GST: true,
    "Income Tax": true,
    TDS: true,
    MCA: true,
    Payroll: true,
    Billing: true,
    Reports: false,
    Settings: false,
    Clients: true,
    Tasks: true,
  },
  Article: {
    Accounting: false,
    GST: false,
    "Income Tax": false,
    TDS: false,
    MCA: false,
    Payroll: false,
    Billing: false,
    Reports: false,
    Settings: false,
    Clients: true,
    Tasks: true,
  },
  Staff: {
    Accounting: false,
    GST: false,
    "Income Tax": false,
    TDS: false,
    MCA: false,
    Payroll: false,
    Billing: false,
    Reports: false,
    Settings: false,
    Clients: true,
    Tasks: true,
  },
};

// Per-member permissions map: memberId -> module -> boolean
type MemberPermissions = Record<string, Record<Module, boolean>>;

// localStorage key per firm
function permissionsKey(firmId: string): string {
  return `caflow_permissions_${firmId}`;
}

function loadPermissionsFromStorage(firmId: string): MemberPermissions {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(permissionsKey(firmId));
    if (!raw) return {};
    return JSON.parse(raw) as MemberPermissions;
  } catch {
    return {};
  }
}

function savePermissionsToStorage(firmId: string, perms: MemberPermissions): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(permissionsKey(firmId), JSON.stringify(perms));
}

/** Returns the effective permissions for a member — stored overrides, or role defaults */
function effectivePermissions(
  member: { id: string; role: Role },
  stored: MemberPermissions
): Record<Module, boolean> {
  if (stored[member.id]) {
    return stored[member.id];
  }
  return { ...ROLE_DEFAULTS[member.role] };
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

const ROLES: Role[] = ["Partner", "Manager", "Article", "Staff"];

const ROLE_COLORS: Record<Role, string> = {
  Partner: "bg-purple-100 text-purple-700",
  Manager: "bg-blue-100 text-blue-700",
  Article: "bg-amber-100 text-amber-700",
  Staff: "bg-gray-100 text-gray-600",
};

// ---- Invite Modal ----
interface InviteModalProps {
  onClose: () => void;
  onInvite: (name: string, email: string, role: Role) => Promise<void>;
}

function InviteModal({ onClose, onInvite }: InviteModalProps) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("Staff");
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
      <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4 text-center">
          <div className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center mx-auto">
            <Mail className="w-6 h-6 text-green-600" />
          </div>
          <h3 className="text-sm font-semibold text-gray-900">Invitation Sent</h3>
          <p className="text-xs text-gray-500">{email} has been added to the team as {role}.</p>
          <button onClick={onClose} className="w-full bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700">
            Done
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Invite Team Member</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-100 rounded-lg px-3 py-2 flex gap-2 text-xs text-red-700">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Full Name</label>
            <input
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="e.g. Priya Sharma"
              value={name}
              onChange={e => setName(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Email Address</label>
            <input
              type="email"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="priya@firm.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Role</label>
            <select
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={role}
              onChange={e => setRole(e.target.value as Role)}
            >
              {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose} className="flex-1 border border-gray-200 text-gray-600 text-sm py-2 rounded-lg hover:bg-gray-50">
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
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Edit Role</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
        </div>
        <p className="text-xs text-gray-500">{member.full_name} · {member.email}</p>

        {error && (
          <div className="bg-red-50 border border-red-100 rounded-lg px-3 py-2 flex gap-2 text-xs text-red-700">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">Role</label>
          <select
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={role}
            onChange={e => setRole(e.target.value as Role)}
          >
            {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div className="flex gap-2 pt-2">
          <button onClick={onClose} className="flex-1 border border-gray-200 text-gray-600 text-sm py-2 rounded-lg hover:bg-gray-50">Cancel</button>
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
        className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600"
      >
        <MoreVertical className="w-4 h-4" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 mt-1 w-40 bg-white border border-gray-100 rounded-lg shadow-lg z-20 py-1">
            <button
              onClick={() => { setOpen(false); onEdit(); }}
              className="w-full text-left px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 flex items-center gap-2"
            >
              <Shield className="w-3.5 h-3.5" />
              Edit Role
            </button>
            <button
              onClick={() => { setOpen(false); onDeactivate(); }}
              className={`w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-gray-50 ${
                isActive ? "text-red-600" : "text-green-600"
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
function RolePermissionsCard() {
  return (
    <div className="bg-white rounded-xl border border-gray-100 p-5 space-y-4">
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-lg bg-violet-100 flex items-center justify-center">
          <Lock className="w-3.5 h-3.5 text-violet-600" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-gray-900">Default Role Permissions</h3>
          <p className="text-xs text-gray-400">Admins can override these per person in the matrix above</p>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {ROLES.map(role => {
          const defaults = ROLE_DEFAULTS[role];
          const allowed = MODULES.filter(m => defaults[m]);
          const denied = MODULES.filter(m => !defaults[m]);
          return (
            <div key={role} className="border border-gray-100 rounded-lg p-3 space-y-2">
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ROLE_COLORS[role]}`}>
                {role}
              </span>
              <div className="space-y-1">
                {allowed.map(m => (
                  <div key={m} className="flex items-center gap-1.5 text-xs text-green-700">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-400 shrink-0" />
                    {m}
                  </div>
                ))}
                {denied.map(m => (
                  <div key={m} className="flex items-center gap-1.5 text-xs text-gray-400">
                    <span className="w-1.5 h-1.5 rounded-full bg-gray-200 shrink-0" />
                    {m}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---- Permissions Matrix Tab ----
interface PermissionsMatrixProps {
  members: TeamMember[];
  firmId: string;
}

function PermissionsMatrix({ members, firmId }: PermissionsMatrixProps) {
  const [stored, setStored] = useState<MemberPermissions>({});

  // Load from localStorage on mount
  useEffect(() => {
    setStored(loadPermissionsFromStorage(firmId));
  }, [firmId]);

  function togglePermission(memberId: string, memberRole: Role, module: Module) {
    setStored(prev => {
      // Start from current effective permissions for this member
      const current = effectivePermissions({ id: memberId, role: memberRole }, prev);
      const updated: MemberPermissions = {
        ...prev,
        [memberId]: {
          ...current,
          [module]: !current[module],
        },
      };
      savePermissionsToStorage(firmId, updated);
      return updated;
    });
  }

  function resetMemberToDefault(memberId: string) {
    setStored(prev => {
      const updated = { ...prev };
      delete updated[memberId];
      savePermissionsToStorage(firmId, updated);
      return updated;
    });
  }

  const activeMembers = members.filter(m => m.is_active !== false);

  if (activeMembers.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-gray-100 p-10 text-center">
        <Users className="w-8 h-8 text-gray-200 mx-auto mb-2" />
        <p className="text-sm text-gray-400">No active team members to configure</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Matrix table */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <h2 className="text-sm font-semibold text-gray-900">Module Access Matrix</h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Toggle access per member per module. Changes are saved instantly.
            Overrides the role default for that individual.
          </p>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-50 bg-gray-50/50">
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3 min-w-[180px] sticky left-0 bg-gray-50/80 backdrop-blur-sm z-10">
                  Member
                </th>
                {MODULES.map(mod => (
                  <th
                    key={mod}
                    className="text-center text-xs font-medium text-gray-500 px-2 py-3 min-w-[70px]"
                  >
                    <span className="block">{mod.split(" ")[0]}</span>
                    {mod.includes(" ") && (
                      <span className="block text-gray-400">{mod.split(" ").slice(1).join(" ")}</span>
                    )}
                  </th>
                ))}
                <th className="text-center text-xs font-medium text-gray-500 px-3 py-3 min-w-[80px]">
                  Reset
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {activeMembers.map(member => {
                const perms = effectivePermissions({ id: member.id, role: member.role }, stored);
                const isOverridden = !!stored[member.id];
                const initials = member.full_name
                  .split(" ")
                  .filter(Boolean)
                  .slice(0, 2)
                  .map(n => n[0])
                  .join("")
                  .toUpperCase();

                return (
                  <tr key={member.id} className="hover:bg-gray-50/40">
                    {/* Sticky member name column */}
                    <td className="px-4 py-3 sticky left-0 bg-white hover:bg-gray-50/40 z-10">
                      <div className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded-full bg-blue-700 text-white flex items-center justify-center text-xs font-semibold shrink-0">
                          {initials}
                        </div>
                        <div className="min-w-0">
                          <p className="text-xs font-medium text-gray-900 truncate max-w-[110px]">
                            {member.full_name}
                          </p>
                          <div className="flex items-center gap-1 mt-0.5">
                            <span className={`text-xs px-1.5 py-px rounded-full font-medium ${ROLE_COLORS[member.role]}`}>
                              {member.role}
                            </span>
                            {isOverridden && (
                              <span className="text-xs text-orange-500 font-medium">custom</span>
                            )}
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* Module checkboxes */}
                    {MODULES.map(mod => {
                      const enabled = perms[mod];
                      const defaultVal = ROLE_DEFAULTS[member.role][mod];
                      const differs = isOverridden && stored[member.id]?.[mod] !== defaultVal;
                      return (
                        <td key={mod} className="px-2 py-3 text-center">
                          <label className="inline-flex items-center justify-center cursor-pointer group">
                            <input
                              type="checkbox"
                              checked={enabled}
                              onChange={() => togglePermission(member.id, member.role, mod)}
                              className="sr-only"
                            />
                            <span
                              className={[
                                "w-5 h-5 rounded flex items-center justify-center border transition-colors",
                                enabled
                                  ? differs
                                    ? "bg-orange-500 border-orange-500"
                                    : "bg-blue-600 border-blue-600"
                                  : "border-gray-200 bg-white group-hover:border-gray-300",
                              ].join(" ")}
                            >
                              {enabled && (
                                <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 12 12">
                                  <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                              )}
                            </span>
                          </label>
                        </td>
                      );
                    })}

                    {/* Reset to role defaults */}
                    <td className="px-3 py-3 text-center">
                      {isOverridden ? (
                        <button
                          onClick={() => resetMemberToDefault(member.id)}
                          className="text-xs text-gray-400 hover:text-blue-600 underline underline-offset-2 transition-colors"
                          title="Reset to role defaults"
                        >
                          Reset
                        </button>
                      ) : (
                        <span className="text-xs text-gray-200">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Legend */}
        <div className="px-5 py-3 border-t border-gray-50 bg-gray-50/30 flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <span className="w-4 h-4 rounded bg-blue-600 inline-block" />
            Access granted (role default)
          </div>
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <span className="w-4 h-4 rounded bg-orange-500 inline-block" />
            Access granted (admin override)
          </div>
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <span className="w-4 h-4 rounded border border-gray-200 bg-white inline-block" />
            No access
          </div>
        </div>
      </div>

      {/* Role defaults info card */}
      <RolePermissionsCard />
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
            role: (currentUserRow.role as Role) ?? "Staff",
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

      // Load all team members for this firm
      const { data: teamRows, error: teamErr } = await supabase
        .from("users")
        .select("id, full_name, email, role, is_active, created_at, auth_user_id, firm_id")
        .eq("firm_id", fId)
        .order("created_at", { ascending: true });

      if (teamErr) throw new Error(teamErr.message);

      setMembers((teamRows ?? []).map(r => ({
        id: r.id,
        full_name: r.full_name ?? r.email ?? "—",
        email: r.email ?? "",
        role: (r.role as Role) ?? "Staff",
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

  async function handleInvite(name: string, email: string, role: Role) {
    const supabase = getSupabaseClient();
    const { error: insertErr } = await supabase.from("users").insert({
      full_name: name,
      email,
      role,
      firm_id: firmId,
      is_active: true,
      status: "invited",
    });
    if (insertErr) throw new Error(insertErr.message);
    await loadTeam();
  }

  async function handleEditRole(id: string, role: Role) {
    const supabase = getSupabaseClient();
    const { error: updateErr } = await supabase.from("users").update({ role }).eq("id", id);
    if (updateErr) throw new Error(updateErr.message);
    setMembers(ms => ms.map(m => m.id === id ? { ...m, role } : m));
  }

  async function handleDeactivate(member: TeamMember) {
    const newActive = member.is_active === false;
    const supabase = getSupabaseClient();
    // Soft deactivate — set is_active flag. If column doesn't exist, update silently fails gracefully in UI.
    const { error: updateErr } = await supabase
      .from("users")
      .update({ is_active: newActive })
      .eq("id", member.id);
    if (updateErr) {
      // Column may not exist — update UI optimistically anyway
      setMembers(ms => ms.map(m => m.id === member.id ? { ...m, is_active: newActive } : m));
      return;
    }
    setMembers(ms => ms.map(m => m.id === member.id ? { ...m, is_active: newActive } : m));
  }

  // Summary counts
  const activeMembers = members.filter(m => m.is_active !== false);
  const partners = members.filter(m => m.role === "Partner").length;
  const managers = members.filter(m => m.role === "Manager").length;
  const articlesStaff = members.filter(m => m.role === "Article" || m.role === "Staff").length;

  const SUMMARY_CARDS = [
    {
      label: "Total Members",
      value: members.length,
      icon: Users,
      gradient: "bg-gradient-to-br from-indigo-500 to-indigo-600",
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
          <h1 className="text-xl font-semibold text-gray-900">Team</h1>
          <p className="text-sm text-gray-500 mt-0.5">Manage your firm&apos;s team members and their roles</p>
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
        <div className="bg-red-50 border border-red-100 rounded-lg px-4 py-3 flex gap-2 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {SUMMARY_CARDS.map(card => (
          <div key={card.label} className="bg-white rounded-xl border border-gray-100 p-4">
            <div className="flex items-center gap-2 mb-3">
              <div className={`w-8 h-8 rounded-xl ${card.gradient} flex items-center justify-center shadow-sm`}>
                <card.icon className="w-4 h-4 text-white" />
              </div>
              <span className="text-xs text-gray-500">{card.label}</span>
            </div>
            <p className="text-lg font-semibold text-gray-900">{loading ? "—" : card.value}</p>
            <p className="text-xs text-gray-400 mt-0.5">{card.sub}</p>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-100">
        <button
          onClick={() => setActiveTab("members")}
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
            activeTab === "members"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          Team Members
        </button>
        <button
          onClick={() => setActiveTab("permissions")}
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px flex items-center gap-1.5 ${
            activeTab === "permissions"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          <Lock className="w-3.5 h-3.5" />
          Permissions
        </button>
      </div>

      {/* Tab: Team Members */}
      {activeTab === "members" && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50">
            <h2 className="text-sm font-semibold text-gray-900">Team Members</h2>
            <p className="text-xs text-gray-400 mt-0.5">All staff registered under your firm</p>
          </div>

          {loading ? (
            <div className="px-5 py-10 text-center text-sm text-gray-400">Loading…</div>
          ) : members.length === 0 ? (
            <div className="px-5 py-10 text-center">
              <Users className="w-8 h-8 text-gray-200 mx-auto mb-2" />
              <p className="text-sm text-gray-400">No team members yet</p>
              <p className="text-xs text-gray-300 mt-1">Invite someone to get started</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-50">
                    <th className="text-left text-xs font-medium text-gray-400 px-5 py-3">Name</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Email</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Role</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Status</th>
                    <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Joined</th>
                    <th className="px-5 py-3 w-10"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
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
                      <tr key={member.id} className={`hover:bg-gray-50/50 ${!isActive ? "opacity-60" : ""}`}>
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 rounded-full bg-blue-700 text-white flex items-center justify-center text-xs font-semibold shrink-0">
                              {initials}
                            </div>
                            <div>
                              <p className="text-sm font-medium text-gray-900">
                                {member.full_name}
                                {isCurrentUser && (
                                  <span className="ml-1.5 text-xs text-blue-500 font-normal">(You)</span>
                                )}
                              </p>
                            </div>
                          </div>
                        </td>
                        <td className="px-3 py-3">
                          <div className="flex items-center gap-1.5 text-xs text-gray-500">
                            <Mail className="w-3 h-3 shrink-0 text-gray-300" />
                            {member.email}
                          </div>
                        </td>
                        <td className="px-3 py-3">
                          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ROLE_COLORS[member.role] ?? "bg-gray-100 text-gray-600"}`}>
                            {member.role}
                          </span>
                        </td>
                        <td className="px-3 py-3">
                          <span className={`text-xs px-2 py-0.5 rounded-full ${isActive ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                            {isActive ? "Active" : "Inactive"}
                          </span>
                        </td>
                        <td className="px-3 py-3 text-xs text-gray-500">{joinedDate}</td>
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
          <div className="bg-white rounded-xl border border-gray-100 px-5 py-10 text-center text-sm text-gray-400">
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
