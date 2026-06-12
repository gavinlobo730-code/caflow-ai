"use client";

import { SlidersHorizontal } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

export default function OverrideControlsPage() {

  // Overrides are per-client — this page shows a brief explanation and links to health dashboard
  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center gap-3">
        <SlidersHorizontal size={20} className="text-emerald-400" />
        <div>
          <h1 className="text-base font-semibold text-white">Override Controls</h1>
          <p className="text-xs text-slate-400">Manage health score overrides per client</p>
        </div>
      </div>
      <Card className="bg-gray-800 border-gray-700">
        <CardContent className="p-6 space-y-4">
          <p className="text-sm text-slate-300">
            Health score overrides are managed at the individual client level.
            Navigate to a client&apos;s Health tab to add or remove overrides for specific dimensions.
          </p>
          <ul className="space-y-2 text-sm text-slate-400">
            <li className="flex items-start gap-2">
              <span className="text-emerald-400 mt-0.5">→</span>
              Go to <strong className="text-white">Clients</strong> and select a client
            </li>
            <li className="flex items-start gap-2">
              <span className="text-emerald-400 mt-0.5">→</span>
              Navigate to the <strong className="text-white">Health</strong> tab
            </li>
            <li className="flex items-start gap-2">
              <span className="text-emerald-400 mt-0.5">→</span>
              Click <strong className="text-white">Add Override</strong> to set a dimension-level override with a reason and expiry
            </li>
          </ul>
          <p className="text-xs text-slate-500 mt-2">
            Overrides allow CAs to manually adjust health dimension scores when the automated calculation doesn&apos;t reflect the true client risk — e.g., a compliance issue is already being resolved.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
