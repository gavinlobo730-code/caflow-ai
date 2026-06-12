import HealthDetailClient from "./HealthDetailClient";

export function generateStaticParams() {
  return [{ client_id: "_placeholder" }];
}

export default function HealthDetailPage() {
  return <HealthDetailClient />;
}
