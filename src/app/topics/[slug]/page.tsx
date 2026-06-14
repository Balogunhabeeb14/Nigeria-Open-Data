import Link from "next/link";
import { Download, ChevronLeft, Database } from "lucide-react";
import { fetchDatasets, fetchGroups } from "@/lib/ckan";
import DownloadButton from "@/components/DownloadButton";

import type { Metadata } from "next";

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const resolvedParams = await params;
  const slug = resolvedParams.slug;
  const topicName = slug.replace(/-/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  return {
    title: `${topicName} | Topics`,
    description: `Explore all open datasets, reports, and statistics related to ${topicName.toLowerCase()}.`,
  };
}

export default async function TopicDetail({ params }: { params: Promise<{ slug: string }> }) {
  const resolvedParams = await params;
  const slug = resolvedParams.slug;
  const topicName = slug.replace(/-/g, ' ').replace(/\b\w/g, l => l.toUpperCase());

  // Fetch real datasets filtered by group (topic)
  const datasets = await fetchDatasets('', 50, `groups:${slug}`);

  return (
    <div className="container mx-auto px-4 py-12">
      <Link href="/topics" className="inline-flex items-center text-primary-600 hover:text-primary-700 font-medium mb-8 transition-colors group">
        <ChevronLeft className="w-5 h-5 mr-1 transform group-hover:-translate-x-1 transition-transform" /> Back to Topics
      </Link>

      <div className="bg-slate-900 rounded-3xl p-8 md:p-12 mb-12 shadow-lg relative overflow-hidden">
        {/* Decorative pattern */}
        <div className="absolute inset-0 opacity-10 bg-[radial-gradient(circle_at_top_right,_var(--tw-gradient-stops))] from-white via-transparent to-transparent"></div>
        
        <div className="relative z-10">
          <h1 className="text-4xl md:text-5xl font-bold text-white mb-4 tracking-tight">{topicName}</h1>
          <p className="text-lg text-slate-300 max-w-2xl">
            Explore all open datasets, reports, and statistics related to {topicName.toLowerCase()}.
          </p>
        </div>
      </div>

      <div className="max-w-4xl mx-auto lg:mx-0">
        <div className="mb-8 flex items-center justify-between">
          <h2 className="text-2xl font-bold text-slate-900">Available Datasets</h2>
          <span className="text-sm font-medium text-slate-500 bg-slate-100 px-4 py-1 rounded-full">
            {datasets.length} Results
          </span>
        </div>

        <div className="space-y-4">
          {datasets.map((dataset) => (
            <div key={dataset.id} className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 hover:shadow-xl hover:-translate-y-1 transition-all duration-300 group">
              <div className="flex flex-col sm:flex-row justify-between items-start gap-4">
                <div>
                  <h3 className="text-xl font-bold text-slate-900 mb-2 group-hover:text-primary-600 transition-colors">
                    <Link href={`/datasets/${dataset.name}`}>{dataset.title || dataset.name}</Link>
                  </h3>
                  <p className="text-sm text-slate-500 font-medium mb-3">
                    Published by <span className="text-slate-700">{dataset.organization?.title || 'Unknown'}</span> • {new Date(dataset.metadata_modified).toLocaleDateString()}
                  </p>
                  <p className="text-slate-600 leading-relaxed mb-4">
                    {dataset.notes || "No description provided."}
                  </p>
                </div>
                <div className="flex-shrink-0 flex gap-2">
                  {dataset.resources?.map((res, idx) => (
                    <span key={idx} className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-800 uppercase tracking-wider group-hover:bg-primary-50 group-hover:text-primary-700 transition-colors">
                      {res.format || 'DATA'}
                    </span>
                  ))}
                </div>
              </div>
              <div className="pt-4 border-t border-slate-50 flex gap-4">
                {dataset.resources && dataset.resources.length > 0 ? (
                  <DownloadButton 
                    url={dataset.resources[0].url} 
                    filename={`${dataset.name}.${dataset.resources[0].format?.toLowerCase() || 'csv'}`}
                    className="inline-flex items-center gap-2 text-sm font-medium text-primary-600 hover:text-primary-700 transition-colors bg-primary-50 px-4 py-2 rounded-lg hover:bg-primary-100"
                  />
                ) : (
                  <span className="inline-flex items-center gap-2 text-sm font-medium text-slate-400 bg-slate-50 px-4 py-2 rounded-lg cursor-not-allowed">
                    <Download className="w-4 h-4" /> No File
                  </span>
                )}
                <Link href={`/datasets/${dataset.name}`} className="inline-flex items-center gap-2 text-sm font-medium text-slate-600 hover:text-slate-900 transition-colors px-4 py-2 rounded-lg border border-slate-200 hover:bg-slate-50">
                  View Dataset
                </Link>
              </div>
            </div>
          ))}
          {datasets.length === 0 && (
            <div className="bg-white p-16 rounded-3xl shadow-sm border border-slate-100 flex flex-col items-center justify-center text-center">
              <div className="w-24 h-24 bg-slate-50 rounded-full flex items-center justify-center mb-6">
                <Database className="w-12 h-12 text-slate-300" />
              </div>
              <h3 className="text-2xl font-bold text-slate-900 mb-3">No Datasets Found</h3>
              <p className="text-slate-500 max-w-md mx-auto text-lg leading-relaxed">
                No datasets are currently assigned to this category. Select a different topic or broaden your search to find relevant public data.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
