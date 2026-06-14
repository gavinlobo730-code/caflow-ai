"use client";

import { ReactNode } from "react";
import { Lock } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { isPartnerOnlyAllowed } from "@/lib/auth/permissions";

/**
 * Route-level guard for the Practice workspace (Amendment v1.1 Guardrail G1).
 * Practice/Revenue surfaces are Partner-only. The nav entry is already hidden
 * for non-partners; this also blocks direct URL access. The backend RBAC + RLS
 * remain the authoritative control — this is the UI layer.
 */
export function PartnerGuard({ children }: { children: ReactNode }) {
  const { userRole, loading } = useAuth();
  if (loading) {
    return <div className="p-8 text-sm text-gray-500">Loading…</div>;
  }
  if (!isPartnerOnlyAllowed(userRole)) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-12 text-center">
        <div className="w-12 h-12 rounded-full bg-gray-100 flex items-center justify-center mb-4">
          <Lock size={20} className="text-gray-400" />
        </div>
        <h2 className="text-base font-semibold text-[#182350]">Partner access only</h2>
        <p className="text-sm text-gray-500 mt-1 max-w-sm">
          The Practice workspace and Revenue Operations are restricted to Partners.
        </p>
      </div>
    );
  }
  return <>{children}</>;
}
