import AdjustmentsPageClient from "./_page";

export function generateStaticParams() {
  return [{ id: "_placeholder", engagementId: "_placeholder" }];
}

export default function AdjustmentsPage() {
  return <AdjustmentsPageClient />;
}
