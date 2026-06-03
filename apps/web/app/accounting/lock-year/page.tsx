"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Lock, Unlock, Shield, AlertTriangle, KeyRound, X, Eye, EyeOff } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { RoleGuard } from "@/components/RoleGuard";

// Indian FY list — label used for DB storage
const FY_LIST = [
  { label: "2025-26", display: "FY 2025-26 (Apr 2025 – Mar 2026)" },
  { label: "2024-25", display: "FY 2024-25 (Apr 2024 – Mar 2025)" },
  { label: "2023-24", display: "FY 2023-24 (Apr 2023 – Mar 2024)" },
  { label: "2022-23", display: "FY 2022-23 (Apr 2022 – Mar 2023)" },
];

// PIN dialog state type
type PinDialog = { fy: string; isLocked: boolean } | null;

function PinModal({
  dialog, lockPin, onConfirm, onClose,
}: {
  dialog: PinDialog;
  lockPin: string | null;
  onConfirm: (fy: string, isLocked: boolean, enteredPin: string) => void;
  onClose: () => void;
}) {
  const [pin, setPin] = useState("");
  const [newPin, setNewPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");
  const [showPin, setShowPin] = useState(false);
  const [err, setErr] = useState("");

  if (!dialog) return null;
  const d = dialog; // narrowed non-null for use inside callbacks
  const isSettingPin = !lockPin;

  function submit() {
    setErr("");
    if (isSettingPin) {
      if (newPin.length < 4) { setErr("PIN must be at least 4 characters"); return; }
      if (newPin !== confirmPin) { setErr("PINs do not match"); return; }
      onConfirm(d.fy, d.isLocked, newPin);
    } else {
      if (pin !== lockPin) { setErr("Incorrect PIN"); return; }
      onConfirm(d.fy, d.isLocked, pin);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <KeyRound className="w-5 h-5 text-blue-600" />
            <h2 className="text-base font-semibold text-gray-900">
              {isSettingPin ? "Set Lock PIN" : d.isLocked ? "Unlock Year" : "Lock Year"}
            </h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
        </div>

        <p className="text-sm text-gray-500">
          {isSettingPin
            ? "No PIN is set yet. Create a PIN that Partners will use to lock or unlock financial years."
            : `Enter the firm PIN to ${d.isLocked ? "unlock" : "lock"} FY ${d.fy}.`}
        </p>

        {isSettingPin ? (
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">New PIN</label>
              <div className="relative">
                <input
                  type={showPin ? "text" : "password"}
                  value={newPin}
                  onChange={e => setNewPin(e.target.value)}
                  placeholder="Min 4 characters"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm pr-9 outline-none focus:border-blue-500"
                />
                <button type="button" onClick={() => setShowPin(v => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400">
                  {showPin ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Confirm PIN</label>
              <input
                type={showPin ? "text" : "password"}
                value={confirmPin}
                onChange={e => setConfirmPin(e.target.value)}
                placeholder="Re-enter PIN"
                onKeyDown={e => e.key === "Enter" && submit()}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              />
            </div>
          </div>
        ) : (
          <div className="relative">
            <input
              autoFocus
              type={showPin ? "text" : "password"}
              value={pin}
              onChange={e => setPin(e.target.value)}
              onKeyDown={e => e.key === "Enter" && submit()}
              placeholder="Enter firm PIN"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm pr-9 outline-none focus:border-blue-500"
            />
            <button type="button" onClick={() => setShowPin(v => !v)}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400">
              {showPin ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        )}

        {err && <p className="text-xs text-red-600">{err}</p>}

        <div className="flex gap-2 pt-1">
          <button onClick={onClose}
            className="flex-1 rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
            Cancel
          </button>
          <button onClick={submit}
            className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
            {isSettingPin ? "Set PIN & Lock" : "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}

function LockYearContent() {
  const [firmId, setFirmId] = useState<string | null>(null);
  const [lockedYears, setLockedYears] = useState<string[]>([]);
  const [lockPin, setLockPin] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [pinDialog, setPinDialog] = useState<PinDialog>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const sb = getSupabaseClient();
      const { data: { session } } = await sb.auth.getSession();
      if (!session) throw new Error("Not authenticated");
      const { data: user } = await sb
        .from("users")
        .select("firm_id")
        .eq("auth_user_id", session.user.id)
        .maybeSingle();
      if (!user?.firm_id) throw new Error("Firm not found — please complete onboarding first");
      setFirmId(user.firm_id);
      const { data: firm, error: firmErr } = await sb
        .from("firms")
        .select("locked_financial_years, lock_pin")
        .eq("id", user.firm_id)
        .maybeSingle();
      if (firmErr) throw new Error(firmErr.message);
      setLockedYears(firm?.locked_financial_years ?? []);
      setLockPin(firm?.lock_pin ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function toggleLock(fy: string, currentlyLocked: boolean, enteredPin: string) {
    if (!firmId) return;
    setSaving(fy);
    setPinDialog(null);
    try {
      const sb = getSupabaseClient();
      const newLocked = currentlyLocked
        ? lockedYears.filter((y) => y !== fy)
        : [...lockedYears, fy];

      const updatePayload: Record<string, unknown> = { locked_financial_years: newLocked };
      // If PIN was just set for the first time, save it too
      if (!lockPin) {
        updatePayload.lock_pin = enteredPin;
        setLockPin(enteredPin);
      }

      const { error: updateErr } = await sb
        .from("firms")
        .update(updatePayload)
        .eq("id", firmId);

      if (updateErr) throw new Error(updateErr.message);
      setLockedYears(newLocked);
      setToast(currentlyLocked ? `FY ${fy} unlocked` : `FY ${fy} locked — no further edits allowed`);
      setTimeout(() => setToast(null), 4000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update");
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-gray-900">Lock Financial Year</h1>
          <p className="text-sm text-gray-500 mt-0.5">Partner-only — lock closed years to prevent accidental edits</p>
        </div>
        <Shield className="w-5 h-5 text-blue-600" />
      </div>

      {/* Warning */}
      <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 flex gap-3">
        <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
        <div className="text-sm text-amber-800">
          <p className="font-medium">Locking a year prevents all journal entries, invoice edits, and adjustments for that period.</p>
          <p className="text-xs mt-1 text-amber-600">Only Partners can lock or unlock. Unlock before making any corrections.</p>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-100 rounded-lg px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {/* FY list */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-50 bg-gray-50">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Financial Years</p>
        </div>
        {loading ? (
          <div className="px-5 py-8 text-center text-sm text-gray-400 animate-pulse">Loading…</div>
        ) : (
          <div className="divide-y divide-gray-50">
            {FY_LIST.map((fy) => {
              const isLocked = lockedYears.includes(fy.label);
              const isSaving = saving === fy.label;
              return (
                <div key={fy.label} className="flex items-center justify-between px-5 py-4">
                  <div className="flex items-center gap-3">
                    {isLocked
                      ? <Lock className="w-4 h-4 text-red-500" />
                      : <Unlock className="w-4 h-4 text-gray-300" />
                    }
                    <div>
                      <p className="text-sm font-medium text-gray-900">{fy.display}</p>
                      <p className={`text-xs mt-0.5 ${isLocked ? "text-red-600 font-medium" : "text-gray-400"}`}>
                        {isLocked ? "Locked — no edits permitted" : "Open — edits allowed"}
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={() => setPinDialog({ fy: fy.label, isLocked })}
                    disabled={isSaving}
                    className={`text-xs px-4 py-1.5 rounded-lg font-medium transition-colors disabled:opacity-50 ${
                      isLocked
                        ? "bg-gray-100 text-gray-700 hover:bg-gray-200"
                        : "bg-red-600 text-white hover:bg-red-700"
                    }`}
                  >
                    {isSaving ? "…" : isLocked ? "Unlock" : "Lock Year"}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* PIN status */}
      <div className="flex items-center justify-between bg-gray-50 rounded-xl px-4 py-3">
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <KeyRound size={14} className="text-gray-400" />
          <span>Lock PIN: </span>
          <span className={`font-medium ${lockPin ? "text-green-700" : "text-amber-600"}`}>
            {lockPin ? "Set" : "Not set — will be created on first lock"}
          </span>
        </div>
      </div>

      <p className="text-xs text-gray-400 text-center">
        Locking follows AS-1 (Accounting Standard on Disclosure of Accounting Policies) — once books are closed, entries should not be changed without proper rectification journals in the next open period.
      </p>

      <PinModal
        dialog={pinDialog}
        lockPin={lockPin}
        onConfirm={(fy, isLocked, pin) => toggleLock(fy, isLocked, pin)}
        onClose={() => setPinDialog(null)}
      />

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 right-6 bg-gray-900 text-white text-sm px-4 py-3 rounded-xl shadow-lg">
          {toast}
        </div>
      )}
    </div>
  );
}

export default function LockYearPage() {
  return (
    <RoleGuard allowed={["Partner"]}>
      <LockYearContent />
    </RoleGuard>
  );
}
