"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { Building2 } from "lucide-react";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate, formatPaise } from "@/lib/services/formatting";
import { getAllBankStatements } from "@/lib/data/bankStatements";
import type { BankStatement } from "@/lib/data/bankStatements";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  reviewed: "bg-blue-100 text-blue-700",
  posted: "bg-green-100 text-green-700",
};

function LoadingSkeleton() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4 animate-pulse">
      <div className="h-8 bg-gray-200 rounded w-64" />
      <div className="h-64 bg-gray-100 rounded-xl" />
    </div>
  );
}

export default function BankStatementsPage() {
  const [statements, setStatements] = useState<BankStatement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAllBankStatements()
      .then(setStatements)
      .catch(err => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingSkeleton />;

  if (error) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Bank Statements</h1>
          <p className="text-sm text-gray-500 mt-0.5">Allocate and post bank transactions to the accounting ledger</p>
        </div>
        <Link
          href="/accounting/bank-import"
          className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700 transition-colors"
        >
          + Import Statement
        </Link>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">{statements.length} statement{statements.length !== 1 ? "s" : ""}</CardTitle>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-xs text-gray-400">
                <th className="px-5 py-3 text-left font-semibold">Bank</th>
                <th className="px-3 py-3 text-left font-semibold">Account</th>
                <th className="px-3 py-3 text-left font-semibold">Period</th>
                <th className="px-3 py-3 text-right font-semibold">Debits</th>
                <th className="px-3 py-3 text-right font-semibold">Credits</th>
                <th className="px-3 py-3 text-center font-semibold">Rows</th>
                <th className="px-3 py-3 text-left font-semibold">Status</th>
                <th className="px-5 py-3 text-left font-semibold">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {statements.map(s => (
                <tr key={s.id} className="hover:bg-gray-50">
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2">
                      <Building2 size={15} className="text-gray-400 shrink-0" />
                      <span className="text-sm font-medium text-gray-900">{s.bank_name}</span>
                    </div>
                  </td>
                  <td className="px-3 py-3 text-xs text-gray-500 font-mono">{s.account_number ?? "—"}</td>
                  <td className="px-3 py-3 text-xs text-gray-500 whitespace-nowrap">
                    {formatDate(s.statement_from)} – {formatDate(s.statement_to)}
                  </td>
                  <td className="px-3 py-3 text-sm text-right tabular-nums text-red-600">
                    {formatPaise(s.total_debits_paise)}
                  </td>
                  <td className="px-3 py-3 text-sm text-right tabular-nums text-green-600">
                    {formatPaise(s.total_credits_paise)}
                  </td>
                  <td className="px-3 py-3 text-xs text-center text-gray-500">{s.row_count}</td>
                  <td className="px-3 py-3">
                    <Badge className={`text-xs ${STATUS_COLORS[s.import_status] ?? "bg-gray-100 text-gray-600"}`}>
                      {s.import_status}
                    </Badge>
                  </td>
                  <td className="px-5 py-3">
                    <Link
                      href={`/accounting/bank-statements/${s.id}`}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      Allocate →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {statements.length === 0 && (
            <div className="text-center py-12 text-sm text-gray-400">
              No bank statements imported yet.{" "}
              <Link href="/accounting/bank-import" className="text-blue-600 hover:underline">
                Import one now →
              </Link>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
