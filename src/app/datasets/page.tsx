import { Suspense } from "react";
import { Download, Database, Search } from "lucide-react";
import Link from "next/link";
import { fetchDatasetPage, fetchOrganizations, fetchGroups } from "@/lib/ckan";
import DatasetFilters from "@/components/DatasetFilters";
import DatasetSearch from "@/components/DatasetSearch";
import DownloadButton from "@/components/DownloadButton";

import type { Metadata } from "next";

export async function generateMetadata({ searchParams }: { searchParams: Promise<{ format?: string, publisher?: string, q?: string, groups?: string }> }): Promise<Metadata> {
  const resolvedParams = await searchParams;
  const parts = [];
  if (resolvedParams.q) parts.push(`"${resolvedParams.q}"`);
  if (resolvedParams.groups) parts.push(resolvedParams.groups);
  if (resolvedParams.format) parts.push(resolvedParams.format);
  
  const titleString = parts.length > 0 
    ? `${parts.join(" · ")} | Datasets`
    : "Explore Datasets";

  return {
    title: titleString,
    description: "Search and download open-access public datasets from Nigeria, the US, the UK, and global sources in CSV, JSON, and XLSX formats.",
  };
}

const PAGE_SIZE = 20;

export default async function DatasetsPage({ searchParams }: { searchParams: Promise<{ format?: string, publisher?: string, q?: string, groups?: string, page?: string }> }) {
  const resolvedParams = await searchParams;
  const format = resolvedParams.format || "";
  const publisher = resolvedParams.publisher || "";
  const group = resolvedParams.groups || "";
  const query = resolvedParams.q || "";
  
  // Construct filter query for CKAN
  const fqParts = [];
  if (format) fqParts.push(`res_format:${format}`);
  if (publisher) fqParts.push(`organization:${publisher}`);
  if (group) fqParts.push(`groups:${group}`);
  const filterQuery = fqParts.join(' AND ');

  const requestedPage = Math.max(1, Number.parseInt(resolvedParams.page || "1", 10) || 1);

  // One page of results, plus the total across all pages
  const { count: total, results: datasets } = await fetchDatasetPage(
    query, PAGE_SIZE, (requestedPage - 1) * PAGE_SIZE, filterQuery,
  );
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const page = Math.min(requestedPage, pageCount);
  const pageHref = (target: number) => {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (format) params.set("format", format);
    if (publisher) params.set("publisher", publisher);
    if (group) params.set("groups", group);
    if (target > 1) params.set("page", String(target));
    const qs = params.toString();
    return qs ? `/datasets?${qs}` : "/datasets";
  };
  const organizations = await fetchOrganizations();
  const allGroups = await fetchGroups();

  // Build active filter labels for display
  const activeFilters: string[] = [];
  if (query) activeFilters.push(`"${query}"`);
  if (format) activeFilters.push(`Format: ${format}`);
  if (publisher) {
    const pubName = organizations.find(o => o.name === publisher)?.title || publisher;
    activeFilters.push(`Publisher: ${pubName}`);
  }
  if (group) {
    const groupName = allGroups.find(g => g.name === group)?.title || group;
    activeFilters.push(`Topic: ${groupName}`);
  }

  return (
    <div className="container mx-auto px-4 py-12">
      <div className="flex flex-col md:flex-row gap-8">
        
        {/* Sidebar Filters */}
        <Suspense fallback={<div className="w-full md:w-64 flex-shrink-0" />}>
          <DatasetFilters organizations={organizations} groups={allGroups} />
        </Suspense>

        {/* Main Content */}
        <main className="flex-1">
          <div className="mb-8 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-slate-900">Datasets</h1>
              {activeFilters.length > 0 && (
                <p className="text-sm text-slate-500 mt-1">
                  Filtered by: {activeFilters.join(" · ")}
                </p>
              )}
            </div>
            <div className="text-sm text-slate-500 font-medium bg-slate-100 px-4 py-2 rounded-full inline-flex w-fit items-center gap-2">
              <Database className="w-4 h-4" />
              {total.toLocaleString("en-GB")} {total === 1 ? "dataset" : "datasets"} found
            </div>
          </div>

          {/* Search Input for Datasets */}
          <Suspense fallback={
            <div className="relative mb-8">
              <div className="flex items-center rounded-xl border border-slate-200 bg-white shadow-sm px-4 py-4">
                <Search className="h-5 w-5 text-slate-400 mr-3" />
                <span className="text-slate-400 text-sm">Loading search...</span>
              </div>
            </div>
          }>
            <DatasetSearch initialQuery={query} />
          </Suspense>

          {/* Dataset List */}
          <div className="space-y-4">
            {datasets.length === 0 ? (
              <div className="bg-white p-16 rounded-3xl shadow-sm border border-slate-100 text-center">
                <div className="w-20 h-20 bg-slate-50 rounded-full flex items-center justify-center mx-auto mb-6">
                  <Search className="w-10 h-10 text-slate-300" />
                </div>
                <h3 className="text-2xl font-bold text-slate-900 mb-3">No Datasets Found</h3>
                <p className="text-slate-500 max-w-md mx-auto text-lg leading-relaxed mb-6">
                  {query
                    ? `No results match your search for "${query}". Try adjusting your filters or using different keywords.`
                    : "No datasets match your criteria. Try resetting the filters or broadening your search parameters to discover public data."
                  }
                </p>
                {(query || format || publisher || group) && (
                  <Link
                    href="/datasets"
                    className="inline-flex items-center gap-2 text-primary-600 hover:text-primary-700 font-medium transition-colors"
                  >
                    Clear all filters →
                  </Link>
                )}
              </div>
            ) : (
              datasets.map((dataset) => (
                <div key={dataset.id} className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 hover:shadow-md hover:border-primary-100 transition-all duration-300 group">
                  <div className="flex flex-col sm:flex-row justify-between items-start gap-4">
                    <div className="flex-1 min-w-0">
                      <Link href={`/datasets/${dataset.name}`} className="text-xl font-bold text-slate-900 hover:text-primary-600 transition-colors mb-2 block">
                        {dataset.title || dataset.name}
                      </Link>
                      <p className="text-sm text-slate-500 font-medium mb-3">
                        Published by <span className="text-slate-700">{dataset.organization?.title || "Unknown"}</span> · {new Date(dataset.metadata_modified).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })}
                      </p>
                      <p className="text-slate-600 leading-relaxed mb-4 line-clamp-2">
                        {(dataset.notes || "").split(/\n\s*\n/)[0] || "No description provided."}
                      </p>
                    </div>
                    <div className="flex-shrink-0 flex gap-2 flex-wrap">
                      {dataset.resources?.map((res, idx) => (
                        <span key={idx} className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-800 uppercase tracking-wider">
                          {res.format || 'DATA'}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="pt-4 border-t border-slate-100 flex flex-wrap gap-4 items-center">
                    {dataset.resources && dataset.resources.length > 0 ? (
                      <DownloadButton url={dataset.resources[0].url} filename={`${dataset.name}.${dataset.resources[0].format?.toLowerCase() || 'csv'}`} />
                    ) : (
                      <span className="flex items-center gap-2 text-sm font-medium text-slate-400 cursor-not-allowed">
                        <Download className="w-4 h-4" /> No File
                      </span>
                    )}
                    <Link href={`/datasets/${dataset.name}`} className="flex items-center gap-2 text-sm font-medium text-slate-600 hover:text-primary-600 transition-colors">
                      View Details →
                    </Link>
                  </div>
                </div>
              ))
            )}
          </div>

          {pageCount > 1 && (
            <nav className="mt-8 flex items-center justify-between gap-4" aria-label="Pagination">
              {page > 1 ? (
                <Link href={pageHref(page - 1)} rel="prev" className="px-5 py-2.5 rounded-xl border border-slate-200 bg-white text-sm font-medium text-slate-700 hover:border-primary-500 hover:text-primary-700 transition-colors">
                  ← Previous
                </Link>
              ) : <span />}
              <p className="text-sm text-slate-500">
                Page {page} of {pageCount.toLocaleString("en-GB")}
              </p>
              {page < pageCount ? (
                <Link href={pageHref(page + 1)} rel="next" className="px-5 py-2.5 rounded-xl border border-slate-200 bg-white text-sm font-medium text-slate-700 hover:border-primary-500 hover:text-primary-700 transition-colors">
                  Next →
                </Link>
              ) : <span />}
            </nav>
          )}
        </main>
      </div>
    </div>
  );
}
