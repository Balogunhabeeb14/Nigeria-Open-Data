import type { Metadata } from "next";
import { contactEmail, REPO_URL } from "@/lib/site";
import { Shield, Lock, Eye, CheckCircle } from "lucide-react";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "Learn how we collect, process, and protect user data on the Naija Open Data Platform.",
};

export const dynamic = "force-dynamic";

export default function PrivacyPage() {
  const email = contactEmail();
  return (
    <div className="container mx-auto px-4 py-12 max-w-3xl">
      <div className="mb-12 text-center md:text-left">
        <div className="bg-primary-50 w-16 h-16 rounded-2xl flex items-center justify-center mb-6 mx-auto md:mx-0">
          <Shield className="w-8 h-8 text-primary-600" />
        </div>
        <h1 className="text-4xl font-extrabold text-slate-900 mb-4 tracking-tight">Privacy Policy</h1>
        <p className="text-lg text-slate-600 leading-relaxed">
          Last updated: June 13, 2026. This Privacy Policy details how we handle information collected from visitors of the Naija Open Data Platform.
        </p>
      </div>

      <div className="prose prose-slate max-w-none space-y-8 text-slate-600 leading-relaxed">
        
        <section className="space-y-3">
          <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Eye className="w-5 h-5 text-primary-600" /> Information We Collect
          </h2>
          <p>
            The Naija Open Data platform values transparency. As a public service portal, we do not require user registration or account creation for querying and downloading public files. The only data processed includes:
          </p>
          <ul className="list-disc pl-6 space-y-2">
            <li><strong>Technical Access Logs</strong>: Standard server logs containing anonymous IP addresses, browser agents, requested resource paths, and retrieval timestamps.</li>
            <li><strong>Analytics Metrics</strong>: Aggregated page visits and download frequency to assess dataset popularity and optimize caching.</li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Lock className="w-5 h-5 text-primary-600" /> Security Standards
          </h2>
          <p>
            We implement industry-standard encryption protocols (HTTPS/TLS) across all transmission paths to protect against interception. Raw data downloads and metadata indexes are stored on secured backend databases maintained by trusted partners.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <CheckCircle className="w-5 h-5 text-primary-600" /> Third-Party Content
          </h2>
          <p>
            Some dataset resources may link directly to external agency domains. We do not exercise operational control over external websites and encourage reviewing their respective policies upon redirection.
          </p>
        </section>

        <section className="bg-slate-50 border border-slate-200 rounded-2xl p-6">
          <h3 className="font-bold text-slate-900 mb-2">Questions & Inquiries</h3>
          <p className="text-sm">
            For questions regarding metadata licensing, privacy concerns, or data governance, {email ? (
              <>write to us at <a href={`mailto:${email}`} className="text-primary-600 hover:underline">{email}</a>.</>
            ) : (
              <>raise it on <a href={`${REPO_URL}/issues`} target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">the project&rsquo;s issue tracker</a>.</>
            )}
          </p>
        </section>

      </div>
    </div>
  );
}
