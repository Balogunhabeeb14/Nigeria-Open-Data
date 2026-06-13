import Link from "next/link";
import { ArrowRight } from "lucide-react";

interface TopicCardProps {
  title: string;
  description: string;
  href: string;
  datasetCount?: number;
}

export default function TopicCard({ title, description, href, datasetCount }: TopicCardProps) {
  return (
    <Link 
      href={href}
      className="group block bg-white rounded-2xl p-6 border border-slate-100 shadow-sm hover:shadow-xl hover:-translate-y-1 transition-all duration-300 ease-out"
    >
      <div className="flex justify-between items-start mb-4">
        <h3 className="text-xl font-bold text-slate-900 group-hover:text-primary-600 transition-colors">
          {title}
        </h3>
        {datasetCount !== undefined && (
          <span className="bg-primary-50 text-primary-700 text-xs font-semibold px-2.5 py-1 rounded-full border border-primary-100 shrink-0 ml-2">
            {datasetCount} {datasetCount === 1 ? 'dataset' : 'datasets'}
          </span>
        )}
      </div>
      <p className="text-slate-600 text-sm leading-relaxed mb-6 line-clamp-3">
        {description}
      </p>
      <div className="flex items-center text-primary-600 font-medium text-sm">
        Explore Data
        <ArrowRight className="ml-2 h-4 w-4 transform group-hover:translate-x-1 transition-transform" />
      </div>
    </Link>
  );
}
