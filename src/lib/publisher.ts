export class PublisherError extends Error {
  constructor(message: string, public status: number, public reauthenticate = false) { super(message); }
}

export async function publisherRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (init.method && init.method !== "GET") {
    const csrf = document.cookie.split("; ").find(cookie => cookie.startsWith("nod_csrf="))?.slice(9);
    if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  }
  const response = await fetch(path, { ...init, headers, credentials: "same-origin", cache: "no-store" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof data.detail === "string" ? data.detail : "Check your inputs and try again.";
    throw new PublisherError(message, response.status, response.headers.get("X-Reauthentication-Required") === "true");
  }
  return data as T;
}

export interface Organisation { id: string; name: string; role: "owner" | "editor" | "viewer"; }
export interface Account { email: string; verified: boolean; organisations: Organisation[]; }
export interface Job { id: string; action: string; status: string; progress: number; phase: string; attempts: number; error_code: string | null; }
export interface Dataset {
  dataset_id: string; display_name: string; description: string; processing_state: string; publication_state: string;
  row_count: number; format: string; licence: string; original_provider: string; provenance: string;
}
export interface DatasetDetail extends Dataset {
  files: { id: string; kind: string; format: string; size_bytes: number }[];
  jobs: Job[]; preview: Record<string, unknown>[];
}
