import EditSalesCreditNotePageClient from "./_page";

// Static-export requires generateStaticParams for the dynamic [cnId] segment;
// the real id comes from the URL at runtime (client-rendered SPA + _redirects).
export function generateStaticParams() {
  return [{ id: "_placeholder", cnId: "_placeholder" }];
}

export default function EditSalesCreditNotePage() {
  return <EditSalesCreditNotePageClient />;
}
