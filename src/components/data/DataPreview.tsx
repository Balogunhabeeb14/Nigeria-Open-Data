import type { DataTable } from "@/lib/ckan";
import { full } from "@/lib/series";

const HEADINGS: Record<string, string> = {
  period: "Period",
  value: "Value",
  unit: "Unit",
  geo_name: "Place",
  geo_code: "Place code",
  geo_level: "Level",
};

// Columns that say the same thing on every row are left out of the preview;
// they are still in the download.
const PREVIEW_COLUMNS = ["period", "geo_name", "value", "unit"];

interface Props {
  table: DataTable;
}

/** The dataset's rows, newest first. Scrolls inside its own box when long. */
export default function DataPreview({ table }: Props) {
  const available = new Set(table.fields.map((f) => f.id));
  const hasStandardShape = available.has("period") && available.has("value");
  const isEmpty = (cell: unknown) => cell === null || cell === undefined || cell === "";
  const columns = (hasStandardShape
    ? PREVIEW_COLUMNS.filter((c) => available.has(c))
    : table.fields.map((f) => f.id).slice(0, 8)
  ).filter(
    // A column with nothing in it (a series with no stated unit, say) is noise.
    (c) => c === "value" || table.records.some((r) => !isEmpty(r[c])),
  );

  const rows = hasStandardShape
    ? [...table.records].sort((a, b) => String(b.period).localeCompare(String(a.period)))
    : table.records;

  const numeric = new Set(
    table.fields.filter((f) => f.type === "numeric" || f.type === "int" || f.type === "float").map((f) => f.id),
  );

  return (
    <div>
      <div className="max-h-[26rem] overflow-auto rounded-xl border border-slate-200" tabIndex={0} role="region" aria-label="Data table">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-slate-50 text-left">
            <tr>
              {columns.map((c) => (
                <th key={c} scope="col" className={`px-4 py-3 font-semibold text-slate-700 border-b border-slate-200 ${numeric.has(c) ? "text-right" : ""}`}>
                  {HEADINGS[c] ?? c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-slate-100 last:border-0">
                {columns.map((c) => {
                  const cell = row[c];
                  const isNumber = numeric.has(c) && cell !== null && cell !== "" && Number.isFinite(Number(cell));
                  return (
                    <td key={c} className={`px-4 py-2.5 text-slate-800 ${numeric.has(c) ? "text-right tabular-nums" : ""}`}>
                      {isEmpty(cell)
                        ? (c === "value" ? <span className="text-slate-400">No value</span> : "")
                        : isNumber ? full(Number(cell)) : String(cell)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-sm text-slate-500">
        {rows.length < table.total
          ? `Showing ${rows.length.toLocaleString("en-GB")} of ${table.total.toLocaleString("en-GB")} rows. Download the file for all of them.`
          : `${table.total.toLocaleString("en-GB")} ${table.total === 1 ? "row" : "rows"}. The download has every column.`}
      </p>
    </div>
  );
}
