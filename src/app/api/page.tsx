import type { Metadata } from "next";
import { Terminal, Play, HelpCircle } from "lucide-react";

export const metadata: Metadata = {
  title: "API Documentation",
  description: "Access datasets programmatically using standard CKAN API endpoints. Documentation for developers, researchers, and data integration engines.",
};

export default function ApiDocsPage() {
  return (
    <div className="container mx-auto px-4 py-12 max-w-4xl">
      <div className="mb-12">
        <h1 className="text-4xl font-extrabold text-slate-900 mb-4 tracking-tight">API Documentation</h1>
        <p className="text-lg text-slate-600 leading-relaxed">
          Nigeria Open Data is powered by a developer-first, open-access API backend. You can programmatically query datasets, files, and organizations using standard CKAN Action API calls.
        </p>
      </div>

      <div className="space-y-12">
        
        {/* Connection details */}
        <section className="bg-slate-900 text-slate-100 rounded-3xl p-8 shadow-sm">
          <h2 className="text-xl font-bold mb-4 flex items-center gap-2 text-white">
            <Terminal className="text-primary-400 w-5 h-5" /> Base API Endpoint
          </h2>
          <p className="text-slate-400 mb-4">
            The base URL for all REST API transactions is:
          </p>
          <code className="block bg-slate-950 p-4 rounded-xl text-primary-300 font-mono text-sm border border-slate-800 break-all select-all">
            http://localhost:5000/api/3/action
          </code>
        </section>

        {/* Endpoint 1 */}
        <section className="space-y-4">
          <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Play className="text-primary-600 w-5 h-5" /> Search Datasets
          </h2>
          <p className="text-slate-600 leading-relaxed">
            Query and filter metadata of all active public datasets using keywords, formats, or organizations.
          </p>
          <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
            <div className="bg-slate-50 border-b border-slate-200 px-6 py-4 flex items-center justify-between">
              <span className="bg-emerald-50 text-emerald-700 text-xs font-bold px-2.5 py-1 rounded-md uppercase tracking-wider">GET</span>
              <span className="font-mono text-sm text-slate-600">/package_search</span>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <h4 className="text-sm font-semibold text-slate-900 uppercase tracking-wider mb-2">Query Parameters</h4>
                <ul className="text-sm space-y-2 text-slate-600">
                  <li><code className="text-pink-600 font-semibold font-mono">q</code> (string): Full-text keyword search.</li>
                  <li><code className="text-pink-600 font-semibold font-mono">fq</code> (string): Filter queries, e.g., <code className="font-mono bg-slate-50 px-1.5 py-0.5 rounded border">res_format:CSV</code>.</li>
                  <li><code className="text-pink-600 font-semibold font-mono">rows</code> (integer): Number of results to return (max 100).</li>
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold text-slate-900 uppercase tracking-wider mb-2">Example curl Request</h4>
                <pre className="bg-slate-950 text-slate-200 p-4 rounded-xl font-mono text-xs overflow-x-auto">
{`curl -s "http://localhost:5000/api/3/action/package_search?q=population&rows=2"`}
                </pre>
              </div>
            </div>
          </div>
        </section>

        {/* Endpoint 2 */}
        <section className="space-y-4">
          <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Play className="text-primary-600 w-5 h-5" /> Get Dataset Details
          </h2>
          <p className="text-slate-600 leading-relaxed">
            Retrieve complete schema details, publisher organization, metadata update logs, and resources (CSV, PDF) for a single dataset.
          </p>
          <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
            <div className="bg-slate-50 border-b border-slate-200 px-6 py-4 flex items-center justify-between">
              <span className="bg-emerald-50 text-emerald-700 text-xs font-bold px-2.5 py-1 rounded-md uppercase tracking-wider">GET</span>
              <span className="font-mono text-sm text-slate-600">/package_show</span>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <h4 className="text-sm font-semibold text-slate-900 uppercase tracking-wider mb-2">Query Parameters</h4>
                <ul className="text-sm space-y-2 text-slate-600">
                  <li><code className="text-pink-600 font-semibold font-mono">id</code> (string): The slug or UUID of the dataset (e.g. <code className="font-mono">nigeria-air-quality-index</code>).</li>
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-semibold text-slate-900 uppercase tracking-wider mb-2">Example JavaScript Request</h4>
                <pre className="bg-slate-950 text-slate-200 p-4 rounded-xl font-mono text-xs overflow-x-auto">
{`fetch('http://localhost:5000/api/3/action/package_show?id=nigeria-air-quality-index')
  .then(res => res.json())
  .then(data => console.log(data.result));`}
                </pre>
              </div>
            </div>
          </div>
        </section>

        {/* Integration Support */}
        <section className="bg-primary-50 rounded-3xl p-8 border border-primary-100 flex items-start gap-4">
          <HelpCircle className="text-primary-600 w-6 h-6 shrink-0 mt-1" />
          <div>
            <h3 className="text-lg font-bold text-slate-900 mb-1">Developer Terms of Use</h3>
            <p className="text-slate-600 text-sm leading-relaxed">
              API keys are not required for read-only query operations. However, rate limits are applied to ensure fair resource distribution. For bulk data scraping, we encourage scheduling queries during off-peak hours or referencing the daily static exports.
            </p>
          </div>
        </section>

      </div>
    </div>
  );
}
