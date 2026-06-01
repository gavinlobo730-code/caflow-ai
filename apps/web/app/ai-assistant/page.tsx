"use client";

import { Sparkles } from "lucide-react";

export default function AIAssistantPage() {
  return (
    <div className="p-6 max-w-7xl mx-auto">
      <h1 className="text-xl font-semibold text-gray-900">AI Copilot</h1>
      <p className="text-sm text-gray-500 mt-1">Powered by Claude — ask about clients, compliance, and tax law</p>
      <div className="mt-8 bg-gray-50 rounded-xl border border-gray-100 p-12 text-center">
        <Sparkles size={40} className="text-gray-300 mx-auto mb-3" />
        <p className="text-sm font-medium text-gray-600 mb-1">Coming in next sprint</p>
        <p className="text-xs text-gray-400">AI-powered assistant for Indian tax law, compliance queries, and client insights.</p>
      </div>
    </div>
  );
}
