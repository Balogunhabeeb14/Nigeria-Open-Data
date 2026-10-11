"use client";

import { useId, useMemo, useState } from "react";
import type { PlaceTable } from "@/lib/series";
import { compact, full, periodLabel } from "@/lib/series";
import SeriesChart from "@/components/data/SeriesChart";

const BAR = "#15803d"; // same hue as the line chart; one measure, one colour
const INITIAL_ROWS = 10;

interface Props {
  table: PlaceTable;
  /** What is measured, for accessible names. */
  label: string;
}

/**
 * A table covering many places: who is highest and lowest in the latest
 * period, and how any one place has changed over time.
 *
 * Bars rank the latest period. Choosing a place (from the bars or the list)
 * draws its history. Every figure is also in the table further down the page.
 */
export default function PlaceExplorer({ table, label }: Props) {
  const { places, periods, unit } = table;
  const latest = periods[periods.length - 1];
  const selectId = useId();

  const ranked = useMemo(
    () =>
      places
        .map((place) => ({ place, value: place.points.find((p) => p.period === latest)?.value }))
        .filter((row): row is { place: (typeof places)[number]; value: number } => row.value !== undefined)
        .sort((a, b) => b.value - a.value),
    [places, latest],
  );

  const [selected, setSelected] = useState<string>(ranked[0]?.place.code ?? places[0].code);
  const [showAll, setShowAll] = useState(false);

  const current = places.find((p) => p.code === selected) ?? places[0];
  const max = Math.max(...ranked.map((r) => r.value), 0);
  const total = ranked.reduce((sum, r) => sum + r.value, 0);
  const visible = showAll ? ranked : ranked.slice(0, INITIAL_ROWS);
  const selectedRank = ranked.findIndex((r) => r.place.code === selected);

  return (
    <div className="space-y-10">
      <section aria-label={`${label}: ranking for ${periodLabel(latest)}`}>
        <h3 className="text-base font-semibold text-slate-900">
          {periodLabel(latest)}, highest first
        </h3>
        <p className="text-sm text-slate-500 mb-4">
          {ranked.length} places{unit ? ` · ${unit}` : ""}. Choose one to see its history below.
        </p>

        <ol className="space-y-1">
          {visible.map(({ place, value }, index) => {
            const isSelected = place.code === selected;
            return (
              <li key={place.code}>
                <button
                  type="button"
                  onClick={() => setSelected(place.code)}
                  aria-pressed={isSelected}
                  title={`${place.name}: ${full(value)}${unit ? ` ${unit}` : ""}${total > 0 ? ` (${((value / total) * 100).toFixed(1)}% of the total)` : ""}`}
                  className={`w-full grid grid-cols-[1.5rem_minmax(5.5rem,9rem)_1fr_auto] items-center gap-3 rounded-lg px-2 py-1.5 text-left text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 ${
                    isSelected ? "bg-primary-50" : "hover:bg-slate-50"
                  }`}
                >
                  <span className="text-slate-400 tabular-nums text-right">{index + 1}</span>
                  <span className={`truncate ${isSelected ? "font-semibold text-slate-900" : "text-slate-700"}`}>{place.name}</span>
                  <span className="h-3 rounded-r" aria-hidden="true">
                    <span
                      className="block h-3 rounded-r"
                      style={{ width: `${max > 0 ? Math.max((value / max) * 100, 0.5) : 0}%`, backgroundColor: BAR, opacity: isSelected ? 1 : 0.75 }}
                    />
                  </span>
                  <span className="tabular-nums text-slate-900 font-medium">{compact(value)}</span>
                </button>
              </li>
            );
          })}
        </ol>

        {ranked.length > INITIAL_ROWS && (
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            aria-expanded={showAll}
            className="mt-3 text-sm font-medium text-primary-700 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 rounded"
          >
            {showAll ? "Show the top 10 only" : `Show all ${ranked.length}`}
          </button>
        )}
      </section>

      <section aria-label={`${label}: history of one place`}>
        <div className="flex flex-wrap items-end justify-between gap-3 mb-4">
          <div>
            <h3 className="text-base font-semibold text-slate-900">{current.name} over time</h3>
            <p className="text-sm text-slate-500">
              {current.points.length > 0 && `${periodLabel(current.points[0].period)} to ${periodLabel(current.points[current.points.length - 1].period)}`}
              {selectedRank >= 0 && ` · ranked ${selectedRank + 1} of ${ranked.length} in ${periodLabel(latest)}`}
            </p>
          </div>
          <div>
            <label htmlFor={selectId} className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">
              Place
            </label>
            <select
              id={selectId}
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              {places.map((place) => (
                <option key={place.code} value={place.code}>{place.name}</option>
              ))}
            </select>
          </div>
        </div>

        {current.points.length >= 2 ? (
          <SeriesChart key={current.code} series={{ points: current.points, unit, place: current.name }} label={`${label}, ${current.name}`} />
        ) : (
          <p className="text-sm text-slate-500">Only one period is available for {current.name}, so there is no trend to draw.</p>
        )}
      </section>
    </div>
  );
}
