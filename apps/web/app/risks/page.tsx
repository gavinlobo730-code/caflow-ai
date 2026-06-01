"use client";

import { Shield } from "lucide-react";

export default function RisksPage() {
  return (
    <div className="p-6 max-w-7xl mx-auto">
      <h1 className="text-xl font-semibold text-gray-900">Risk Intelligence</h1>
      <p className="text-sm text-gray-500 mt-1">Real-time risk monitoring across all clients</p>
      <div className="mt-8 bg-gray-50 rounded-xl border border-gray-100 p-12 text-center">
        <Shield size={40} className="text-gray-300 mx-auto mb-3" />
        <p className="text-sm font-medium text-gray-600 mb-1">Coming in next sprint</p>
        <p className="text-xs text-gray-400">Automated risk detection for GST compliance, ITR mismatches, and pending filings.</p>
      </div>
    </div>
  );
}
