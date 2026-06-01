"use client";

import { Bot } from "lucide-react";

export default function AssistantPage() {
  return (
    <div className="p-6 max-w-3xl mx-auto">
      <h1 className="text-xl font-semibold text-gray-900">GST Knowledge Assistant</h1>
      <p className="text-sm text-gray-500 mt-1">Ask anything about GST, ITR, or compliance</p>
      <div className="mt-8 bg-gray-50 rounded-xl border border-gray-100 p-12 text-center">
        <Bot size={40} className="text-gray-300 mx-auto mb-3" />
        <p className="text-sm font-medium text-gray-600 mb-1">Coming in next sprint</p>
        <p className="text-xs text-gray-400">AI-powered Q&amp;A for Indian tax law, GST rules, and compliance queries.</p>
      </div>
    </div>
  );
}
