import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    template: "%s | Nigeria Open Data Platform",
    default: "Nigeria Open Data Platform - Trusted Public & Global Datasets",
  },
  description: "Access, explore, and download verified public and government datasets from Nigeria, the UK, the US, and global repositories in accessible formats like CSV and JSON.",
  keywords: ["Nigeria Open Data", "Global Datasets", "UK Open Data", "US Open Data", "CSV Datasets", "Government Data", "Demographic Data", "Public Data API"],
  authors: [{ name: "Nigeria Open Data Team" }],
  creator: "Nigeria Open Data Platform",
  publisher: "Nigeria Open Data Platform",
  openGraph: {
    type: "website",
    locale: "en_NG",
    url: "http://localhost:3000",
    siteName: "Nigeria Open Data Platform",
    title: "Nigeria Open Data Platform - Public & Global Datasets",
    description: "Discover and download verified public data from Nigeria, the United States, the United Kingdom, and global institutions in accessible formats.",
  },
  twitter: {
    card: "summary_large_image",
    title: "Nigeria Open Data Platform",
    description: "Discover and download verified public data from Nigeria, the United States, the United Kingdom, and global institutions in accessible formats.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} antialiased`}>
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
