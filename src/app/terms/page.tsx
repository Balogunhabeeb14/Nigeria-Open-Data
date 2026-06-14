import type { Metadata } from "next";
import { Scale, FileText, AlertTriangle, CheckCircle } from "lucide-react";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "Read the rules, attribution guidelines, and terms governing dataset usage on the Nigeria Open Data Platform.",
};

export default function TermsPage() {
  return (
    <div className="container mx-auto px-4 py-12 max-w-3xl">
      <div className="mb-12 text-center md:text-left">
        <div className="bg-primary-50 w-16 h-16 rounded-2xl flex items-center justify-center mb-6 mx-auto md:mx-0">
          <Scale className="w-8 h-8 text-primary-600" />
        </div>
        <h1 className="text-4xl font-extrabold text-slate-900 mb-4 tracking-tight">Terms of Service</h1>
        <p className="text-lg text-slate-600 leading-relaxed">
          Last updated: June 13, 2026. These Terms govern your access and use of the Nigeria Open Data Platform.
        </p>
      </div>

      <div className="prose prose-slate max-w-none space-y-8 text-slate-600 leading-relaxed">
        
        <section className="space-y-3">
          <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <FileText className="w-5 h-5 text-primary-600" /> Terms of Data Usage
          </h2>
          <p>
            Unless explicitly marked otherwise, all datasets uploaded to this catalog are licensed under open, public-domain standards. Users are free to:
          </p>
          <ul className="list-disc pl-6 space-y-2">
            <li>Download, print, distribute, and reproduce dataset resources.</li>
            <li>Analyze, mash up, and integrate data points into commercial or non-commercial applications.</li>
            <li>Provide clear attribution back to the publisher agency of the source data.</li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-primary-600" /> Disclaimer of Warranties
          </h2>
          <p>
            Data is provided on an "as-is" and "as-available" basis. We make no guarantees regarding the completeness, accuracy, or continuous availability of any information hosted on this platform. Use of public datasets is at the sole discretion and risk of the user.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <CheckCircle className="w-5 h-5 text-primary-600" /> Fair Use & Scraping
          </h2>
          <p>
            Accessing data programmatically is permitted and encouraged via our API. However, server requests must conform to reasonable limits to avoid compromising performance for other public users. Unauthorized attempts to execute denial-of-service queries may result in rate-limit restrictions or IP blocking.
          </p>
        </section>

      </div>
    </div>
  );
}
