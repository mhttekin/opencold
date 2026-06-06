"use client";

import { geoNaturalEarth1, geoPath } from "d3-geo";
import type { FeatureCollection, Geometry } from "geojson";
import { Check, Maximize, Minus, Plus, Search, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { feature } from "topojson-client";
import type { Topology } from "topojson-specification";

import topology from "@/data/countries-110m.json";

/* ── geometry ── */

const WIDTH = 980; // base unit — the SVG scales responsively to its container
const PAD = 10; // viewBox breathing room so coastlines aren't clipped
const ZOOM_STEP = 1.5;
const ZOOM_MIN = 1;
const ZOOM_MAX = 8;

type CountryShape = { name: string; d: string };

type CountryProps = { name: string };

type WorldGeometry = {
  shapes: CountryShape[];
  vbW: number;
  vbH: number;
};

function useWorldGeometry(): WorldGeometry {
  return useMemo(() => {
    const fc = feature(
      topology as unknown as Topology,
      (topology as unknown as Topology).objects.countries,
    ) as unknown as FeatureCollection<Geometry, CountryProps>;

    const features = fc.features.filter(
      (f) => f.properties.name !== "Antarctica",
    );
    const collection = { type: "FeatureCollection", features } as FeatureCollection;

    // Fit to width, measure the rendered landmass bounds, then re-fit tightly
    // into a normalized [0,0]-origin box. This crops the ocean letterboxing so
    // the map fills the frame, and keeps the zoom/pan maths simple.
    const [[x0, y0], [x1, y1]] = geoPath(
      geoNaturalEarth1().fitWidth(WIDTH, collection),
    ).bounds(collection);
    const vbW = x1 - x0;
    const vbH = y1 - y0;

    const path = geoPath(
      geoNaturalEarth1().fitExtent(
        [
          [0, 0],
          [vbW, vbH],
        ],
        collection,
      ),
    );
    const shapes = features
      .map((f) => ({ name: f.properties.name, d: path(f) ?? "" }))
      .filter((c) => c.d.length > 0);

    return { shapes, vbW, vbH };
  }, []);
}

/* ── suggested quick-picks (regions the backend has strong signals for) ── */

const SUGGESTED: { name: string; label: string }[] = [
  { name: "United States of America", label: "USA" },
  { name: "United Kingdom", label: "UK" },
  { name: "Germany", label: "Germany" },
  { name: "France", label: "France" },
  { name: "India", label: "India" },
  { name: "Brazil", label: "Brazil" },
  { name: "Nigeria", label: "Nigeria" },
];

const SHORT_LABELS: Record<string, string> = {
  "United States of America": "United States",
  "Dem. Rep. Congo": "DR Congo",
  "Central African Rep.": "Central African Rep.",
  "Dominican Rep.": "Dominican Rep.",
  "S. Sudan": "South Sudan",
  "Eq. Guinea": "Eq. Guinea",
  "Bosnia and Herz.": "Bosnia & Herz.",
};

function displayName(name: string): string {
  return SHORT_LABELS[name] ?? name;
}

const clamp = (v: number, lo: number, hi: number) =>
  Math.max(lo, Math.min(hi, v));

/* ── component ── */

export default function WorldMap({
  selected,
  onToggle,
  onClear,
}: {
  selected: string[];
  onToggle: (name: string) => void;
  onClear: () => void;
}) {
  const { shapes, vbW, vbH } = useWorldGeometry();
  const [hovered, setHovered] = useState<string | null>(null);
  const [view, setView] = useState({ k: 1, tx: 0, ty: 0 });
  const [query, setQuery] = useState("");
  const selectedSet = useMemo(() => new Set(selected), [selected]);

  const allNames = useMemo(
    () =>
      shapes
        .map((s) => s.name)
        .sort((a, b) => displayName(a).localeCompare(displayName(b))),
    [shapes],
  );

  // type-ahead: prefix matches first ("nige" → Niger, Nigeria), then substring
  const q = query.trim().toLowerCase();
  const matches = useMemo(() => {
    if (!q) return [];
    const starts: string[] = [];
    const contains: string[] = [];
    for (const name of allNames) {
      const dn = displayName(name).toLowerCase();
      if (dn.startsWith(q) || name.toLowerCase().startsWith(q)) starts.push(name);
      else if (dn.includes(q) || name.toLowerCase().includes(q))
        contains.push(name);
    }
    return [...starts, ...contains].slice(0, 8);
  }, [q, allNames]);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const moved = useRef(false);

  const clampPan = (tx: number, ty: number, k: number) => ({
    tx: clamp(tx, vbW * (1 - k), 0),
    ty: clamp(ty, vbH * (1 - k), 0),
  });

  const zoomBy = (factor: number) =>
    setView((v) => {
      const newK = clamp(v.k * factor, ZOOM_MIN, ZOOM_MAX);
      if (newK === v.k) return v;
      // keep the map centre fixed while zooming
      const px = vbW / 2;
      const py = vbH / 2;
      const tx = px - (px - v.tx) * (newK / v.k);
      const ty = py - (py - v.ty) * (newK / v.k);
      return { k: newK, ...clampPan(tx, ty, newK) };
    });

  const reset = () => setView({ k: 1, tx: 0, ty: 0 });

  // Pan via window listeners (no pointer capture) — capturing the pointer on the
  // SVG would steal the click from the country path, so selection only worked at
  // base zoom. Listening on window keeps drag working while leaving clicks intact.
  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    moved.current = false;
    if (view.k <= 1) return; // nothing to pan at base zoom
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const sx = (vbW + 2 * PAD) / rect.width;
    const sy = (vbH + 2 * PAD) / rect.height;
    const startX = e.clientX;
    const startY = e.clientY;
    const baseTx = view.tx;
    const baseTy = view.ty;

    const onMove = (ev: PointerEvent) => {
      const rawDx = ev.clientX - startX;
      const rawDy = ev.clientY - startY;
      if (Math.abs(rawDx) > 3 || Math.abs(rawDy) > 3) moved.current = true;
      setView((v) => ({
        ...v,
        ...clampPan(baseTx + rawDx * sx, baseTy + rawDy * sy, v.k),
      }));
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const handleToggle = (name: string) => {
    // a pan gesture that ends on a country shouldn't also select it
    if (moved.current) {
      moved.current = false;
      return;
    }
    onToggle(name);
  };

  const zoomed = view.k > 1;
  const canReset = view.k !== 1 || view.tx !== 0 || view.ty !== 0;

  return (
    <div className="space-y-4">
      {/* map */}
      <div className="worldmap-frame">
        {/* hovered country label */}
        <div className="worldmap-label">
          {hovered ? (
            <span className="font-medium text-zinc-700">
              {displayName(hovered)}
            </span>
          ) : (
            <span className="text-zinc-400">
              {selected.length === 0
                ? "Click countries to target"
                : `${selected.length} selected`}
            </span>
          )}
        </div>

        {/* zoom controls */}
        <div className="worldmap-controls">
          <button
            type="button"
            onClick={() => zoomBy(ZOOM_STEP)}
            disabled={view.k >= ZOOM_MAX}
            aria-label="Zoom in"
            className="worldmap-ctrl"
          >
            <Plus size={15} />
          </button>
          <button
            type="button"
            onClick={() => zoomBy(1 / ZOOM_STEP)}
            disabled={view.k <= ZOOM_MIN}
            aria-label="Zoom out"
            className="worldmap-ctrl"
          >
            <Minus size={15} />
          </button>
          <button
            type="button"
            onClick={reset}
            disabled={!canReset}
            aria-label="Reset view"
            className="worldmap-ctrl"
          >
            <Maximize size={14} />
          </button>
        </div>

        <svg
          ref={svgRef}
          viewBox={`${-PAD} ${-PAD} ${vbW + 2 * PAD} ${vbH + 2 * PAD}`}
          className={`block h-auto w-full touch-none select-none ${
            zoomed ? "cursor-grab active:cursor-grabbing" : ""
          }`}
          role="group"
          aria-label="World map — select target countries"
          onPointerDown={onPointerDown}
        >
          <g
            transform={`translate(${view.tx} ${view.ty}) scale(${view.k})`}
          >
            {shapes.map((c) => {
              const isSel = selectedSet.has(c.name);
              return (
                <path
                  key={c.name}
                  d={c.d}
                  className={`worldmap-country ${isSel ? "worldmap-country--on" : ""}`}
                  onClick={() => handleToggle(c.name)}
                  onMouseEnter={() => setHovered(c.name)}
                  onMouseLeave={() => setHovered(null)}
                  tabIndex={0}
                  role="button"
                  aria-pressed={isSel}
                  aria-label={displayName(c.name)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onToggle(c.name);
                    }
                  }}
                />
              );
            })}
          </g>
        </svg>
      </div>

      {/* suggested quick-picks — single line */}
      <div>
        <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-zinc-400">
          Suggested
        </p>
        <div className="flex flex-nowrap gap-1.5 overflow-x-auto pb-0.5">
          {SUGGESTED.map((s) => {
            const isSel = selectedSet.has(s.name);
            return (
              <button
                key={s.name}
                onClick={() => onToggle(s.name)}
                className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-medium transition active:scale-[0.97] ${
                  isSel
                    ? "border-zinc-900 bg-zinc-900 text-white"
                    : "border-zinc-200 bg-white text-zinc-600 hover:border-zinc-400"
                }`}
              >
                {s.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* type-ahead search over all countries */}
      <div>
        <div className="relative">
          <Search
            size={14}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search any country…"
            className="h-10 w-full rounded-lg border border-zinc-200 bg-white pl-9 pr-9 text-sm text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute right-2.5 top-1/2 grid size-5 -translate-y-1/2 place-items-center rounded-full text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-900"
            >
              <X size={12} />
            </button>
          )}
        </div>

        {/* matches accordion */}
        <div
          className="accordion-body mt-1"
          style={{ gridTemplateRows: q.length > 0 ? "1fr" : "0fr" }}
        >
          <div className="min-h-0 overflow-hidden">
            <div className="space-y-0.5 rounded-lg border border-zinc-100 bg-zinc-50/60 p-1">
              {matches.length > 0 ? (
                matches.map((name) => {
                  const isSel = selectedSet.has(name);
                  return (
                    <button
                      key={name}
                      onClick={() => onToggle(name)}
                      className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs transition ${
                        isSel ? "bg-white shadow-sm" : "hover:bg-white/70"
                      }`}
                    >
                      <span
                        className={`font-medium ${isSel ? "text-zinc-900" : "text-zinc-600"}`}
                      >
                        {displayName(name)}
                      </span>
                      {isSel && (
                        <Check size={12} className="ml-auto text-zinc-900" />
                      )}
                    </button>
                  );
                })
              ) : (
                <p className="px-2.5 py-1.5 text-xs text-zinc-400">
                  No countries match “{query.trim()}”
                </p>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* selected chips */}
      {selected.length > 0 && (
        <div>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
              Selected — {selected.length}
            </p>
            <button
              onClick={onClear}
              className="text-[11px] font-medium text-zinc-400 transition hover:text-zinc-900"
            >
              Clear all
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {selected.map((name) => (
              <span
                key={name}
                className="inline-flex items-center gap-1 rounded-full bg-zinc-100 py-1 pl-3 pr-1.5 text-xs font-medium text-zinc-700"
              >
                {displayName(name)}
                <button
                  onClick={() => onToggle(name)}
                  className="grid size-4 place-items-center rounded-full text-zinc-400 transition hover:bg-zinc-200 hover:text-zinc-900"
                  aria-label={`Remove ${displayName(name)}`}
                >
                  <X size={11} />
                </button>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
