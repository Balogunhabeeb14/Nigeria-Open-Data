/** Facts about this deployment that pages share. Read on the server at run time. */

export const REPO_URL = "https://github.com/Balogunhabeeb14/Nigeria-Open-Data";

/**
 * Where people can write to the team. Set CONTACT_EMAIL on the server to an
 * address the team actually receives mail at. Until it is set, pages point to
 * the project's GitHub issues instead of showing an address that may not work.
 */
export function contactEmail(): string | undefined {
  const value = (process.env.CONTACT_EMAIL || "").trim();
  return value.includes("@") ? value : undefined;
}

/** The pipeline API, which sits beside the website. */
const PIPELINE_URL = (process.env.PIPELINE_INTERNAL_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export interface SourceStatus {
  id: string;
  name: string;
  kind: string;
  datasets: number;
  checked_without_data: number;
  failed: number;
  awaiting_publication: number;
  observations: number;
  last_successful_update: string | null;
  last_checked: string | null;
}

export interface DataStatus {
  sources: SourceStatus[];
  totals: {
    datasets: number;
    observations: number;
    sources: number;
    failed: number;
    last_successful_update: string | null;
  };
}

/** What the pipeline has actually loaded, and when. Null if it cannot be reached. */
export async function fetchDataStatus(): Promise<DataStatus | null> {
  try {
    const res = await fetch(`${PIPELINE_URL}/api/status`, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    return (await res.json()) as DataStatus;
  } catch {
    return null;
  }
}

export function longDate(iso: string | null | undefined): string {
  if (!iso) return "Not yet";
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}
