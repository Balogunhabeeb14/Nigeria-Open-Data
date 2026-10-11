import type { Metadata } from "next";
// Inter is bundled with the site (all its language subsets, so Yoruba, Igbo
// and Hausa letters use it too). Nothing is fetched from Google, at build
// time or in the visitor's browser.
import "@fontsource-variable/inter";
import "./globals.css";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

export const metadata: Metadata = {
  title: {
    template: "%s | Naija Open Data Platform",
    default: "Naija Open Data Platform - Public data about Nigeria in one place",
  },
  description: "Search, chart and download public data about Nigeria from many sources, each with its publisher, licence and last update.",
  keywords: ["Naija Open Data", "Nigeria open data", "Nigeria statistics", "Nigeria datasets", "CSV", "public data", "data API"],
  authors: [{ name: "Naija Open Data Team" }],
  creator: "Naija Open Data Platform",
  publisher: "Naija Open Data Platform",
  openGraph: {
    type: "website",
    locale: "en_NG",
    siteName: "Naija Open Data Platform",
    title: "Naija Open Data Platform",
    description: "Search, chart and download public data about Nigeria, with the source of every number shown.",
  },
  twitter: {
    card: "summary_large_image",
    title: "Naija Open Data Platform",
    description: "Search, chart and download public data about Nigeria, with the source of every number shown.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="antialiased">
      <body className="min-h-screen bg-slate-50 flex flex-col">
        <Header />
        <main className="flex-grow">
          {children}
        </main>
        <Footer />
      </body>
    </html>
  );
}
