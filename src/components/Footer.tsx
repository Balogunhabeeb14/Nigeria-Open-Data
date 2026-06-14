import Link from "next/link";
import { Database, Mail } from "lucide-react";

export default function Footer() {
  return (
    <footer className="bg-slate-900 text-slate-300 py-12">
      <div className="container mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
          <div className="col-span-1 md:col-span-2">
            <div className="flex items-center gap-2 mb-4">
              <Database className="h-6 w-6 text-primary-500" />
              <span className="text-xl font-bold text-white tracking-tight">
                Nigeria Open Data
              </span>
            </div>
            <p className="text-slate-400 max-w-sm mb-6">
              Empowering citizens, researchers, and developers with accessible public data for innovation and transparency.
            </p>
            <div className="flex space-x-4">
              <a href="mailto:support@Nigeriaopendata.gov.ng" className="text-slate-400 hover:text-white transition-colors">
                <Mail className="h-5 w-5" />
              </a>
            </div>
          </div>
          
          <div>
            <h3 className="text-sm font-semibold text-white tracking-wider uppercase mb-4">Platform</h3>
            <ul className="space-y-3">
              <li><Link href="/datasets" className="hover:text-primary-400 transition-colors">All Datasets</Link></li>
              <li><Link href="/topics" className="hover:text-primary-400 transition-colors">Topics</Link></li>
              <li><Link href="/publishers" className="hover:text-primary-400 transition-colors">Publishers</Link></li>
              <li><Link href="/api" className="hover:text-primary-400 transition-colors">API Documentation</Link></li>
            </ul>
          </div>
          
          <div>
            <h3 className="text-sm font-semibold text-white tracking-wider uppercase mb-4">Legal</h3>
            <ul className="space-y-3">
              <li><Link href="/privacy" className="hover:text-primary-400 transition-colors">Privacy Policy</Link></li>
              <li><Link href="/terms" className="hover:text-primary-400 transition-colors">Terms of Service</Link></li>
              <li><Link href="/accessibility" className="hover:text-primary-400 transition-colors">Accessibility</Link></li>
              <li><Link href="/about" className="hover:text-primary-400 transition-colors">About Us</Link></li>
            </ul>
          </div>
        </div>
        <div className="border-t border-slate-800 mt-12 pt-8 flex flex-col md:flex-row justify-between items-center">
          <p className="text-sm text-slate-500">
            &copy; {new Date().getFullYear()} Nigeria Open Data. All rights reserved.
          </p>
          <p className="text-sm text-slate-500 mt-2 md:mt-0">
            Built for transparency.
          </p>
        </div>
      </div>
    </footer>
  );
}
