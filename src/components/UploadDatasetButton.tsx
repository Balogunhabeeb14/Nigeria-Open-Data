"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import PublisherRegistrationForm from "@/components/forms/PublisherRegistrationForm";

export default function UploadDatasetButton() {
  const [isModalOpen, setIsModalOpen] = useState(false);

  return (
    <>
      <button 
        onClick={() => setIsModalOpen(true)}
        className="inline-flex items-center gap-3 bg-primary-600 hover:bg-primary-700 text-white px-8 py-4 rounded-2xl font-bold text-lg shadow-xl shadow-primary-600/20 hover:shadow-primary-600/40 hover:-translate-y-1 transition-all duration-300"
      >
        <Plus className="w-6 h-6" /> Publish New Dataset
      </button>

      {/* Modal Overlay */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto p-4 sm:p-6">
          <div 
            className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm transition-opacity" 
            onClick={() => setIsModalOpen(false)}
          ></div>
          <div className="relative w-full max-w-4xl z-10 animate-in fade-in zoom-in-95 duration-300">
            <PublisherRegistrationForm onClose={() => setIsModalOpen(false)} />
          </div>
        </div>
      )}
    </>
  );
}
