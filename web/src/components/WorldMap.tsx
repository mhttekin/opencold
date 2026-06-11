"use client";

import { geoNaturalEarth1, geoPath } from "d3-geo";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import { Check, Maximize, Minus, Plus, Search, X } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";
import { feature } from "topojson-client";
import type { Topology } from "topojson-specification";

import topology from "@/data/countries-110m.json";

/* ── geometry ── */

const WIDTH = 980; // base unit — the SVG scales responsively to its container
const PAD = 10; // viewBox breathing room so coastlines aren't clipped
const ZOOM_STEP = 1.5;
const ZOOM_MIN = 1;
const ZOOM_MAX = 8;

type CountryShape = { name: string; d: string; cx: number; cy: number };

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

    // Label anchor: centroid of the LARGEST polygon, not the whole geometry —
    // 110m France includes French Guiana and the USA includes Alaska, which
    // would drag a whole-geometry centroid into the ocean.
    const mainlandCentroid = (f: Feature<Geometry, CountryProps>) => {
      if (f.geometry.type !== "MultiPolygon") return path.centroid(f);
      let best: Feature | null = null;
      let bestArea = -1;
      for (const coords of f.geometry.coordinates) {
        const part = {
          type: "Feature",
          properties: {},
          geometry: { type: "Polygon", coordinates: coords },
        } as Feature;
        const a = Math.abs(path.area(part));
        if (a > bestArea) {
          bestArea = a;
          best = part;
        }
      }
      return path.centroid(best ?? f);
    };

    const shapes = features
      .map((f) => {
        const [cx, cy] = mainlandCentroid(f);
        return { name: f.properties.name, d: path(f) ?? "", cx, cy };
      })
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
  { name: "Spain", label: "Spain" },
];

/* ── business hubs the 110m map omits ── */

// Natural Earth's low-poly map drops several small but business-critical
// states (Singapore, Hong Kong, Bahrain, …). The map can't draw them, but they
// should still be reachable from search. These names get merged into the
// type-ahead list and selected as plain region strings — there's just no shape
// to highlight on the map.
const EXTRA_COUNTRIES = [
  "Singapore",
  "Hong Kong",
  "Bahrain",
  "Malta",
  "Mauritius",
  "Monaco",
  "Liechtenstein",
  "Macau",
  "Andorra",
  "San Marino",
  "Maldives",
  "Seychelles",
  "Barbados",
  "Bermuda",
  "Cayman Islands",
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

export function displayName(name: string): string {
  return SHORT_LABELS[name] ?? name;
}

const clamp = (v: number, lo: number, hi: number) =>
  Math.max(lo, Math.min(hi, v));

/* ── atlas: the flat interactive map (right column) ── */

export default function WorldMap({
  selected,
  onToggle,
  terms,
}: {
  selected: string[];
  onToggle: (name: string) => void;
  /** optional localized search-term preview per selected country */
  terms?: Record<string, string>;
}) {
  const { shapes, vbW, vbH } = useWorldGeometry();
  const [hovered, setHovered] = useState<string | null>(null);
  const [view, setView] = useState({ k: 1, tx: 0, ty: 0 });
  const selectedSet = useMemo(() => new Set(selected), [selected]);

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
  const labelled = shapes.filter((s) => selectedSet.has(s.name));

  return (
    <div className="worldmap-frame h-full">
      {/* hovered country name — quiet, top-right of the canvas */}
      <div className="pointer-events-none absolute right-0 top-0 z-10 h-4">
        {hovered && (
          <p className="text-[11px] font-medium text-zinc-500">
            {displayName(hovered)}
          </p>
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
        className={`h-full w-full touch-none select-none ${
          zoomed ? "cursor-grab active:cursor-grabbing" : ""
        }`}
        role="group"
        aria-label="World map — select target countries"
        onPointerDown={onPointerDown}
      >
        <g transform={`translate(${view.tx} ${view.ty}) scale(${view.k})`}>
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

          {/* tiny labels on selected countries, with optional localized
              search-term previews; counter-scaled so they keep their size
              while zooming */}
          {labelled.map((s) => (
            <motion.g
              key={s.name}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.45, ease: "easeOut" }}
              transform={`translate(${s.cx} ${s.cy}) scale(${1 / view.k})`}
              className="pointer-events-none"
            >
              <text textAnchor="middle" className="worldmap-name">
                {displayName(s.name)}
              </text>
              {terms?.[s.name] && (
                <text y="12" textAnchor="middle" className="worldmap-term">
                  {terms[s.name]}
                </text>
              )}
            </motion.g>
          ))}
        </g>
      </svg>
    </div>
  );
}

/* ── atlas controls: selected chips + search + quick-picks ──
 * Lives on the atlas side, anchored to the bottom — an atlas tool, not a
 * form section. The type-ahead panel opens upward so it never clips at the
 * bottom of the page.
 */

export function CountryPicker({
  selected,
  onToggle,
  onClear,
}: {
  selected: string[];
  onToggle: (name: string) => void;
  onClear: () => void;
}) {
  const { shapes } = useWorldGeometry();
  const [query, setQuery] = useState("");
  const [panelOpen, setPanelOpen] = useState(true);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const selectedSet = useMemo(() => new Set(selected), [selected]);

  // clicking anywhere outside the search box closes the type-ahead panel
  useEffect(() => {
    const onDown = (e: PointerEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node))
        setPanelOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, []);

  // Hubs the map can't render — only those not already present as a shape.
  const offMap = useMemo(() => {
    const onMap = new Set(shapes.map((s) => s.name));
    return EXTRA_COUNTRIES.filter((n) => !onMap.has(n));
  }, [shapes]);

  const allNames = useMemo(
    () =>
      [...shapes.map((s) => s.name), ...offMap].sort((a, b) =>
        displayName(a).localeCompare(displayName(b)),
      ),
    [shapes, offMap],
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

  // Keyboard navigation over the suggestion list. When nothing matches, the
  // single "add custom region" row is the lone navigable option (index 0).
  const [activeIndex, setActiveIndex] = useState(0);
  const optionCount = matches.length > 0 ? matches.length : q ? 1 : 0;

  const addCustomRegion = () => {
    const name = query.trim();
    if (!name) return;
    onToggle(name);
    setQuery("");
    setActiveIndex(0);
  };

  const onSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      setPanelOpen(false);
      return;
    }
    if (optionCount === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, optionCount - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (matches.length > 0)
        onToggle(matches[Math.min(activeIndex, matches.length - 1)]);
      else addCustomRegion();
    }
  };

  return (
    <div className="relative rounded-xl border border-zinc-200/70 bg-white/60 p-3">
      {/* selected chips — float above the dock (bottom-anchored, growing
          upward over the map) so the dock height never changes and the map
          never shifts. Pointer events are scoped to the chips themselves. */}
      <div className="pointer-events-none absolute bottom-full left-0 right-0 mb-2 flex flex-wrap items-center gap-1.5">
        <AnimatePresence initial={false}>
          {selected.map((name) => (
            <motion.button
              key={name}
              onClick={() => onToggle(name)}
              initial={{ opacity: 0, scale: 0.92 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.92 }}
              transition={{ duration: 0.16, ease: "easeOut" }}
              className="pointer-events-auto inline-flex cursor-pointer items-center gap-1 rounded-full border border-zinc-200 bg-white/90 py-1 pl-3 pr-1.5 text-xs font-medium text-zinc-700 transition-colors hover:border-zinc-400 hover:text-zinc-900"
              aria-label={`Remove ${displayName(name)}`}
            >
              {displayName(name)}
              <span className="grid size-4 place-items-center rounded-full text-zinc-400">
                <X size={11} />
              </span>
            </motion.button>
          ))}
        </AnimatePresence>
        {selected.length > 0 && (
          <button
            onClick={onClear}
            className="pointer-events-auto ml-1 text-[11px] font-medium text-zinc-400 transition hover:text-zinc-900"
          >
            Clear all
          </button>
        )}
      </div>

      {/* search on its own row, suggestions wrap below */}
      <div className="space-y-2.5">
        <div ref={boxRef} className="relative w-full max-w-[360px]">
          <Search
            size={13}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400"
          />
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActiveIndex(0);
              setPanelOpen(true);
            }}
            onFocus={() => setPanelOpen(true)}
            onKeyDown={onSearchKeyDown}
            placeholder="Search countries or regions…"
            className="h-9 w-full rounded-lg border border-zinc-200 bg-white/80 pl-8 pr-8 text-[13px] text-zinc-900 outline-none transition-colors placeholder:text-zinc-400 focus:border-zinc-400"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 grid size-5 -translate-y-1/2 place-items-center rounded-full text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-900"
            >
              <X size={12} />
            </button>
          )}

          {/* type-ahead panel — opens upward over the atlas */}
          {q.length > 0 && panelOpen && (
            <div className="absolute bottom-[calc(100%+6px)] left-0 z-20 w-full space-y-0.5 rounded-lg border border-zinc-200 bg-white p-1 shadow-sm">
              {matches.length > 0 ? (
                matches.map((name, idx) => {
                  const isSel = selectedSet.has(name);
                  const isActive = idx === activeIndex;
                  return (
                    <button
                      key={name}
                      onClick={() => onToggle(name)}
                      onMouseEnter={() => setActiveIndex(idx)}
                      className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs transition ${
                        isSel
                          ? "bg-zinc-50"
                          : isActive
                            ? "bg-zinc-50"
                            : "hover:bg-zinc-50"
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
                // No country matches — let the user target the raw string as a
                // custom region rather than dead-ending.
                <button
                  onClick={addCustomRegion}
                  className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs transition hover:bg-zinc-50"
                >
                  <Plus size={12} className="shrink-0 text-zinc-400" />
                  <span className="text-zinc-600">
                    Add{" "}
                    <span className="font-medium text-zinc-900">
                      “{query.trim()}”
                    </span>
                  </span>
                </button>
              )}
            </div>
          )}
        </div>

        <div className="flex flex-wrap gap-1.5">
          {SUGGESTED.map((s) => {
            const isSel = selectedSet.has(s.name);
            return (
              <button
                key={s.name}
                onClick={() => onToggle(s.name)}
                className={`rounded-full border px-2.5 py-1 text-[11px] font-medium transition active:scale-[0.97] ${
                  isSel
                    ? "border-zinc-900 bg-zinc-900 text-white"
                    : "border-zinc-200 bg-white/70 text-zinc-600 hover:border-zinc-400"
                }`}
              >
                {s.label}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
