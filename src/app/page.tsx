import SearchBar from "@/components/SearchBar";
import TopicCard from "@/components/TopicCard";

import { fetchGroups } from "@/lib/ckan";

export default async function Home() {
  const groups = await fetchGroups();
  
  // Map or fallback in case CKAN isn't populated yet
  const displayGroups = groups.length > 0 ? groups : [
    {
      id: 'business',
      name: 'business',
      title: 'Business and Economy',
      description: 'Data on small businesses, industry, imports, exports, and trade. Empower your business with insights.',
      package_count: 0
    },
    {
      id: 'crime',
      name: 'crime',
      title: 'Crime and Justice',
      description: 'Information on courts, police, prisons, offenders, borders, and immigration. Analyze safety and justice.',
      package_count: 0
    },
    {
      id: 'education',
      name: 'education',
      title: 'Education',
      description: 'Covers students, training, qualifications, and the National Curriculum. Discover learning trends.',
      package_count: 0
    },
    {
      id: 'health',
      name: 'health',
      title: 'Health',
      description: 'Find information on smoking, drugs, alcohol, medicine performance, and hospitals. Track public health metrics.',
      package_count: 0
    }
  ];

  return (
    <div className="bg-slate-50">
      {/* Hero Section */}
      <section className="relative pt-20 pb-32 overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-primary-50 to-slate-50 z-0"></div>
        <div className="container mx-auto px-4 relative z-10 text-center">
          <h1 className="text-5xl md:text-6xl font-extrabold text-slate-900 mb-6 tracking-tight">
            Nigeria <span className="text-primary-600">Open Data</span>
          </h1>
          <p className="text-xl text-slate-600 mb-12 max-w-2xl mx-auto leading-relaxed">
            Access trusted, scalable, and verifiable government and public data to build the next generation of products and services.
          </p>
          <SearchBar />
        </div>
      </section>

      {/* Topics Section */}
      <section className="py-20 bg-white">
        <div className="container mx-auto px-4">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-bold text-slate-900 mb-4">Popular Topics</h2>
            <p className="text-slate-600 max-w-2xl mx-auto">
              Browse datasets organized by high-level categories.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
            {displayGroups.slice(0, 4).map((group) => (
              <TopicCard 
                key={group.id} 
                title={group.title} 
                description={group.description || "No description provided."} 
                href={`/datasets?groups=${group.name}`}
                datasetCount={group.package_count}
              />
            ))}
          </div>
        </div>
      </section>

      {/* Why Use Section */}
      <section className="py-24 bg-primary-50 relative overflow-hidden">
        {/* Decorative background elements */}
        <div className="absolute top-0 left-0 w-full h-full overflow-hidden z-0 opacity-50 pointer-events-none">
          <div className="absolute -top-24 -left-24 w-96 h-96 rounded-full bg-primary-200 blur-3xl"></div>
          <div className="absolute bottom-0 right-0 w-[800px] h-[800px] bg-[radial-gradient(ellipse_at_bottom_right,_var(--tw-gradient-stops))] from-primary-100 via-transparent to-transparent blur-3xl"></div>
        </div>

        <div className="container mx-auto px-4 relative z-10">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-bold text-slate-900 mb-4">Why Use Nigeria Open Data?</h2>
            <p className="text-slate-600 max-w-2xl mx-auto">
              Built on enterprise-grade infrastructure to deliver the best data experience.
            </p>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 lg:gap-12 text-center">
            <div className="p-8 bg-white rounded-3xl shadow-sm border border-primary-100 hover:shadow-xl hover:-translate-y-2 transition-all duration-300 group">
              <div className="bg-primary-50 w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-6 group-hover:scale-110 group-hover:bg-primary-100 transition-all duration-300">
                <svg className="w-8 h-8 text-primary-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                </svg>
              </div>
              <h3 className="text-xl font-bold mb-3 text-slate-900">Trusted & Secure</h3>
              <p className="text-slate-600 leading-relaxed">
                Access verified, up-to-date data directly from government and public bodies in a secure environment.
              </p>
            </div>
            
            <div className="p-8 bg-white rounded-3xl shadow-sm border border-primary-100 hover:shadow-xl hover:-translate-y-2 transition-all duration-300 group">
              <div className="bg-primary-50 w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-6 group-hover:scale-110 group-hover:bg-primary-100 transition-all duration-300">
                <svg className="w-8 h-8 text-primary-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <h3 className="text-xl font-bold mb-3 text-slate-900">Lightning Fast</h3>
              <p className="text-slate-600 leading-relaxed">
                Powered by a modern architecture to ensure datasets are searchable and downloadable in milliseconds.
              </p>
            </div>
            
            <div className="p-8 bg-white rounded-3xl shadow-sm border border-primary-100 hover:shadow-xl hover:-translate-y-2 transition-all duration-300 group">
              <div className="bg-primary-50 w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-6 group-hover:scale-110 group-hover:bg-primary-100 transition-all duration-300">
                <svg className="w-8 h-8 text-primary-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
                </svg>
              </div>
              <h3 className="text-xl font-bold mb-3 text-slate-900">Extensive Coverage</h3>
              <p className="text-slate-600 leading-relaxed">
                Explore an ever-growing catalog of datasets across multiple domains, updated via automated pipelines.
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
