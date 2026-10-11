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

/** 1284 → '1,284', 12900 → '12.9K', 4200000 → '4.2M'. For axis ticks. */
export function compact(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e12) return trim(value / 1e12) + "T";
  if (abs >= 1e9) return trim(value / 1e9) + "B";
  if (abs >= 1e6) return trim(value / 1e6) + "M";
  if (abs >= 1e4) return trim(value / 1e3) + "K";
  return full(value);
}

/** A value with a sensible number of decimals for its size. For tables and tooltips. */
export function full(value: number): string {
  const abs = Math.abs(value);
  const decimals = abs >= 1000 ? 0 : abs >= 100 ? 1 : abs >= 1 ? 2 : 3;
  return value.toLocaleString("en-GB", { maximumFractionDigits: decimals });
}

function trim(value: number): string {
  return value.toLocaleString("en-GB", { maximumFractionDigits: Math.abs(value) >= 100 ? 0 : 1 });
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
