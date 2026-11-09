// Where the server fetches the catalogue from. CATALOG_INTERNAL_URL is read
// when the server starts, so one built image can be pointed at any backend
// (CKAN, or the pipeline's built-in catalogue). NEXT_PUBLIC_CKAN_URL is fixed
// at build time and is only the fallback.
const CKAN_URL = (
  process.env.CATALOG_INTERNAL_URL ||
  process.env.CKAN_URL ||
  process.env.NEXT_PUBLIC_CKAN_URL ||
  'http://localhost:5000'
).replace(/\/$/, '');

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
  resources: CKANResource[];
}

export interface CKANResource {
  id?: string;
  format: string;
  url: string;
  name: string;
  description?: string;
  /** True when the rows are held in the catalogue and can be queried. */
  datastore_active?: boolean;
  url_type?: string;
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


export interface DatasetPage {
  /** Total number of matching datasets, not just the ones on this page. */
  count: number;
  results: CKANPackage[];
}

/** One page of search results, with the total so the UI can paginate. */
export async function fetchDatasetPage(
  query: string = '',
  rows: number = 20,
  start: number = 0,
  filterQuery: string = '',
): Promise<DatasetPage> {
  try {
    let url = `${CKAN_URL}/api/3/action/package_search?q=${encodeURIComponent(query)}&rows=${rows}&start=${start}`;
    if (filterQuery) {
      url += `&fq=${encodeURIComponent(filterQuery)}`;
    }
    const res = await fetch(url, { next: { revalidate: 60 } });
    if (!res.ok) {
      console.warn(`Catalogue API error: ${res.status}`);
      return { count: 0, results: [] };
    }
    const data = await res.json();
    if (data.success) {
      return { count: data.result.count ?? data.result.results.length, results: data.result.results };
    }
    return { count: 0, results: [] };
  } catch (error) {
    console.error("Failed to connect to the catalogue:", error);
    return { count: 0, results: [] };
  }
}

export interface DataTable {
  fields: { id: string; type?: string }[];
  records: Record<string, string | number | null>[];
  total: number;
}

/** The resource whose rows can be read back, if the dataset has one. */
export function findDataResource(dataset: CKANPackage): CKANResource | undefined {
  return dataset.resources?.find((r) => r.id && (r.datastore_active || r.url_type === 'datastore'));
}

/** Rows of a data table. Returns null when the table cannot be read. */
export async function fetchDataTable(resourceId: string, limit: number = 5000): Promise<DataTable | null> {
  try {
    const res = await fetch(
      `${CKAN_URL}/api/3/action/datastore_search?resource_id=${encodeURIComponent(resourceId)}&limit=${limit}`,
      { next: { revalidate: 60 } },
    );
    if (!res.ok) return null;
    const data = await res.json();
    if (!data.success) return null;
    return {
      // CKAN adds an internal row id column; it is not part of the data.
      fields: (data.result.fields as DataTable['fields']).filter((f) => f.id !== '_id'),
      records: data.result.records,
      total: data.result.total ?? data.result.records.length,
    };
  } catch (error) {
    console.error("Failed to fetch data table:", error);
    return null;
  }
}
