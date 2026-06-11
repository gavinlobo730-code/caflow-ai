import ExportsPageClient from "./_page";

export function generateStaticParams() {
  return [{ id: "_placeholder", engagementId: "_placeholder" }];
}

export default function ExportsPage() {
  return <ExportsPageClient />;
}
