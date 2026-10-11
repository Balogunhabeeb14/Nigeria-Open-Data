import type { Metadata } from "next";
import { Terminal, Play, HelpCircle } from "lucide-react";

export const metadata: Metadata = {
  title: "API Documentation",
  description: "Read the catalogue and the data programmatically. Open, read-only, no key needed.",
};

const BASE = "/api/3/action";

const endpoints = [
  {
    title: "Search datasets",
    path: "/package_search",
    summary: "Find datasets by words in their title or description, and filter by topic, publisher or file format.",
    params: [
      ["q", "Search words, for example population or \"school enrolment\"."],
      ["fq", "Filters joined with AND: groups:health, organization:world-bank, res_format:CSV."],
      ["rows", "How many results to return (default 10, up to 1,000)."],
      ["start", "How many results to skip, for paging."],
    ],
    example: `curl "https://<this-site>${BASE}/package_search?q=population&rows=5"`,
    returns: "result.count is the total number of matches; result.results holds this page of datasets.",
  },
  {
    title: "Get one dataset",
    path: "/package_show",
    summary: "Everything about one dataset: description, publisher, licence, source, coverage and its files.",
    params: [["id", "The dataset's name as it appears in its page address, for example ng-wb-sp-pop-totl."]],
    example: `curl "https://<this-site>${BASE}/package_show?id=ng-wb-sp-pop-totl"`,
    returns: "result.resources lists the files. A resource with datastore_active: true can be queried row by row.",
  },
  {
    title: "Read a dataset's rows",
    path: "/datastore_search",
    summary: "The values themselves, as JSON. For a time series the rows come oldest first.",
    params: [
      ["resource_id", "The id of a resource from package_show."],
      ["limit", "How many rows to return (default 100)."],
      ["offset", "How many rows to skip, for paging."],
    ],
    example: `curl "https://<this-site>${BASE}/datastore_search?resource_id=<resource-id>&limit=500"`,
    returns: "result.records holds the rows, result.fields the columns, result.total the row count.",
  },
  {
    title: "List topics and publishers",
    path: "/group_list  ·  /organization_list",
    summary: "The topics and publishers on the site, each with the number of datasets it holds.",
    params: [["all_fields", "Set to true for titles, descriptions and dataset counts; otherwise names only."]],
    example: `curl "https://<this-site>${BASE}/group_list?all_fields=true"`,
    returns: "result is a list, busiest first.",
  },
];

export default function ApiDocsPage() {
  return (
    <div className="container mx-auto px-4 py-12 max-w-4xl">
      <div className="mb-12">
        <h1 className="text-4xl font-extrabold text-slate-900 mb-4 tracking-tight">API Documentation</h1>
        <p className="text-lg text-slate-600 leading-relaxed">
          Everything on this site can also be read by a program. The API is open and read-only:
          no account or key is needed. It follows the conventions of the CKAN Action API, which many
          open data portals use, so existing CKAN client libraries work with it.
        </p>
      </div>

      <div className="space-y-12">
        <section className="bg-slate-900 text-slate-100 rounded-3xl p-8 shadow-sm">
          <h2 className="text-xl font-bold mb-4 flex items-center gap-2 text-white">
            <Terminal className="text-primary-400 w-5 h-5" /> Base address
          </h2>
          <p className="text-slate-400 mb-4">
            Add each path below to this site&rsquo;s own address followed by:
          </p>
          <code className="block bg-slate-950 p-4 rounded-xl text-primary-300 font-mono text-sm border border-slate-800 break-all select-all">
            {BASE}
          </code>
          <p className="text-slate-400 mt-4 text-sm">
            Every response is JSON with a <code className="font-mono">success</code> flag and the answer under <code className="font-mono">result</code>.
          </p>
        </section>

        {endpoints.map((endpoint) => (
          <section key={endpoint.path} className="space-y-4">
            <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
              <Play className="text-primary-600 w-5 h-5" /> {endpoint.title}
            </h2>
            <p className="text-slate-600 leading-relaxed">{endpoint.summary}</p>
            <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
              <div className="bg-slate-50 border-b border-slate-200 px-6 py-4 flex items-center justify-between gap-4">
                <span className="bg-emerald-50 text-emerald-700 text-xs font-bold px-2.5 py-1 rounded-md uppercase tracking-wider">GET</span>
                <span className="font-mono text-sm text-slate-600 break-all text-right">{endpoint.path}</span>
              </div>
              <div className="p-6 space-y-4">
                <div>
                  <h3 className="text-sm font-semibold text-slate-900 uppercase tracking-wider mb-2">Parameters</h3>
                  <ul className="text-sm space-y-2 text-slate-600">
                    {endpoint.params.map(([name, text]) => (
                      <li key={name}>
                        <code className="text-pink-700 font-semibold font-mono">{name}</code>: {text}
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-slate-900 uppercase tracking-wider mb-2">Example</h3>
                  <pre className="bg-slate-950 text-slate-200 p-4 rounded-xl font-mono text-xs overflow-x-auto">{endpoint.example}</pre>
                </div>
                <p className="text-sm text-slate-600">{endpoint.returns}</p>
              </div>
            </div>
          </section>
        ))}

        <section className="space-y-4">
          <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Play className="text-primary-600 w-5 h-5" /> Download a whole table
          </h2>
          <p className="text-slate-600 leading-relaxed">
            Each data table has a CSV address, shown as the <code className="font-mono">url</code> of its resource in{" "}
            <code className="font-mono">package_show</code>. It is the same file the Download button gives you.
          </p>
          <pre className="bg-slate-950 text-slate-200 p-4 rounded-xl font-mono text-xs overflow-x-auto">{`curl -O "https://<this-site>/datastore/dump/<resource-id>"`}</pre>
        </section>

        <section className="bg-primary-50 rounded-3xl p-8 border border-primary-100 flex items-start gap-4">
          <HelpCircle className="text-primary-600 w-6 h-6 shrink-0 mt-1" />
          <div>
            <h3 className="text-lg font-bold text-slate-900 mb-1">Using the data</h3>
            <p className="text-slate-600 text-sm leading-relaxed">
              Each dataset carries its own licence and names its original publisher; follow that licence
              and credit that publisher when you reuse the data. Please keep automated requests modest so
              the service stays quick for everyone, and prefer the CSV download when you need a whole table.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
