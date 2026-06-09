export default function ReportsPage() {
  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="bg-white rounded-xl border border-gray-100 p-10 text-center space-y-3">
        <div className="w-10 h-10 rounded-full bg-purple-50 flex items-center justify-center mx-auto">
          <span className="text-purple-500 text-lg">📊</span>
        </div>
        <h2 className="text-sm font-semibold text-gray-800">Reports — Coming in Phase 1</h2>
        <p className="text-xs text-gray-400 max-w-sm mx-auto">
          P&amp;L, Balance Sheet, Cash Flow, and management reports in Schedule III format
          will be available in the next release.
        </p>
      </div>
    </div>
  );
}
