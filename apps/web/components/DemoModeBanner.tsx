"use client";

import { FlaskConical } from "lucide-react";
import { DEMO_BANNER_TITLE, DEMO_BANNER_BODY } from "@/lib/filing/demoFiling";

/**
 * The required DEMO MODE banner. Shown on every screen of the filing simulation
 * so a user can never believe a real filing occurred.
 */
export default function DemoModeBanner() {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3">
      <FlaskConical size={18} className="text-amber-600 mt-0.5 shrink-0" />
      <div>
        <p className="text-sm font-bold uppercase tracking-wide text-amber-800">{DEMO_BANNER_TITLE}</p>
        <p className="text-xs text-amber-700 mt-0.5">{DEMO_BANNER_BODY}</p>
      </div>
    </div>
  );
}
