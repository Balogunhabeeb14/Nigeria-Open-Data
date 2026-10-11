import Link from "next/link";
import type { Metadata } from "next";
import { fetchDataStatus, longDate } from "@/lib/site";

export const metadata: Metadata = {
  title: "Data status",
  description: "Which sources feed Naija Open Data, how many datasets each provides and when each was last updated.",
};

export const dynamic = "force-dynamic";

export default async function StatusPage() {
  const status = await fetchDataStatus();

  return (
    <div className="container mx-auto px-4 py-12 max-w-5xl">
      <h1 className="text-4xl font-extrabold text-slate-900 mb-4 tracking-tight">Data status</h1>
      <p className="text-lg text-slate-600 leading-relaxed mb-10 max-w-3xl">
        Where the data on this site comes from and how current it is. These figures are the
        platform&rsquo;s own record of what it loaded, updated every time it checks a source.
      </p>

      {!status || status.sources.length === 0 ? (
        <div className="bg-white p-10 rounded-3xl border border-slate-100 shadow-sm">
          <h2 className="text-xl font-bold text-slate-900 mb-2">
            {status ? "Nothing has been loaded yet" : "Status is not available right now"}
          </h2>
          <p className="text-slate-600">
            {status
              ? "The first load is still running. Check back in a few minutes."
              : "The data service could not be reached. The datasets already published are unaffected."}
          </p>
        </div>
      ) : (
        <>
          <dl className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-10">
            {[
              ["Datasets", status.totals.datasets.toLocaleString("en-GB")],
              ["Data points held", status.totals.observations.toLocaleString("en-GB")],
              ["Sources", status.totals.sources.toLocaleString("en-GB")],
              ["Last update", longDate(status.totals.last_successful_update)],
            ].map(([label, value]) => (
              <div key={label} className="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm">
                <dt className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-2">{label}</dt>
                <dd className="text-2xl font-bold text-slate-900">{value}</dd>
              </div>
            ))}
          </dl>

          <div className="bg-white rounded-3xl border border-slate-100 shadow-sm overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Sources, the datasets each provides and when each was last updated</caption>
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th scope="col" className="px-6 py-4 font-semibold text-slate-700">Source</th>
                  <th scope="col" className="px-6 py-4 font-semibold text-slate-700 text-right">Datasets</th>
                  <th scope="col" className="px-6 py-4 font-semibold text-slate-700">Last updated</th>
                  <th scope="col" className="px-6 py-4 font-semibold text-slate-700">Notes</th>
                </tr>
              </thead>
              <tbody>
                {status.sources.map((source) => {
                  const notes: string[] = [];
                  if (source.failed > 0) notes.push(`${source.failed} could not be loaded at the last attempt`);
                  if (source.awaiting_publication > 0) notes.push(`${source.awaiting_publication} waiting to be published`);
                  if (source.checked_without_data > 0) notes.push(`${source.checked_without_data} series have no Nigeria data at the source`);
                  return (
                    <tr key={source.id} className="border-t border-slate-100 align-top">
                      <th scope="row" className="px-6 py-4 text-left font-medium text-slate-900">
                        {source.name}
                        <span className="block text-xs font-normal text-slate-500 mt-0.5">{source.kind}</span>
                      </th>
                      <td className="px-6 py-4 text-right tabular-nums text-slate-900">{source.datasets.toLocaleString("en-GB")}</td>
                      <td className="px-6 py-4 text-slate-700 whitespace-nowrap">{longDate(source.last_successful_update)}</td>
                      <td className="px-6 py-4 text-slate-600">{notes.join(". ") || "No problems recorded"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      <p className="mt-8 text-sm text-slate-500">
        Each dataset page also shows its own source, licence and last update.{" "}
        <Link href="/datasets" className="text-primary-700 hover:underline">Browse the datasets</Link>.
      </p>
    </div>
  );
}
