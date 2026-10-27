import Link from "next/link";
import { Plus } from "lucide-react";
export default function UploadDatasetButton() {
  return <Link href="/publisher" className="inline-flex items-center gap-3 bg-primary-600 hover:bg-primary-700 text-white px-8 py-4 rounded-2xl font-bold text-lg"><Plus className="w-6 h-6" />Publish New Dataset</Link>;
}
