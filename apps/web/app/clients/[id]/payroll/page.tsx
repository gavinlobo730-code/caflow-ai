export default function PayrollPage() {
  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="bg-white rounded-xl border border-gray-100 p-10 text-center space-y-3">
        <div className="w-10 h-10 rounded-full bg-green-50 flex items-center justify-center mx-auto">
          <span className="text-green-500 text-lg">👥</span>
        </div>
        <h2 className="text-sm font-semibold text-gray-800">Payroll — Coming in Phase 1</h2>
        <p className="text-xs text-gray-400 max-w-sm mx-auto">
          Employee management, salary computation, TDS deduction, and payslip generation
          will be available in the next release.
        </p>
      </div>
    </div>
  );
}
