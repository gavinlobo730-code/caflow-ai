"use client";

import { FileText } from "lucide-react";

export default function DocumentsPage() {
  return (
    <div className="p-6 max-w-7xl mx-auto">
      <h1 className="text-xl font-semibold text-gray-900">Document Intelligence</h1>
      <p className="text-sm text-gray-500 mt-1">AI-powered extraction and risk analysis</p>
      <div className="mt-8 bg-gray-50 rounded-xl border border-gray-100 p-12 text-center">
        <FileText size={40} className="text-gray-300 mx-auto mb-3" />
        <p className="text-sm font-medium text-gray-600 mb-1">Coming in next sprint</p>
        <p className="text-xs text-gray-400">Document upload, OCR extraction, and risk analysis will be available here.</p>
      </div>
    </div>
  );
}
