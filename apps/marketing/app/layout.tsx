import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], display: "swap" });

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
  openGraph: {
    title: "PracticeSync — AI practice management for Indian CAs",
    description:
      "Compliance, accounting, payroll and clients in one AI-first platform built for Indian CA firms.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={inter.className}>{children}</body>
    </html>
  );
}
