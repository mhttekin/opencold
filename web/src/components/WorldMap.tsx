"use client";

import { geoNaturalEarth1, geoPath } from "d3-geo";
import type { FeatureCollection, Geometry } from "geojson";
import { X } from "lucide-react";
import { useMemo, useState } from "react";
import { feature } from "topojson-client";
import type { Topology } from "topojson-specification";

import topology from "@/data/countries-110m.json";

/* ── geometry ── */

const WIDTH = 800;
const HEIGHT = 412;

type CountryShape = { name: string; d: string };

type CountryProps = { name: string };

function useWorldShapes(): CountryShape[] {
  return useMemo(() => {
    const fc = feature(
      topology as unknown as Topology,
      (topology as unknown as Topology).objects.countries,
    ) as unknown as FeatureCollection<Geometry, CountryProps>;

    const features = fc.features.filter(
      (f) => f.properties.name !== "Antarctica",
    );

    const projection = geoNaturalEarth1().fitExtent(
      [
        [8, 8],
        [WIDTH - 8, HEIGHT - 8],
      ],
      { type: "FeatureCollection", features } as FeatureCollection,
    );
    const path = geoPath(projection);

    return features
      .map((f) => ({ name: f.properties.name, d: path(f) ?? "" }))
      .filter((c) => c.d.length > 0);
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
  const shapes = useWorldShapes();
  const [hovered, setHovered] = useState<string | null>(null);
  const selectedSet = useMemo(() => new Set(selected), [selected]);

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

        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="block h-auto w-full"
          role="group"
          aria-label="World map — select target countries"
        >
          {shapes.map((c) => {
            const isSel = selectedSet.has(c.name);
            return (
              <path
                key={c.name}
                d={c.d}
                className={`worldmap-country ${isSel ? "worldmap-country--on" : ""}`}
                onClick={() => onToggle(c.name)}
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
