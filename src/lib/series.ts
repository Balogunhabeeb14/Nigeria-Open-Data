import type { DataTable } from "@/lib/ckan";

export interface SeriesPoint {
  /** Period exactly as published: '2024', '2024Q1', '2024-01'. */
  period: string;
  value: number;
}

export interface Series {
  points: SeriesPoint[];
  unit: string;
  place: string;
}

/**
 * Pull one plottable series out of a data table.
 *
 * A table is plottable when it has `period` and `value` columns and covers a
 * single place. Tables that cover several places (states, LGAs) are not
 * squeezed into one line; they return null and are shown as a table only.
 */
export function toSeries(table: DataTable): Series | null {
  const ids = new Set(table.fields.map((f) => f.id));
  if (!ids.has("period") || !ids.has("value")) return null;

  const places = new Set(table.records.map((r) => String(r.geo_code ?? "")));
  if (places.size > 1) return null;

  const points = table.records
    .filter((r) => r.value !== null && r.value !== "" && Number.isFinite(Number(r.value)))
    .map((r) => ({ period: String(r.period), value: Number(r.value) }))
    .sort((a, b) => a.period.localeCompare(b.period));
  if (points.length < 2) return null;

  const first = table.records[0] ?? {};
  return {
    points,
    unit: String(first.unit ?? ""),
    place: String(first.geo_name ?? ""),
  };
}

/**
 * 1284 → '1,284', 12900 → '12.9K', 4200000 → '4.2M'. For axis ticks and labels.
 * `extraDigits` adds decimals when neighbouring values would otherwise read the same.
 */
export function compact(value: number, extraDigits: number = 0): string {
  const abs = Math.abs(value);
  if (abs >= 1e12) return trim(value / 1e12, extraDigits) + "T";
  if (abs >= 1e9) return trim(value / 1e9, extraDigits) + "B";
  if (abs >= 1e6) return trim(value / 1e6, extraDigits) + "M";
  if (abs >= 1e4) return trim(value / 1e3, extraDigits) + "K";
  return extraDigits > 0
    ? value.toLocaleString("en-GB", { maximumFractionDigits: Math.min(6, 2 + extraDigits) })
    : full(value);
}

/** Tick labels that are all different: precision is raised until they are. */
export function tickLabels(ticks: number[]): string[] {
  for (let extra = 0; extra <= 3; extra++) {
    const labels = ticks.map((t) => compact(t, extra));
    if (new Set(labels).size === labels.length) return labels;
  }
  return ticks.map((t) => full(t));
}

/** A value with a sensible number of decimals for its size. For tables and tooltips. */
export function full(value: number): string {
  const abs = Math.abs(value);
  const decimals = abs >= 1000 ? 0 : abs >= 100 ? 1 : abs >= 1 ? 2 : 3;
  return value.toLocaleString("en-GB", { maximumFractionDigits: decimals });
}

function trim(value: number, extraDigits: number = 0): string {
  return value.toLocaleString("en-GB", { maximumFractionDigits: (Math.abs(value) >= 100 ? 0 : 1) + extraDigits });
}

/** Round axis bounds and evenly spaced ticks covering [min, max]. */
export function niceTicks(min: number, max: number, target: number = 5): number[] {
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1;
    min -= pad;
    max += pad;
  }
  const rawStep = (max - min) / target;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const residual = rawStep / magnitude;
  const step = (residual >= 5 ? 10 : residual >= 2 ? 5 : residual >= 1 ? 2 : 1) * magnitude;
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= end + step / 2; v += step) {
    ticks.push(Number(v.toPrecision(12)));
  }
  return ticks;
}

export interface PlaceSeries {
  code: string;
  name: string;
  points: SeriesPoint[];
}

export interface PlaceTable {
  places: PlaceSeries[];
  /** Every period present, oldest first. */
  periods: string[];
  unit: string;
}

/**
 * Split a table that covers several places (states, say) into one series per
 * place. Returns null for tables that cover a single place or lack the
 * standard `period` and `value` columns.
 */
export function toPlaceTable(table: DataTable): PlaceTable | null {
  const ids = new Set(table.fields.map((f) => f.id));
  if (!ids.has("period") || !ids.has("value") || !ids.has("geo_code")) return null;

  const byPlace = new Map<string, PlaceSeries>();
  const periods = new Set<string>();
  for (const r of table.records) {
    if (r.value === null || r.value === "" || !Number.isFinite(Number(r.value))) continue;
    const code = String(r.geo_code ?? "");
    const period = String(r.period);
    periods.add(period);
    let place = byPlace.get(code);
    if (!place) {
      place = { code, name: String(r.geo_name ?? code), points: [] };
      byPlace.set(code, place);
    }
    place.points.push({ period, value: Number(r.value) });
  }
  if (byPlace.size < 2) return null;

  const places = [...byPlace.values()];
  for (const place of places) place.points.sort((a, b) => a.period.localeCompare(b.period));
  places.sort((a, b) => a.name.localeCompare(b.name));
  return {
    places,
    periods: [...periods].sort(),
    unit: String(table.records[0]?.unit ?? ""),
  };
}

/** '2026Q1' → 'Q1 2026', '2024-03' → 'March 2024'; anything else unchanged. */
export function periodLabel(period: string): string {
  const quarter = /^(\d{4})Q([1-4])$/.exec(period);
  if (quarter) return `Q${quarter[2]} ${quarter[1]}`;
  const month = /^(\d{4})-(\d{2})$/.exec(period);
  if (month) {
    const names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
    const name = names[Number(month[2]) - 1];
    if (name) return `${name} ${month[1]}`;
  }
  return period;
}
