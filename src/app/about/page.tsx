import { Database, ShieldCheck, Zap } from "lucide-react";
import Link from "next/link";

export default function AboutPage() {
  return (
    <div className="bg-slate-50 min-h-screen">
      {/* Hero */}
      <section className="bg-slate-900 text-white py-24">
        <div className="container mx-auto px-4 max-w-4xl text-center">
          <h1 className="text-4xl md:text-5xl font-extrabold mb-6 tracking-tight">About Nigeria Open Data</h1>
          <p className="text-xl text-slate-400 leading-relaxed">
            Public data about Nigeria, gathered from many publishers into one place anyone can search and use.
          </p>
        </div>
      </section>

      {/* Content */}
      <section className="py-20">
        <div className="container mx-auto px-4 max-w-4xl">
          <div className="bg-white rounded-3xl p-8 md:p-12 shadow-sm border border-slate-100 hover:shadow-lg transition-shadow duration-300">
            <h2 className="text-3xl font-bold text-slate-900 mb-6">Our Mission</h2>
            <p className="text-lg text-slate-600 leading-relaxed mb-12">
              Useful data about Nigeria exists, but it is scattered across the websites of statistical
              agencies, ministries, development organisations and international bodies, in different
              formats. This platform collects it, describes it consistently and keeps it up to date, so
              students, researchers, journalists, businesses and civil society can find and use it
              without specialist skills. It is an independent, open-source project run by volunteers.
              It is not a government service, and the figures remain those of the original publishers.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
              <div className="text-center p-6 group">
                <div className="bg-primary-50 w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4 group-hover:bg-primary-100 group-hover:scale-110 transition-all duration-300">
                  <Database className="w-8 h-8 text-primary-600" />
                </div>
                <h3 className="text-xl font-bold text-slate-900 mb-2">One place</h3>
                <p className="text-slate-600">Many sources, described the same way and searchable together.</p>
              </div>
              <div className="text-center p-6 group">
                <div className="bg-primary-50 w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4 group-hover:bg-primary-100 group-hover:scale-110 transition-all duration-300">
                  <ShieldCheck className="w-8 h-8 text-primary-600" />
                </div>
                <h3 className="text-xl font-bold text-slate-900 mb-2">Traceable</h3>
                <p className="text-slate-600">Every dataset shows its source, licence and last update.</p>
              </div>
              <div className="text-center p-6 group">
                <div className="bg-primary-50 w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4 group-hover:bg-primary-100 group-hover:scale-110 transition-all duration-300">
                  <Zap className="w-8 h-8 text-primary-600" />
                </div>
                <h3 className="text-xl font-bold text-slate-900 mb-2">Open</h3>
                <p className="text-slate-600">The code and the list of sources are public for anyone to check.</p>
              </div>
            </div>

            <div className="mt-12 text-center">
              <Link href="/datasets" className="inline-flex items-center justify-center bg-primary-600 text-white font-medium px-8 py-4 rounded-xl hover:bg-primary-700 hover:-translate-y-1 transition-all duration-300 shadow-sm">
                Explore the Data
              </Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
