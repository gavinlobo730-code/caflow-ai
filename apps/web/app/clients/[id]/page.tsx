import { redirect } from "next/navigation";

interface Props {
  params: Promise<{ id: string }>;
}

export function generateStaticParams() {
  return [{ id: "_placeholder" }];
}

export default async function ClientRootPage({ params }: Props) {
  const { id } = await params;
  redirect(`/clients/${id}/overview`);
}
