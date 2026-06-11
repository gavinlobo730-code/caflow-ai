export default function YearEndPage() {
  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="bg-[#131620] rounded-xl border border-white/[0.05] p-10 text-center space-y-3">
        <div className="w-10 h-10 rounded-full bg-amber-50 flex items-center justify-center mx-auto">
          <span className="text-amber-500 text-lg">📅</span>
        </div>
        <h2 className="text-sm font-semibold text-white/75">Year End Close — Coming in Phase 1</h2>
        <p className="text-xs text-white/30 max-w-sm mx-auto">
          Year-end closing entries, depreciation schedules, and statutory audit support
          will be available in the next release.
        </p>
      </div>
    </div>
  );
}
