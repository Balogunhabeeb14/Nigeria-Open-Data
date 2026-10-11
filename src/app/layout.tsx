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
    template: "%s | Nigeria Open Data Platform",
    default: "Nigeria Open Data Platform - Public data about Nigeria in one place",
  },
  description: "Search, chart and download public data about Nigeria from many sources, each with its publisher, licence and last update.",
  keywords: ["Nigeria open data", "Nigeria statistics", "Nigeria datasets", "CSV", "public data", "data API"],
  authors: [{ name: "Nigeria Open Data Team" }],
  creator: "Nigeria Open Data Platform",
  publisher: "Nigeria Open Data Platform",
  openGraph: {
    type: "website",
    locale: "en_NG",
    siteName: "Nigeria Open Data Platform",
    title: "Nigeria Open Data Platform",
    description: "Search, chart and download public data about Nigeria, with the source of every number shown.",
  },
  twitter: {
    card: "summary_large_image",
    title: "Nigeria Open Data Platform",
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
