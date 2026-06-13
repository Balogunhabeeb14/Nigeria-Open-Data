"use client";

import { Download } from "lucide-react";
import { useState } from "react";

interface DownloadButtonProps {
  url: string;
  filename: string;
  className?: string;
}

export default function DownloadButton({ url, filename, className }: DownloadButtonProps) {
  const [isDownloading, setIsDownloading] = useState(false);

  const handleDownload = async (e: React.MouseEvent<HTMLButtonElement>) => {
    e.preventDefault();
    if (isDownloading) return;
    
    try {
      setIsDownloading(true);
      
      // Fetch the file as a blob to force a download instead of opening a new tab
      const response = await fetch(url);
      if (!response.ok) throw new Error("Network response was not ok");
      
      const blob = await response.blob();
      const downloadUrl = window.URL.createObjectURL(blob);
      
      const a = document.createElement("a");
      a.style.display = "none";
      a.href = downloadUrl;
      // Provide a fallback filename if none is provided or if it's empty
      a.download = filename || "dataset-download";
      
      document.body.appendChild(a);
      a.click();
      
      window.URL.revokeObjectURL(downloadUrl);
      document.body.removeChild(a);
    } catch (error) {
      console.error("Download failed:", error);
      // Fallback: just open the URL in a new tab if blob fetch fails (e.g. CORS issues)
      window.open(url, "_blank");
    } finally {
      setIsDownloading(false);
    }
  };

  const defaultClassName = "flex items-center gap-2 text-sm font-medium text-primary-600 hover:text-primary-700 transition-colors";

  return (
    <button 
      onClick={handleDownload} 
      disabled={isDownloading}
      className={className || defaultClassName}
      title={`Download ${filename}`}
    >
      <Download className={`w-4 h-4 ${isDownloading ? 'animate-bounce' : ''}`} /> 
      {isDownloading ? 'Downloading...' : 'Download'}
    </button>
  );
}
