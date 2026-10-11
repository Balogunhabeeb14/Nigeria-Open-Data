import TopicCard from "@/components/TopicCard";
import { fetchGroups } from "@/lib/ckan";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Browse by Topic",
  description: "Browse datasets categorized by popular topics including Business, Environment, health, demographics, and crime.",
};

// Rendered per request: the catalogue is not reachable while the site is
// being built, and a page built then would show an empty catalogue.
export const dynamic = "force-dynamic";

export default async function TopicsPage() {
  const allTopics = await fetchGroups();

  return (
    <div className="container mx-auto px-4 py-12">
      <div className="max-w-3xl mx-auto text-center mb-16">
        <h1 className="text-4xl font-bold text-slate-900 mb-4 tracking-tight">Data Topics</h1>
        <p className="text-lg text-slate-600">
          Browse our extensive collection of datasets organized by category. Find exactly what you need by selecting a topic below.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 lg:gap-8">
        {allTopics.map((topic) => (
          <TopicCard
            key={topic.name}
            title={topic.title || topic.name}
            description={topic.description || "Explore datasets in this category."}
            href={`/datasets?groups=${topic.name}`}
            datasetCount={topic.package_count}
          />
        ))}
        {allTopics.length === 0 && (
          <div className="col-span-full bg-white p-12 rounded-3xl shadow-sm border border-slate-100 flex flex-col items-center justify-center text-center min-h-[300px]">
            <div className="w-20 h-20 bg-slate-50 rounded-full flex items-center justify-center mb-6">
              <svg className="w-10 h-10 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 002-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
              </svg>
            </div>
            <h3 className="text-2xl font-bold text-slate-900 mb-2">No Topics Available Yet</h3>
            <p className="text-slate-500 max-w-md mx-auto text-lg">
              There are currently no topic categories available. Please check back later or explore datasets directly.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
