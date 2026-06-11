export default function TaxPage() {
  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-10 text-center space-y-3">
        <div className="w-10 h-10 rounded-full bg-blue-50 flex items-center justify-center mx-auto">
          <span className="text-blue-500 text-lg">📋</span>
        </div>
        <h2 className="text-sm font-semibold text-[#1E293B]">Income Tax — Coming in Phase 1</h2>
        <p className="text-xs text-[#94A3B8] max-w-sm mx-auto">
          ITR preparation, advance tax computation, and capital gains tracking
          will be available in the next release.
        </p>
      </div>
    </div>
  );
}
