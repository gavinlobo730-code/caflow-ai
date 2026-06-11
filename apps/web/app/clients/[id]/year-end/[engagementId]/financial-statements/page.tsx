import FinancialStatementsPageClient from "./_page";

export function generateStaticParams() {
  return [{ id: "_placeholder", engagementId: "_placeholder" }];
}

export default function FinancialStatementsPage() {
  return <FinancialStatementsPageClient />;
}
