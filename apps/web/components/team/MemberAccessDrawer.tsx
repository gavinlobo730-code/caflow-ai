"use client";

/**
 * One member's access, edited per person (migration 403).
 *
 * WHAT THIS REPLACES
 *     A grid of checkboxes headed "Toggle access per member per module. Changes
 *     are saved instantly. Overrides the role default for that individual."
 *     Every clause was false: the toggles went into localStorage, reaching no
 *     other user, device or server, and `core/permissions.py` had no per-member
 *     override concept, so nothing could have honoured them. A Partner who
 *     unticked Payroll for an Executive believed they had removed access. They
 *     had not, anywhere. It was left READ-ONLY rather than deleted because the
 *     need it described is real; this is that need, built.
 *
 * THREE STATES, NOT A CHECKBOX
 *     Role · Allow · Block. A checkbox has two, and the third — "no override,
 *     whatever the role says" — is the one that lets a Partner hand a
 *     permission BACK to the role after granting or blocking it. Without it the
 *     first tick would freeze today's role map into the person's row for ever,
 *     detached from the firm's own role definitions. It is also the state every
 *     member is in today, so it must be nameable.
 *
 * NOTHING IS DECIDED HERE
 *     The server resolves access (`core/permissions.resolve_permission`) and
 *     this screen renders what it is told. In particular the "effective" column
 *     is the SERVER's answer re-read after every save, not a local recompute —
 *     a browser that worked out the effect itself would be a second resolver,
 *     and the two disagreeing is exactly how the read-only grid came to lie.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { X, ShieldAlert, Lock, RotateCcw } from "lucide-react";
import { api, type MemberAccessGrid } from "@/lib/api";

type Pair = {
  resource: string;
  action: string;
  privilege_changing: boolean;
  unrevokable_for_partner: boolean;
};

/** The three states a pair can be in, as the wire represents them. */
type Choice = "role" | "allow" | "block";
const CHOICES: { key: Choice; label: string; title: string }[] = [
  { key: "role", label: "Role", title: "No override — whatever this person's role gives them" },
  { key: "allow", label: "Allow", title: "Allowed, however junior the role" },
  { key: "block", label: "Block", title: "Refused, however senior the role" },
];

function choiceOf(overrides: Record<string, boolean>, key: string): Choice {
  if (!(key in overrides)) return "role";
  return overrides[key] ? "allow" : "block";
}

/** The wire value for a choice. `null` DELETES the row — see the API client. */
function wireValue(choice: Choice): boolean | null {
  return choice === "role" ? null : choice === "allow";
}

/** Title Case from a snake_case resource or action, so no label list is kept here. */
function humanise(token: string): string {
  return token
    .split("_")
    .map((w) => (w.length <= 3 ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)))
    .join(" ");
}

interface Props {
  userId: string;
  /** Closed by the caller; this component never navigates. */
  onClose: () => void;
  /** Called after a successful save so the matrix behind can refresh. */
  onSaved?: (grid: MemberAccessGrid) => void;
}

export default function MemberAccessDrawer({ userId, onClose, onSaved }: Props) {
  const [vocabulary, setVocabulary] = useState<Pair[] | null>(null);
  const [grid, setGrid] = useState<MemberAccessGrid | null>(null);
  const [draft, setDraft] = useState<Record<string, Choice>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    const [vocab, one] = await Promise.all([
      api.identity.permissionVocabulary(),
      api.identity.memberPermissions(userId),
    ]);
    // Both endpoints answer 200 with {success:false} on a refusal, so an
    // unchecked call would render an empty grid as though the person had no
    // access at all — the failure mode this codebase keeps finding.
    if (!vocab.success || !vocab.data) { setError(vocab.error ?? "Couldn't load the permission list."); return; }
    if (!one.success || !one.data) { setError(one.error ?? "Couldn't load this member's access."); return; }
    setVocabulary(vocab.data.permissions);
    setGrid(one.data);
    setDraft(
      Object.fromEntries(
        vocab.data.permissions.map((p) => {
          const key = `${p.resource}:${p.action}`;
          return [key, choiceOf(one.data!.overrides, key)];
        }),
      ),
    );
  }, [userId]);

  useEffect(() => {
    let cancelled = false;
    load().catch(() => { if (!cancelled) setError("Couldn't load this member's access."); });
    return () => { cancelled = true; };
  }, [load]);

  /** What has moved since the server's answer — the payload, and the dirty flag. */
  const changes = useMemo(() => {
    if (!grid || !vocabulary) return {} as Record<string, boolean | null>;
    const out: Record<string, boolean | null> = {};
    for (const p of vocabulary) {
      const key = `${p.resource}:${p.action}`;
      const was = choiceOf(grid.overrides, key);
      const now = draft[key] ?? "role";
      if (now !== was) out[key] = wireValue(now);
    }
    return out;
  }, [draft, grid, vocabulary]);

  const dirty = Object.keys(changes).length > 0;

  /** The vocabulary grouped by resource, in the order the server sent it.
   *  An array of pairs rather than a Map, because the build targets a
   *  JS version whose Map iterator needs downlevelIteration and the grouping
   *  is the only thing wanted here. */
  const byResource = useMemo<Array<[string, Pair[]]>>(() => {
    const order: string[] = [];
    const groups: Record<string, Pair[]> = {};
    for (const p of vocabulary ?? []) {
      if (!groups[p.resource]) { groups[p.resource] = []; order.push(p.resource); }
      groups[p.resource].push(p);
    }
    return order.map((r) => [r, groups[r]]);
  }, [vocabulary]);

  async function save() {
    if (!dirty || saving) return;
    setSaving(true);
    setError(null);
    try {
      const res = await api.identity.setMemberPermissions(userId, changes);
      if (!res.success || !res.data) {
        setError(res.error ?? "Couldn't save those changes.");
        return;
      }
      setGrid(res.data);
      setDraft(
        Object.fromEntries(
          (vocabulary ?? []).map((p) => {
            const key = `${p.resource}:${p.action}`;
            return [key, choiceOf(res.data!.overrides, key)];
          }),
        ),
      );
      onSaved?.(res.data);
    } catch {
      setError("Couldn't save those changes.");
    } finally {
      setSaving(false);
    }
  }

  function resetAll() {
    setDraft((d) => Object.fromEntries(Object.keys(d).map((k) => [k, "role" as Choice])));
  }

  const isPartner = grid?.role === "Partner";

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div
        className="w-full max-w-2xl h-full bg-white shadow-xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Member access"
      >
        <div className="px-5 py-4 border-b border-[#F1F5F9] flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-[#0F172A] truncate">
              {grid?.full_name || "Member access"}
            </h2>
            <p className="text-xs text-[#94A3B8] mt-0.5">
              {grid?.email}
              {grid?.role ? ` · ${grid.role}` : ""}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-[#94A3B8] hover:text-[#0F172A]">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-3 border-b border-[#F1F5F9] bg-[#F8FAFC]/60">
          <p className="text-xs text-[#475569]">
            <strong className="font-medium text-[#0F172A]">Role</strong> means no override — this
            person gets whatever their role gives them, and follows it if the role changes.{" "}
            <strong className="font-medium text-[#0F172A]">Allow</strong> and{" "}
            <strong className="font-medium text-[#0F172A]">Block</strong> override it for this
            person only.
          </p>
          <p className="text-xs text-[#94A3B8] mt-1">
            Which <em>clients</em> this person can open is set separately, under Client
            Assignments — this screen decides which parts of the product they can use.
          </p>
        </div>

        {error && (
          <div className="px-5 py-3 border-b border-[#F1F5F9]">
            <p className="text-xs text-red-600">{error}</p>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {!vocabulary || !grid ? (
            <p className="text-sm text-[#94A3B8]">Loading…</p>
          ) : (
            byResource.map(([resource, pairs]) => (
              <div key={resource}>
                <h3 className="text-xs font-semibold text-[#0F172A] mb-2">{humanise(resource)}</h3>
                <div className="space-y-1">
                  {pairs.map((p: Pair) => {
                    const key = `${p.resource}:${p.action}`;
                    const current = draft[key] ?? "role";
                    const roleGives = (grid.role_defaults[p.resource] ?? []).includes(p.action);
                    const partnerFloor = isPartner && p.unrevokable_for_partner;
                    return (
                      <div
                        key={key}
                        className="flex items-center justify-between gap-3 py-1.5 px-2 rounded hover:bg-[#F8FAFC]"
                      >
                        <div className="min-w-0 flex items-center gap-2">
                          <span className="text-xs text-[#334155]">{humanise(p.action)}</span>
                          <span className="text-[10px] text-[#94A3B8]">
                            {roleGives ? "role allows" : "role does not allow"}
                          </span>
                          {p.privilege_changing && (
                            <span
                              title="Granting this lets them change what other people can do."
                              className="inline-flex items-center gap-1 text-[10px] text-amber-700 bg-amber-50 px-1.5 py-px rounded"
                            >
                              <ShieldAlert className="w-3 h-3" />
                              changes others&apos; access
                            </span>
                          )}
                          {partnerFloor && (
                            <span
                              title="A Partner cannot be blocked from this — it is what reaches this screen, so removing it would leave nobody able to put it back."
                              className="inline-flex items-center gap-1 text-[10px] text-[#64748B] bg-[#F1F5F9] px-1.5 py-px rounded"
                            >
                              <Lock className="w-3 h-3" />
                              always on for a Partner
                            </span>
                          )}
                        </div>
                        <div className="flex shrink-0 rounded-md border border-[#E2E8F0] overflow-hidden">
                          {CHOICES.map((c) => {
                            const disabled = partnerFloor && c.key === "block";
                            const active = current === c.key;
                            return (
                              <button
                                key={c.key}
                                type="button"
                                title={disabled
                                  ? "A Partner cannot be blocked from this."
                                  : c.title}
                                disabled={disabled}
                                onClick={() => setDraft((d) => ({ ...d, [key]: c.key }))}
                                className={[
                                  "px-2 py-1 text-[11px] border-r last:border-r-0 border-[#E2E8F0]",
                                  disabled
                                    ? "text-[#CBD5E1] cursor-not-allowed"
                                    : active
                                      ? c.key === "block"
                                        ? "bg-red-600 text-white"
                                        : c.key === "allow"
                                          ? "bg-emerald-600 text-white"
                                          : "bg-[#F1F5F9] text-[#0F172A]"
                                      : "text-[#64748B] hover:bg-[#F8FAFC]",
                                ].join(" ")}
                              >
                                {c.label}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </div>

        <div className="px-5 py-3 border-t border-[#F1F5F9] flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={resetAll}
            className="inline-flex items-center gap-1.5 text-xs text-[#64748B] hover:text-[#0F172A]"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Back to role defaults
          </button>
          <div className="flex items-center gap-2">
            <span className="text-xs text-[#94A3B8]">
              {dirty ? `${Object.keys(changes).length} change${Object.keys(changes).length === 1 ? "" : "s"}` : "No changes"}
            </span>
            <button
              type="button"
              onClick={save}
              disabled={!dirty || saving}
              className="px-3 py-1.5 text-xs font-medium rounded-md bg-blue-700 text-white disabled:bg-[#CBD5E1]"
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
