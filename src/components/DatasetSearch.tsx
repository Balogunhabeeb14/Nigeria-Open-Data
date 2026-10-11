"use client";

import { Search, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, useEffect, useRef, useCallback } from "react";

interface DatasetSearchProps {
  initialQuery?: string;
}

export default function DatasetSearch({ initialQuery = "" }: DatasetSearchProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [query, setQuery] = useState(initialQuery);
  const [isFocused, setIsFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Navigate with updated search params
  const navigateWithQuery = useCallback((searchQuery: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (searchQuery.trim()) {
      params.set("q", searchQuery.trim());
    } else {
      params.delete("q");
    }
    params.delete("page"); // a new search starts again from the first page
    router.push(`/datasets?${params.toString()}`);
  }, [router, searchParams]);

  // Debounced search on typing
  useEffect(() => {
    // Only trigger debounce if value actually changed from initial
    if (query === initialQuery) return;

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      navigateWithQuery(query);
    }, 400);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, navigateWithQuery, initialQuery]);

  // Handle form submit (Enter key)
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (debounceRef.current) clearTimeout(debounceRef.current);
    navigateWithQuery(query);
  };

  // Clear search
  const handleClear = () => {
    setQuery("");
    if (debounceRef.current) clearTimeout(debounceRef.current);
    navigateWithQuery("");
    inputRef.current?.focus();
  };

  return (
    <form onSubmit={handleSubmit} className="relative mb-8 group">
      <div className={`relative flex items-center rounded-xl border transition-all duration-200 bg-white shadow-sm ${
        isFocused
          ? "ring-2 ring-primary-500 border-primary-500 shadow-md"
          : "border-slate-200 hover:border-slate-300 hover:shadow-md"
      }`}>
        <div className="pl-4 flex items-center pointer-events-none">
          <Search className={`h-5 w-5 transition-colors duration-200 ${
            isFocused ? "text-primary-500" : "text-slate-400"
          }`} />
        </div>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          className="block w-full pl-3 pr-4 py-4 rounded-xl border-0 text-slate-900 placeholder:text-slate-400 sm:text-sm bg-transparent focus:outline-none focus:ring-0"
          placeholder="Search datasets by title, description, or keyword..."
          aria-label="Search datasets"
        />
        {query && (
          <button
            type="button"
            onClick={handleClear}
            className="mr-2 p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-all"
            aria-label="Clear search"
          >
            <X className="h-4 w-4" />
          </button>
        )}
        <button
          type="submit"
          className="mr-2 bg-primary-600 hover:bg-primary-700 text-white px-5 py-2 rounded-lg text-sm font-medium transition-colors shadow-sm flex-shrink-0"
        >
          Search
        </button>
      </div>
      {query && (
        <p className="absolute -bottom-6 left-1 text-xs text-slate-400">
          Showing results for &ldquo;<span className="font-medium text-slate-600">{query}</span>&rdquo;
        </p>
      )}
    </form>
  );
}
