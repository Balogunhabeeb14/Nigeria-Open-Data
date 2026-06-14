"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Search, Database, Menu, X } from "lucide-react";
import { useState, useRef, useEffect } from "react";

export default function Header() {
  const [searchOpen, setSearchOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  // Focus the input when search opens
  useEffect(() => {
    if (searchOpen && searchInputRef.current) {
      searchInputRef.current.focus();
    }
  }, [searchOpen]);

  // Close search on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setSearchOpen(false);
        setSearchQuery("");
      }
    };
    if (searchOpen) {
      document.addEventListener("keydown", handleKeyDown);
      return () => document.removeEventListener("keydown", handleKeyDown);
    }
  }, [searchOpen]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = searchQuery.trim();
    if (trimmed) {
      router.push(`/datasets?q=${encodeURIComponent(trimmed)}`);
    } else {
      router.push("/datasets");
    }
    setSearchOpen(false);
    setSearchQuery("");
    setMobileMenuOpen(false);
  };

  const navLinks = [
    { href: "/datasets", label: "Datasets" },
    { href: "/topics", label: "Topics" },
    { href: "/publishers", label: "Publishers" },
    { href: "/about", label: "About" },
  ];

  return (
    <header className="bg-white/80 backdrop-blur-lg border-b border-slate-200/80 sticky top-0 z-50 shadow-sm">
      <div className="container mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16">
          {/* Logo */}
          <div className="flex items-center gap-2">
            <Database className="h-6 w-6 text-primary-600" />
            <Link href="/" className="text-xl font-bold text-slate-900 tracking-tight">
              Nigeria Open Data
            </Link>
          </div>
          
          {/* Desktop Navigation */}
          <nav className="hidden md:flex space-x-8">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="text-sm font-medium text-slate-600 hover:text-primary-600 transition-colors relative after:absolute after:bottom-0 after:left-0 after:right-0 after:h-0.5 after:bg-primary-600 after:scale-x-0 hover:after:scale-x-100 after:transition-transform after:duration-200 after:origin-center"
              >
                {link.label}
              </Link>
            ))}
          </nav>
          
          {/* Actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSearchOpen(!searchOpen)}
              className={`p-2 rounded-lg transition-all duration-200 ${
                searchOpen
                  ? "bg-primary-50 text-primary-600"
                  : "text-slate-500 hover:text-slate-900 hover:bg-slate-100"
              }`}
              aria-label={searchOpen ? "Close search" : "Open search"}
            >
              {searchOpen ? <X className="h-5 w-5" /> : <Search className="h-5 w-5" />}
            </button>
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="md:hidden p-2 text-slate-500 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-all"
              aria-label="Menu"
            >
              {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </div>

        {/* Search Overlay — slides down under the header */}
        <div className={`overflow-hidden transition-all duration-300 ease-in-out ${
          searchOpen ? "max-h-24 opacity-100 pb-4" : "max-h-0 opacity-0"
        }`}>
          <form onSubmit={handleSearchSubmit} className="relative">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
              <Search className="h-5 w-5 text-slate-400" />
            </div>
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="block w-full pl-12 pr-28 py-3 rounded-xl border-0 ring-1 ring-inset ring-slate-200 shadow-sm text-slate-900 placeholder:text-slate-400 focus:ring-2 focus:ring-inset focus:ring-primary-500 sm:text-sm transition-all bg-slate-50 focus:bg-white"
              placeholder="Search all datasets, topics, or publishers..."
              aria-label="Search datasets"
            />
            <div className="absolute inset-y-1.5 right-1.5">
              <button
                type="submit"
                className="bg-primary-600 hover:bg-primary-700 text-white px-5 py-1.5 rounded-lg text-sm font-medium transition-colors shadow-sm h-full"
              >
                Search
              </button>
            </div>
          </form>
        </div>

        {/* Mobile Menu */}
        <div className={`md:hidden overflow-hidden transition-all duration-300 ease-in-out ${
          mobileMenuOpen ? "max-h-64 opacity-100 pb-4" : "max-h-0 opacity-0"
        }`}>
          <nav className="flex flex-col space-y-1 pt-2 border-t border-slate-100">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setMobileMenuOpen(false)}
                className="text-sm font-medium text-slate-600 hover:text-primary-600 hover:bg-primary-50 px-4 py-3 rounded-lg transition-all"
              >
                {link.label}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </header>
  );
}
