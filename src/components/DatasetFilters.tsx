"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Filter } from "lucide-react";
import { CKANOrganization, CKANGroup } from "@/lib/ckan";

interface DatasetFiltersProps {
  organizations: CKANOrganization[];
  groups: CKANGroup[];
}

export default function DatasetFilters({ organizations, groups }: DatasetFiltersProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const currentFormat = searchParams.get("format") || "";
  const currentPublisher = searchParams.get("publisher") || "";
  const currentGroup = searchParams.get("groups") || "";

  const updateFilters = (key: string, value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    
    // Toggle behavior
    if (params.get(key) === value) {
      params.delete(key);
    } else {
      params.set(key, value);
    }

    router.push(`/datasets?${params.toString()}`);
  };

  return (
    <aside className="w-full md:w-64 flex-shrink-0">
      <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 sticky top-24">
        <h2 className="text-lg font-bold text-slate-900 mb-6 flex items-center gap-2">
          <Filter className="w-5 h-5" /> Filters
        </h2>
        
        {/* Topic Filter Section */}
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-slate-900 mb-3 uppercase tracking-wider">Topics</h3>
          <div className="space-y-2 max-h-64 overflow-y-auto pr-2">
            {groups.map(group => (
              <label key={group.name} className="flex items-center gap-2 cursor-pointer group">
                <input 
                  type="checkbox" 
                  checked={currentGroup === group.name}
                  onChange={() => updateFilters("groups", group.name)}
                  className="rounded border-slate-300 text-primary-600 focus:ring-primary-500" 
                />
                <span className="text-slate-600 group-hover:text-slate-900 transition-colors">
                  {group.title || group.name}
                </span>
              </label>
            ))}
            {groups.length === 0 && (
              <p className="text-sm text-slate-500">No topics available.</p>
            )}
          </div>
        </div>

        <div className="mb-6">
          <h3 className="text-sm font-semibold text-slate-900 mb-3 uppercase tracking-wider">Format</h3>
          <div className="space-y-2">
            {["CSV", "JSON", "XLSX", "PDF"].map(format => (
              <label key={format} className="flex items-center gap-2 cursor-pointer group">
                <input 
                  type="checkbox" 
                  checked={currentFormat === format}
                  onChange={() => updateFilters("format", format)}
                  className="rounded border-slate-300 text-primary-600 focus:ring-primary-500" 
                />
                <span className="text-slate-600 group-hover:text-slate-900 transition-colors">{format}</span>
              </label>
            ))}
          </div>
        </div>

        <div>
          <h3 className="text-sm font-semibold text-slate-900 mb-3 uppercase tracking-wider">Publisher</h3>
          <div className="space-y-2 max-h-64 overflow-y-auto pr-2">
            {organizations.map(pub => (
              <label key={pub.name} className="flex items-center gap-2 cursor-pointer group">
                <input 
                  type="checkbox" 
                  checked={currentPublisher === pub.name}
                  onChange={() => updateFilters("publisher", pub.name)}
                  className="rounded border-slate-300 text-primary-600 focus:ring-primary-500" 
                />
                <span className="text-slate-600 group-hover:text-slate-900 transition-colors">{pub.title || pub.name}</span>
              </label>
            ))}
            {organizations.length === 0 && (
              <p className="text-sm text-slate-500">No publishers available.</p>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
