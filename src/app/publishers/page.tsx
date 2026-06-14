import { Building2, ArrowRight } from "lucide-react";
import Link from "next/link";
import { fetchOrganizations } from "@/lib/ckan";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Data Publishers",
  description: "Browse datasets provided by various government departments, ministries, agencies, and public institutions.",
};

export default async function PublishersPage() {
  const publishers = await fetchOrganizations();

  return (
    <div className="container mx-auto px-4 py-12">
      <div className="max-w-3xl mx-auto text-center mb-16">
        <h1 className="text-4xl font-bold text-slate-900 mb-4 tracking-tight">Data Publishers</h1>
        <p className="text-lg text-slate-600">
          Explore datasets provided by various government ministries, departments, and agencies (MDAs).
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {publishers.map((pub, i) => (
          <Link href={`/datasets?publisher=${pub.name}`} key={i} className="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm hover:shadow-lg hover:border-primary-100 transition-all duration-300 group flex items-start gap-4">
            <div className="bg-slate-50 p-3 rounded-xl group-hover:bg-primary-50 transition-colors">
              <Building2 className="w-6 h-6 text-slate-400 group-hover:text-primary-600 transition-colors" />
            </div>
            <div className="flex-1">
              <h3 className="text-lg font-bold text-slate-900 group-hover:text-primary-600 transition-colors mb-1">
                {pub.title || pub.name}
              </h3>
              <p className="text-sm font-medium text-slate-500 flex items-center justify-between">
                {pub.package_count} Datasets
                <ArrowRight className="w-4 h-4 opacity-0 -translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-300" />
              </p>
            </div>
          </Link>
        ))}
        {publishers.length === 0 && (
          <div className="col-span-full bg-white p-12 rounded-3xl shadow-sm border border-slate-100 flex flex-col items-center justify-center text-center min-h-[300px]">
            <div className="w-20 h-20 bg-slate-50 rounded-full flex items-center justify-center mb-6">
              <Building2 className="w-10 h-10 text-slate-400" />
            </div>
            <h3 className="text-2xl font-bold text-slate-900 mb-2">No Publishers Found</h3>
            <p className="text-slate-500 max-w-md mx-auto text-lg">
              There are currently no registered publishers or organizations. Verified government bodies and contributors will appear here once registered.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
