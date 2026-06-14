"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";

export default function SearchBar() {
  const [query, setQuery] = useState("");
  const router = useRouter();

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed) {
      router.push(`/datasets?q=${encodeURIComponent(trimmed)}`);
    } else {
      router.push("/datasets");
    }
  };

  return (
    <form onSubmit={handleSearch} className="max-w-3xl mx-auto w-full relative group">
      <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
        <Search className="h-5 w-5 text-slate-400 group-focus-within:text-primary-500 transition-colors" />
      </div>
      <input
        type="text"
        className="block w-full pl-12 pr-4 py-4 rounded-2xl border-0 ring-1 ring-inset ring-slate-200 shadow-sm text-slate-900 placeholder:text-slate-400 focus:ring-2 focus:ring-inset focus:ring-primary-500 sm:text-lg transition-all duration-300 ease-in-out hover:shadow-md focus:shadow-md"
        placeholder="Search datasets, topics, or publishers..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="absolute inset-y-2 right-2">
        <button
          type="submit"
          className="bg-primary-600 hover:bg-primary-700 text-white px-6 py-2 rounded-xl text-sm font-medium transition-colors shadow-sm h-full"
        >
          Search
        </button>
      </div>
    </form>
  );
}
