const CKAN_URL = process.env.NEXT_PUBLIC_CKAN_URL || 'http://localhost:5000';

export interface CKANPackage {
  id: string;
  name: string;
  title: string;
  notes: string;
  metadata_created: string;
  metadata_modified: string;
  organization?: {
    title: string;
  };
  /** Licence as CKAN knows it. Absent when the source did not state one. */
  license_id?: string;
  license_title?: string;
  /** Link to the dataset at its original source. */
  url?: string;
  /** Key/value metadata written by the pipeline (source, coverage, licence...). */
  extras?: { key: string; value: string }[];
  resources: {
    format: string;
    url: string;
    name: string;
  }[];
}

/** Read one of the pipeline's metadata values from a dataset. */
export function getExtra(dataset: CKANPackage, key: string): string | undefined {
  return dataset.extras?.find((e) => e.key === key)?.value || undefined;
}

/**
 * Fetch datasets from the CKAN Backend.
 * Implements ISR (Incremental Static Regeneration) for high scalability and speed.
 */
export async function fetchDatasets(query: string = '', rows: number = 10, filterQuery: string = ''): Promise<CKANPackage[]> {
  try {
    let url = `${CKAN_URL}/api/3/action/package_search?q=${encodeURIComponent(query)}&rows=${rows}`;
    if (filterQuery) {
        url += `&fq=${encodeURIComponent(filterQuery)}`;
    }
    const res = await fetch(url, {
      next: { revalidate: 60 } // Cache for 60 seconds
    });
    
    if (!res.ok) {
      console.warn(`CKAN API error: ${res.status}`);
      return [];
    }

    const data = await res.json();
    if (data.success) {
      return data.result.results as CKANPackage[];
    }
    return [];
  } catch (error) {
    console.error("Failed to connect to CKAN Backend:", error);
    // Return empty array if backend is down to prevent frontend crashes
    return [];
  }
}

export interface CKANOrganization {
  id: string;
  name: string;
  title: string;
  description: string;
  package_count: number;
}

export async function fetchOrganizations(): Promise<CKANOrganization[]> {
  try {
    const res = await fetch(`${CKAN_URL}/api/3/action/organization_list?all_fields=true`, {
      next: { revalidate: 60 }
    });
    if (!res.ok) return [];
    const data = await res.json();
    if (data.success) {
      return data.result as CKANOrganization[];
    }
    return [];
  } catch (error) {
    console.error("Failed to fetch organizations:", error);
    return [];
  }
}

export interface CKANGroup {
  id: string;
  name: string;
  title: string;
  description: string;
  package_count: number;
}

export async function fetchGroups(): Promise<CKANGroup[]> {
  try {
    const res = await fetch(`${CKAN_URL}/api/3/action/group_list?all_fields=true`, {
      next: { revalidate: 60 }
    });
    if (!res.ok) return [];
    const data = await res.json();
    if (data.success) {
      return data.result as CKANGroup[];
    }
    return [];
  } catch (error) {
    console.error("Failed to fetch groups:", error);
    return [];
  }
}

export async function fetchDataset(slug: string): Promise<CKANPackage | null> {
  try {
    const res = await fetch(`${CKAN_URL}/api/3/action/package_show?id=${encodeURIComponent(slug)}`, {
      next: { revalidate: 60 }
    });
    
    if (!res.ok) {
      console.warn(`CKAN API error: ${res.status}`);
      return null;
    }

    const data = await res.json();
    if (data.success) {
      return data.result as CKANPackage;
    }
    return null;
  } catch (error) {
    console.error("Failed to fetch dataset details:", error);
    return null;
  }
}

