import EntityDetailClient from "./EntityDetailClient";

export function generateStaticParams() {
  return [{ entity_id: "_placeholder" }];
}

export default function EntityDetailPage() {
  return <EntityDetailClient />;
}
