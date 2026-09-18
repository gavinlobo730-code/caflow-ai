import type { Metadata } from "next";
import { manrope } from "@/lib/fonts";
import { SITE_URL } from "@/lib/site";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "PracticeSync — AI practice management for Indian CAs",
    template: "%s · PracticeSync",
  },
  description:
    "One AI-first platform for Indian Chartered Accountants — GST, Income Tax, TDS and MCA compliance, accounting, payroll, client management and documents. Replace Tally, ClearTax, Winman and WhatsApp.",
  keywords: [
    "CA practice management software",
    "GST software India",
    "income tax filing software",
    "TDS return software",
    "chartered accountant software",
    "PracticeSync",
  ],
  /*
    `metadataBase` is what makes a RELATIVE image below resolve. Every consumer
    of these tags — WhatsApp, LinkedIn, Slack, iMessage — fetches the picture
    from its own servers against an absolute URL, so without a base there is
    nothing for `/og.jpg` to be relative TO and the preview is simply dropped.
  */
  metadataBase: new URL(SITE_URL),
  openGraph: {
    title: "PracticeSync — AI practice management for Indian CAs",
    description:
      "Compliance, accounting, payroll and clients in one place — the AI-first platform for Indian CA firms.",
    type: "website",
    siteName: "PracticeSync",
    locale: "en_IN",
    /*
      Rendered by scripts/build-og-image.mjs against the BUILT site, so the card
      is set in the pages' own Manrope and Instrument Serif and carries the real
      logo mark rather than a lookalike. `alt` is not decoration here: several
      clients read it out, and a screen reader meeting a shared link has nothing
      else to go on.
    */
    images: [
      {
        url: "/og.jpg",
        width: 1200,
        height: 630,
        alt: "PracticeSync — run your entire practice on one intelligent platform",
      },
    ],
  },
  /*
    Twitter/X reads its own tags and ignores the Open Graph ones where both are
    present, so the card type has to be stated or a 1200x630 image is shown as a
    small square thumbnail.
  */
  twitter: {
    card: "summary_large_image",
    title: "PracticeSync — AI practice management for Indian CAs",
    description:
      "Compliance, accounting, payroll and clients in one place — the AI-first platform for Indian CA firms.",
    images: ["/og.jpg"],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${manrope.variable} font-manrope`}>{children}</body>
    </html>
  );
}
