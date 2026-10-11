import { fetchDataset, fetchDataTable, findDataResource, getExtra } from "@/lib/ckan";
import { toSeries } from "@/lib/series";
import SeriesChart from "@/components/data/SeriesChart";
import DataPreview from "@/components/data/DataPreview";
import { notFound } from "next/navigation";
import Link from "next/link";
import { ChevronLeft, Building2, Calendar, FileText, Database, LineChart } from "lucide-react";
import DownloadButton from "@/components/DownloadButton";

import type { Metadata } from "next";

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const resolvedParams = await params;
  const slug = resolvedParams.slug;
  const dataset = await fetchDataset(slug);
  
  if (!dataset) {
    return {
      title: "Dataset Not Found",
    };
  }

  return {
    title: `${dataset.title || dataset.name} | Dataset`,
    description: (dataset.notes || "").split(/\n\s*\n/)[0].slice(0, 200) || `Download ${dataset.title || dataset.name} from Naija Open Data.`,
  };
}

export default async function DatasetDetail({ params }: { params: Promise<{ slug: string }> }) {
  const resolvedParams = await params;
  const slug = resolvedParams.slug;
  const dataset = await fetchDataset(slug);

  if (!dataset) {
    notFound();
  }

  // Provenance written by the pipeline. Shown as stated by the source; when a
  // source gave no licence we say so instead of implying the data is open.
  const licence =
    getExtra(dataset, "licence_name") ||
    (dataset.license_id && dataset.license_id !== "notspecified" ? dataset.license_title : undefined) ||
    "Not specified by the source";
  const licenceUrl = getExtra(dataset, "licence_url");
  const source = getExtra(dataset, "source");
  const sourceUrl = getExtra(dataset, "source_url") || dataset.url;
  const coverageStart = getExtra(dataset, "temporal_start");
  const coverageEnd = getExtra(dataset, "temporal_end");
  const hostedExternally = getExtra(dataset, "hosted") === "external";
  const unit = getExtra(dataset, "unit");

  // The rows themselves, when the catalogue holds them (not for listings
  // whose files live on another portal).
  const dataResource = findDataResource(dataset);
  const table = dataResource?.id ? await fetchDataTable(dataResource.id) : null;
  const series = table ? toSeries(table) : null;
  const paragraphs = (dataset.notes || "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);

  return (
    <div className="container mx-auto px-4 py-12">
      {/* Back link */}
      <Link href="/datasets" className="inline-flex items-center text-primary-600 hover:text-primary-700 font-medium mb-8 transition-colors group">
        <ChevronLeft className="w-5 h-5 mr-1 transform group-hover:-translate-x-1 transition-transform" /> Back to Datasets
      </Link>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* Main Content (Title, Description, Resources) */}
        <div className="lg:col-span-2 space-y-8">
          
          {/* Header */}
          <div className="bg-white p-8 md:p-10 rounded-3xl shadow-sm border border-slate-100">
            <h1 className="text-3xl md:text-4xl font-bold text-slate-900 mb-4">{dataset.title || dataset.name}</h1>
            {paragraphs.length === 0 ? (
              <p className="text-lg text-slate-600 leading-relaxed">No description provided.</p>
            ) : (
              <div className="space-y-3">
                {paragraphs.map((text, i) => (
                  <p key={i} className={i === 0 ? "text-lg text-slate-700 leading-relaxed" : "text-sm text-slate-500 leading-relaxed"}>
                    {text}
                  </p>
                ))}
              </div>
            )}
          </div>

          {/* The data: chart, then every row */}
          {table && table.records.length > 0 && (
            <div className="bg-white p-8 md:p-10 rounded-3xl shadow-sm border border-slate-100">
              <h2 className="text-2xl font-bold text-slate-900 mb-1 flex items-center gap-2">
                <LineChart className="w-6 h-6 text-primary-600" /> Data
              </h2>
              {series ? (
                <>
                  <p className="text-sm text-slate-500 mb-6">
                    {[series.place, unit || series.unit, `${series.points[0].period} to ${series.points[series.points.length - 1].period}`]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                  <SeriesChart series={series} label={dataset.title || dataset.name} />
                  <h3 className="text-base font-semibold text-slate-900 mt-8 mb-3">All values</h3>
                </>
              ) : (
                <p className="text-sm text-slate-500 mb-6">
                  This table covers more than one place or has no single time series, so it is shown as a table.
                </p>
              )}
              <DataPreview table={table} />
            </div>
          )}

          {/* Resources */}
          <div className="bg-white p-8 md:p-10 rounded-3xl shadow-sm border border-slate-100">
            <h2 className="text-2xl font-bold text-slate-900 mb-6 flex items-center gap-2">
              <Database className="w-6 h-6 text-primary-600" /> {hostedExternally ? "Files at the source" : "Download"}
            </h2>
            
            {dataset.resources && dataset.resources.length > 0 ? (
              <div className="space-y-4">
                {dataset.resources.map((res, idx) => (
                  <div key={idx} className="flex flex-col sm:flex-row sm:items-center justify-between p-6 border border-slate-100 rounded-2xl bg-slate-50 hover:bg-white hover:shadow-md transition-all">
                    <div className="flex items-start gap-4 mb-4 sm:mb-0 min-w-0">
                      <div className="bg-primary-100 text-primary-700 px-3 py-1 rounded-lg font-bold text-sm uppercase tracking-widest mt-1">
                        {res.format || 'DATA'}
                      </div>
                      <div className="min-w-0">
                        <h3 className="font-bold text-slate-900 text-lg break-words">{res.name || `Resource ${idx + 1}`}</h3>
                        <p className="text-sm text-slate-500 truncate max-w-full sm:max-w-xs md:max-w-md">
                          {res.url.startsWith("/") ? (res.description || "Every row and column, as CSV") : res.url}
                        </p>
                      </div>
                    </div>
                    <DownloadButton 
                      url={res.url} 
                      filename={`${dataset.name}-${res.name || idx}.${res.format?.toLowerCase() || 'csv'}`} 
                      className="flex items-center justify-center gap-2 bg-primary-600 text-white px-6 py-3 rounded-xl hover:bg-primary-700 font-semibold transition-colors shadow-sm"
                    />
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-8 text-center text-slate-500 bg-slate-50 rounded-2xl border border-slate-100 border-dashed">
                No files available for download.
              </div>
            )}
          </div>
        </div>

        {/* Sidebar (Metadata) */}
        <aside className="space-y-6">
          <div className="bg-white p-8 rounded-3xl shadow-sm border border-slate-100">
            <h3 className="text-lg font-bold text-slate-900 mb-6 border-b border-slate-100 pb-4">Metadata</h3>
            
            <ul className="space-y-6">
              <li className="flex items-start gap-4">
                <div className="bg-slate-50 p-2 rounded-lg text-slate-400">
                  <Building2 className="w-5 h-5" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-1">Publisher</p>
                  <p className="font-medium text-slate-900">{dataset.organization?.title || 'Unknown Publisher'}</p>
                </div>
              </li>
              
              <li className="flex items-start gap-4">
                <div className="bg-slate-50 p-2 rounded-lg text-slate-400">
                  <Calendar className="w-5 h-5" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-1">Last Updated</p>
                  <p className="font-medium text-slate-900">{new Date(dataset.metadata_modified).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })}</p>
                </div>
              </li>

              <li className="flex items-start gap-4">
                <div className="bg-slate-50 p-2 rounded-lg text-slate-400">
                  <FileText className="w-5 h-5" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-1">License</p>
                  {licenceUrl ? (
                    <a href={licenceUrl} target="_blank" rel="noopener noreferrer" className="font-medium text-primary-700 hover:underline">
                      {licence}
                    </a>
                  ) : (
                    <p className="font-medium text-slate-900">{licence}</p>
                  )}
                </div>
              </li>

              {(source || sourceUrl) && (
                <li className="flex items-start gap-4">
                  <div className="bg-slate-50 p-2 rounded-lg text-slate-400">
                    <Database className="w-5 h-5" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-1">Source</p>
                    {source && <p className="font-medium text-slate-900">{source}</p>}
                    {sourceUrl && (
                      <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="text-sm text-primary-700 hover:underline break-words">
                        View at the original source
                      </a>
                    )}
                    {hostedExternally && (
                      <p className="text-sm text-slate-500 mt-1">Files are hosted by the original portal.</p>
                    )}
                  </div>
                </li>
              )}

              {coverageStart && coverageEnd && (
                <li className="flex items-start gap-4">
                  <div className="bg-slate-50 p-2 rounded-lg text-slate-400">
                    <Calendar className="w-5 h-5" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-1">Coverage</p>
                    <p className="font-medium text-slate-900">
                      {coverageStart === coverageEnd ? coverageStart : `${coverageStart} to ${coverageEnd}`}
                    </p>
                  </div>
                </li>
              )}
            </ul>
          </div>
        </aside>

      </div>
    </div>
  );
}
