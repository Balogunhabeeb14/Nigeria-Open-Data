"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { Series } from "@/lib/series";
import { compact, full, niceTicks } from "@/lib/series";

// Width before the browser has measured the container (server render).
const DEFAULT_WIDTH = 720;
const NARROW = 480;
const LINE = "#15803d";      // primary-700; checked for contrast on white
const GRID = "#e2e8f0";      // slate-200
const AXIS_TEXT = "#64748b"; // slate-500
const INK = "#0f172a";       // slate-900

interface Props {
  series: Series;
  /** What is plotted, for the accessible name. */
  label: string;
}

/**
 * One series over time: a line, a labelled end point, and a crosshair that
 * reads out the value at whichever period the pointer or keyboard is on.
 * Every value shown here is also in the table below the chart.
 */
export default function SeriesChart({ series, label }: Props) {
  const { points, unit } = series;
  const [active, setActive] = useState<number | null>(null);
  const [WIDTH, setWidth] = useState(DEFAULT_WIDTH);
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const titleId = useId();

  // Draw at the container's real width so text stays a readable size on a
  // phone, instead of shrinking a desktop-sized drawing.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => setWidth(Math.max(260, Math.round(el.clientWidth)));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const narrow = WIDTH < NARROW;
  const HEIGHT = narrow ? 230 : 300;
  const MARGIN = useMemo(
    () => ({ top: 16, right: narrow ? 52 : 72, bottom: 32, left: narrow ? 40 : 52 }),
    [narrow],
  );

  const geometry = useMemo(() => {
    const values = points.map((p) => p.value);
    const ticks = niceTicks(Math.min(...values), Math.max(...values));
    const yMin = ticks[0];
    const yMax = ticks[ticks.length - 1];
    const innerW = WIDTH - MARGIN.left - MARGIN.right;
    const innerH = HEIGHT - MARGIN.top - MARGIN.bottom;
    const x = (i: number) => MARGIN.left + (points.length === 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
    const y = (v: number) => MARGIN.top + (1 - (v - yMin) / (yMax - yMin || 1)) * innerH;
    const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");

    // A handful of period labels (fewer on a phone), always with first and last.
    const every = Math.max(1, Math.ceil(points.length / (narrow ? 3 : 6)));
    const xLabels = points
      .map((p, i) => ({ i, text: p.period }))
      .filter(({ i }) => i % every === 0 && points.length - 1 - i >= every / 2);
    xLabels.push({ i: points.length - 1, text: points[points.length - 1].period });

    return { ticks, x, y, path, xLabels, innerW };
  }, [points, WIDTH, HEIGHT, MARGIN, narrow]);

  const { ticks, x, y, path, xLabels, innerW } = geometry;
  const last = points.length - 1;
  const shown = active ?? last;

  const indexFromPointer = (clientX: number) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const px = ((clientX - rect.left) / rect.width) * WIDTH;
    const ratio = (px - MARGIN.left) / innerW;
    return Math.min(last, Math.max(0, Math.round(ratio * last)));
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const from = active ?? last;
    const next =
      e.key === "ArrowLeft" ? from - 1 :
      e.key === "ArrowRight" ? from + 1 :
      e.key === "Home" ? 0 :
      e.key === "End" ? last : null;
    if (next === null) return;
    e.preventDefault();
    setActive(Math.min(last, Math.max(0, next)));
  };

  const readout = `${points[shown].period}: ${full(points[shown].value)}${unit ? ` ${unit}` : ""}`;
  // Keep the tooltip inside the plot: flip it to the left of the crosshair near the right edge.
  const tipLeft = x(shown) > WIDTH * 0.6;

  return (
    <figure className="m-0">
      <div className="relative" ref={wrapRef}>
        <svg
          ref={svgRef}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="w-full h-auto touch-none select-none outline-none focus-visible:ring-2 focus-visible:ring-primary-500 rounded-lg"
          role="img"
          aria-labelledby={titleId}
          tabIndex={0}
          onPointerMove={(e) => setActive(indexFromPointer(e.clientX))}
          onPointerDown={(e) => setActive(indexFromPointer(e.clientX))}
          onPointerLeave={() => setActive(null)}
          onBlur={() => setActive(null)}
          onKeyDown={onKeyDown}
        >
          <title id={titleId}>
            {`${label}, ${points[0].period} to ${points[last].period}. Latest value ${full(points[last].value)}${unit ? ` ${unit}` : ""}. Use the arrow keys to read each period.`}
          </title>

          {/* Gridlines and y ticks */}
          {ticks.map((t) => (
            <g key={t}>
              <line x1={MARGIN.left} x2={WIDTH - MARGIN.right} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={1} />
              <text x={MARGIN.left - 8} y={y(t)} textAnchor="end" dominantBaseline="middle" fontSize={12} fill={AXIS_TEXT} style={{ fontVariantNumeric: "tabular-nums" }}>
                {compact(t)}
              </text>
            </g>
          ))}

          {/* Period labels */}
          {xLabels.map(({ i, text }) => (
            <text key={i} x={x(i)} y={HEIGHT - 10} textAnchor={i === last ? "end" : i === 0 ? "start" : "middle"} fontSize={12} fill={AXIS_TEXT} style={{ fontVariantNumeric: "tabular-nums" }}>
              {text}
            </text>
          ))}

          {/* The series */}
          <path d={path} fill="none" stroke={LINE} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

          {/* Latest value, labelled at the line's end */}
          <circle cx={x(last)} cy={y(points[last].value)} r={4.5} fill={LINE} stroke="#ffffff" strokeWidth={2} />
          {active === null && (
            <text x={x(last) + 10} y={y(points[last].value)} dominantBaseline="middle" fontSize={13} fontWeight={600} fill={INK}>
              {compact(points[last].value)}
            </text>
          )}

          {/* Crosshair */}
          {active !== null && (
            <g pointerEvents="none">
              <line x1={x(active)} x2={x(active)} y1={MARGIN.top} y2={HEIGHT - MARGIN.bottom} stroke={AXIS_TEXT} strokeWidth={1} />
              <circle cx={x(active)} cy={y(points[active].value)} r={5} fill={LINE} stroke="#ffffff" strokeWidth={2} />
            </g>
          )}
        </svg>

        {active !== null && (
          <div
            className="pointer-events-none absolute top-2 rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-md"
            style={{
              left: tipLeft ? undefined : `calc(${(x(active) / WIDTH) * 100}% + 12px)`,
              right: tipLeft ? `calc(${100 - (x(active) / WIDTH) * 100}% + 12px)` : undefined,
            }}
          >
            <p className="text-base font-semibold text-slate-900 leading-tight tabular-nums">
              {full(points[active].value)}
              {unit && <span className="ml-1 text-sm font-normal text-slate-500">{unit}</span>}
            </p>
            <p className="text-sm text-slate-500 tabular-nums">{points[active].period}</p>
          </div>
        )}
      </div>

      {/* Same reading for screen readers as sighted users get from the tooltip */}
      <p className="sr-only" aria-live="polite">{active !== null ? readout : ""}</p>
    </figure>
  );
}
