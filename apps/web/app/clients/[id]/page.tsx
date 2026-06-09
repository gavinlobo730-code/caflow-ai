import { redirect } from "next/navigation";

interface Props {
  params: { id: string };
}

export function generateStaticParams() {
  return [{ id: "_placeholder" }];
}

export default function ClientRootPage({ params }: Props) {
  redirect(`/clients/${params.id}/overview`);
}
