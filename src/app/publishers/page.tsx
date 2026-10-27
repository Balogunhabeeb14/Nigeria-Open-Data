import { Building2, ArrowRight } from "lucide-react";
import Link from "next/link";
import { fetchOrganizations } from "@/lib/ckan";
import { REPO_URL } from "@/lib/site";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Data Publishers",
  description: "The organisations whose data is listed on Naija Open Data.",
};

// Rendered per request: the catalogue is not reachable while the site is
// being built, and a page built then would show an empty catalogue.
export const dynamic = "force-dynamic";

export default async function PublishersPage() {
  const publishers = await fetchOrganizations();

  return (
    <div className="container mx-auto px-4 py-12 relative min-h-screen">
      <div className="max-w-3xl mx-auto text-center mb-16">
        <h1 className="text-4xl md:text-5xl font-black text-slate-900 mb-4 tracking-tight">Data Publishers</h1>
        <p className="text-lg text-slate-600 mb-8">
          The organisations whose data is listed here. Every dataset links back to its original source.
        </p>
        <a
          href={`${REPO_URL}/issues/new`}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 bg-primary-600 hover:bg-primary-700 text-white px-6 py-3 rounded-xl font-semibold transition-colors"
        >
          Suggest a dataset or source
        </a>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {publishers.map((pub, i) => (
          <Link href={`/datasets?publisher=${pub.name}`} key={i} className="bg-white p-6 rounded-3xl border border-slate-100 shadow-sm hover:shadow-xl hover:border-primary-100 transition-all duration-300 group flex items-start gap-4">
            <div className="bg-slate-50 p-4 rounded-2xl group-hover:bg-primary-50 transition-colors shrink-0">
              <Building2 className="w-7 h-7 text-slate-400 group-hover:text-primary-600 transition-colors" />
            </div>
            <div className="flex-1 mt-1">
              <h3 className="text-lg font-bold text-slate-900 group-hover:text-primary-600 transition-colors mb-1 line-clamp-2">
                {pub.title || pub.name}
              </h3>
              <p className="text-sm font-semibold text-slate-500 flex items-center justify-between mt-3">
                {pub.package_count} Datasets
                <ArrowRight className="w-4 h-4 opacity-0 -translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-300 text-primary-600" />
              </p>
            </div>
          </Link>
        ))}
        {publishers.length === 0 && (
          <div className="col-span-full bg-white p-12 rounded-[2.5rem] shadow-sm border border-slate-100 flex flex-col items-center justify-center text-center min-h-[300px]">
            <div className="w-24 h-24 bg-slate-50 rounded-full flex items-center justify-center mb-6">
              <Building2 className="w-12 h-12 text-slate-300" />
            </div>
            <h3 className="text-2xl font-black text-slate-900 mb-2">No Publishers Found</h3>
            <p className="text-slate-500 max-w-md mx-auto text-lg font-medium">
              No publishers are listed yet. They appear here as soon as the first datasets are loaded.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
