import EditInvoicePageClient from "./_page";

// Static-export requires generateStaticParams for the dynamic [invoiceId] segment;
// the real id comes from the URL at runtime (client-rendered SPA + _redirects).
export function generateStaticParams() {
  return [{ id: "_placeholder", invoiceId: "_placeholder" }];
}

export default function EditInvoicePage() {
  return <EditInvoicePageClient />;
}
