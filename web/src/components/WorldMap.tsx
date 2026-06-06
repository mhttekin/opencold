"use client";

import { geoNaturalEarth1, geoPath } from "d3-geo";
import type { FeatureCollection, Geometry } from "geojson";
import { Maximize, Minus, Plus, X } from "lucide-react";
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
  { name: "United States of America", label: "United States" },
  { name: "United Kingdom", label: "United Kingdom" },
  { name: "Germany", label: "Germany" },
  { name: "France", label: "France" },
  { name: "India", label: "India" },
  { name: "Bangladesh", label: "Bangladesh" },
  { name: "Pakistan", label: "Pakistan" },
  { name: "Turkey", label: "Turkey" },
  { name: "Indonesia", label: "Indonesia" },
  { name: "Nigeria", label: "Nigeria" },
  { name: "Kenya", label: "Kenya" },
  { name: "Brazil", label: "Brazil" },
  { name: "Mexico", label: "Mexico" },
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
  const selectedSet = useMemo(() => new Set(selected), [selected]);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const drag = useRef<{ x: number; y: number; tx: number; ty: number } | null>(
    null,
  );
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

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    moved.current = false;
    if (view.k <= 1) return;
    drag.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!drag.current || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const sx = (vbW + 2 * PAD) / rect.width;
    const sy = (vbH + 2 * PAD) / rect.height;
    const rawDx = e.clientX - drag.current.x;
    const rawDy = e.clientY - drag.current.y;
    if (Math.abs(rawDx) > 3 || Math.abs(rawDy) > 3) moved.current = true;
    setView((v) => ({
      ...v,
      ...clampPan(drag.current!.tx + rawDx * sx, drag.current!.ty + rawDy * sy, v.k),
    }));
  };

  const onPointerUp = () => {
    drag.current = null;
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
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={onPointerUp}
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

      {/* suggested quick-picks */}
      <div>
        <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-zinc-400">
          Suggested
        </p>
        <div className="flex flex-wrap gap-1.5">
          {SUGGESTED.map((s) => {
            const isSel = selectedSet.has(s.name);
            return (
              <button
                key={s.name}
                onClick={() => onToggle(s.name)}
                className={`rounded-full border px-3 py-1 text-xs font-medium transition active:scale-[0.97] ${
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
