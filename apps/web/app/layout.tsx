import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { Toaster } from "@/components/ui/toaster";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "CAflow AI",
  description: "AI-powered practice management for Indian Chartered Accountants",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <div className="flex h-screen bg-gray-50">
          <Sidebar />
          <main className="flex-1 overflow-auto">
            {children}
          </main>
        </div>
        <Toaster />
      </body>
    </html>
  );
}
