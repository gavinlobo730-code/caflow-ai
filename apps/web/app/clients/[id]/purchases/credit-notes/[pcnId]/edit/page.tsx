import EditPurchaseCreditNotePageClient from "./_page";

// Static-export requires generateStaticParams for the dynamic [pcnId] segment;
// the real id comes from the URL at runtime (client-rendered SPA + _redirects).
export function generateStaticParams() {
  return [{ id: "_placeholder", pcnId: "_placeholder" }];
}

export default function EditPurchaseCreditNotePage() {
  return <EditPurchaseCreditNotePageClient />;
}
