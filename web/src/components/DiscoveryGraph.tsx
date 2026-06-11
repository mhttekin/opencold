"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useState, useSyncExternalStore } from "react";

/* ── discovery constellation ──
 * Research expansion model: seed → countries/regions → companies → evidence.
 * Small independent clusters; only one is visually dominant at a time, the
 * previous one ghosts to near-invisible, anything older fades out.
 *
 * Everything is deterministic static data — positions, control points, and
 * delays are precomputed from these tables (no randomness, no Date.now()),
 * and the whole canvas mounts client-side only, so SSR and client markup
 * can never disagree (hydration-safe).
 */

type Evidence = { t: string; green?: boolean };

type Company = {
  name: string;
  pos: { x: number; y: number }; // offset from its country node
  evidence: Evidence[]; // 1-3 lines, varied depth
};

type Group = {
  country: string;
  pos: { x: number; y: number }; // country anchor, relative to seed center
  align?: "right"; // text grows leftward from its anchor
  companies: Company[]; // usually one; sometimes two
};

type Cluster = {
  seed: [string, string];
  anchor: { x: string; y: string }; // seed position inside the hero canvas
  groups: Group[];
};

const CLUSTERS: Cluster[] = [
  {
    // upper-left, fanning right (NE / E / SE); companies continue outward
    seed: ["insurance", "MENA"],
    anchor: { x: "15%", y: "23%" },
    groups: [
      {
        country: "Saudi Arabia",
        pos: { x: 112, y: -50 },
        companies: [
          {
            name: "Tawuniya",
            pos: { x: 118, y: -52 },
            evidence: [
              { t: "tawuniya.com.sa" },
              { t: "✓ fit 96", green: true },
            ],
          },
        ],
      },
      {
        country: "UAE",
        pos: { x: 172, y: 28 },
        companies: [
          {
            name: "Daman",
            pos: { x: 138, y: 26 },
            evidence: [{ t: "«التأمين الصحي» on site" }],
          },
        ],
      },
      {
        country: "Morocco",
        pos: { x: 62, y: 92 },
        companies: [
          {
            name: "Wafa Assurance",
            pos: { x: 100, y: 46 },
            evidence: [
              { t: "subsidiary of Al Mada" },
              { t: "✓ fit 91", green: true },
            ],
          },
        ],
      },
    ],
  },
  {
    // upper-right, expanding left and down (W / SW / S / SE)
    seed: ["logistics", "western europe"],
    anchor: { x: "72%", y: "16%" },
    groups: [
      {
        country: "UK",
        pos: { x: -206, y: -28 },
        align: "right",
        companies: [
          {
            name: "Davies Turner",
            pos: { x: -132, y: -20 },
            evidence: [
              { t: "website verified" },
              { t: "phone found" },
              { t: "✓ fit 93", green: true },
            ],
          },
        ],
      },
      {
        country: "Germany",
        pos: { x: -150, y: 60 },
        align: "right",
        companies: [
          {
            name: "Dachser",
            pos: { x: -118, y: 60 },
            evidence: [
              { t: "„Spedition“ on homepage" },
              { t: "✓ fit 95", green: true },
            ],
          },
        ],
      },
      {
        country: "France",
        pos: { x: -50, y: 108 },
        align: "right",
        companies: [
          {
            name: "Bolloré Logistics",
            pos: { x: -70, y: 58 },
            evidence: [
              { t: "acquired by CMA CGM" },
              { t: "✓ fit 94", green: true },
            ],
          },
        ],
      },
      {
        country: "Spain",
        pos: { x: 38, y: 100 },
        companies: [
          {
            name: "Carreras Grupo Logístico",
            pos: { x: 84, y: 52 },
            evidence: [{ t: "address found" }, { t: "✓ fit 89", green: true }],
          },
        ],
      },
    ],
  },
  {
    // center, growing upward (NW / N / NE); Brazil branches twice
    seed: ["dental clinics", "LATAM"],
    anchor: { x: "44%", y: "42%" },
    groups: [
      {
        country: "Mexico",
        pos: { x: -138, y: -82 },
        align: "right",
        companies: [
          {
            name: "Dentalia",
            pos: { x: -122, y: -70 },
            evidence: [{ t: "70+ clinics" }, { t: "✓ fit 95", green: true }],
          },
        ],
      },
      {
        country: "Brazil",
        pos: { x: 60, y: -106 },
        companies: [
          {
            name: "OdontoCompany",
            pos: { x: 48, y: -86 },
            evidence: [{ t: "“rede odontológica”" }],
          },
          {
            name: "Sorridents",
            pos: { x: 96, y: -44 },
            evidence: [{ t: "✓ fit 93", green: true }],
          },
        ],
      },
      {
        country: "Colombia",
        pos: { x: 170, y: -26 },
        companies: [
          {
            name: "Sonría",
            pos: { x: 138, y: -56 },
            evidence: [{ t: "address found" }, { t: "✓ fit 92", green: true }],
          },
        ],
      },
    ],
  },
];

// mobile: one cluster at a time, groups cascade right-down from the card
const MOBILE_ANCHOR = { x: "6%", y: "10%" };
const MOBILE_POS = [
  { x: 44, y: 52 },
  { x: 70, y: 118 },
  { x: 40, y: 184 },
  { x: 66, y: 250 },
];
const MOBILE_COMPANY_POS = { x: 78, y: 30 };

const EASE = [0.22, 1, 0.36, 1] as const;
const GROUP_STEP = 0.55; // seconds between branches starting
const COMPANY_STEP = 0.3; // extra stagger between companies of one country
const ROTATE = 8; // seconds between clusters (mobile: +1)
const GHOST_OPACITY = 0.05; // previous cluster: a barely-there trace

const r1 = (n: number) => Math.round(n * 10) / 10;

/* gently bowed line — organic, not a bracket or flowchart connector */
function organic(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  bow: number,
) {
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  return `M ${r1(x1)} ${r1(y1)} Q ${r1(mx + (-dy / len) * bow)} ${r1(my + (dx / len) * bow)}, ${r1(x2)} ${r1(y2)}`;
}

function DrawnPath({
  d,
  delay,
  dur,
  opacity,
  instant,
}: {
  d: string;
  delay: number;
  dur: number;
  opacity: number;
  instant: boolean;
}) {
  return (
    <motion.path
      d={d}
      fill="none"
      stroke="#DEDDD8"
      strokeWidth="1"
      strokeOpacity={opacity}
      initial={instant ? false : { pathLength: 0, opacity: 0 }}
      animate={{ pathLength: 1, opacity: 1 }}
      transition={
        instant
          ? { duration: 0 }
          : {
              pathLength: { delay, duration: dur, ease: "easeInOut" },
              opacity: { delay, duration: 0.25 },
            }
      }
    />
  );
}

/* node positioned at (x, y); centered on y unless top-anchored */
function Node({
  x,
  y,
  align,
  top,
  delay,
  instant,
  children,
}: {
  x: number;
  y: number;
  align?: "right";
  top?: boolean;
  delay: number;
  instant: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`absolute whitespace-nowrap ${top ? "" : "-translate-y-1/2"} ${align === "right" ? "-translate-x-full" : ""}`}
      style={{ left: x, top: y }}
    >
      <motion.div
        initial={instant ? false : { opacity: 0, y: 5, filter: "blur(2px)" }}
        animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
        transition={
          instant ? { duration: 0 } : { delay, duration: 0.5, ease: EASE }
        }
      >
        {children}
      </motion.div>
    </div>
  );
}

/* ── one cluster ── */

function ClusterBloom({
  cluster,
  compact,
  dimmed,
  instant,
}: {
  cluster: Cluster;
  compact: boolean;
  dimmed: boolean;
  instant: boolean;
}) {
  const anchor = compact ? MOBILE_ANCHOR : cluster.anchor;

  const groups = cluster.groups.map((g, i) =>
    compact
      ? {
          ...g,
          pos: MOBILE_POS[i],
          align: undefined,
          companies: g.companies.slice(0, 1).map((co) => ({
            ...co,
            pos: MOBILE_COMPANY_POS,
            evidence: co.evidence.slice(0, 2),
          })),
        }
      : g,
  );

  return (
    <motion.div
      initial={{ opacity: instant ? 1 : 0 }}
      animate={{ opacity: dimmed ? GHOST_OPACITY : 1 }}
      exit={{ opacity: 0, transition: { duration: 0.5, ease: "easeInOut" } }}
      transition={{ duration: dimmed ? 0.5 : 0.6, ease: "easeInOut" }}
      className="absolute"
      style={{ left: anchor.x, top: anchor.y }}
    >
      {/* branch lines: seed → country, then country → each company */}
      <svg
        className="absolute left-0 top-0 overflow-visible"
        width="2"
        height="2"
        aria-hidden
      >
        {groups.map((g, i) => {
          const t0 = 0.55 + i * GROUP_STEP;
          const len = Math.hypot(g.pos.x, g.pos.y) || 1;
          const ux = g.pos.x / len;
          const uy = g.pos.y / len;
          const start = compact
            ? { x: 24 + ux * 26, y: 12 + uy * 12 }
            : { x: ux * 54, y: uy * 25 };
          const end = { x: g.pos.x - ux * 12, y: g.pos.y - uy * 12 };
          const sideways = g.align === "right" ? -1 : 1;

          return (
            <g key={i}>
              <DrawnPath
                d={organic(start.x, start.y, end.x, end.y, i % 2 ? -10 : 12)}
                delay={t0}
                dur={0.55}
                opacity={0.75}
                instant={instant}
              />
              {g.companies.map((co, ci) => {
                const clen = Math.hypot(co.pos.x, co.pos.y) || 1;
                const cux = co.pos.x / clen;
                const cuy = co.pos.y / clen;
                const from = {
                  x: g.pos.x + sideways * 12,
                  y: g.pos.y + (co.pos.y >= 0 ? 11 : -11),
                };
                const to = {
                  x: g.pos.x + co.pos.x - cux * 14,
                  y: g.pos.y + co.pos.y - cuy * 14,
                };
                return (
                  <DrawnPath
                    key={ci}
                    d={organic(
                      from.x,
                      from.y,
                      to.x,
                      to.y,
                      (i + ci) % 2 ? 8 : -8,
                    )}
                    delay={t0 + 0.6 + ci * COMPANY_STEP}
                    dur={0.5}
                    opacity={0.6}
                    instant={instant}
                  />
                );
              })}
            </g>
          );
        })}
      </svg>

      {/* seed card — a small floating UI card, not a bubble */}
      <div
        className="absolute left-0 top-0"
        style={{
          transform: compact ? "translate(0, -50%)" : "translate(-50%, -50%)",
        }}
      >
        <motion.div
          initial={instant ? false : { opacity: 0, y: 4, filter: "blur(3px)" }}
          animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          transition={
            instant
              ? { duration: 0 }
              : { delay: 0.15, duration: 0.6, ease: EASE }
          }
          className="relative"
        >
          {!instant && !dimmed && (
            <motion.span
              aria-hidden
              className="absolute -inset-2 rounded-xl border border-zinc-400/35"
              initial={{ opacity: 0, scale: 0.88 }}
              animate={{ opacity: [0.3, 0], scale: [0.88, 1.25] }}
              transition={{ delay: 0.45, duration: 2, ease: "easeOut" }}
            />
          )}
          <div className="rounded-lg border border-[#DEDDD8] bg-white/85 px-3 py-2 shadow-[0_1px_3px_rgba(0,0,0,0.05)] backdrop-blur-[2px]">
            <p className="font-code text-[11px] leading-[1.45] text-zinc-800">
              {cluster.seed[0]}
            </p>
            <p className="font-code text-[11px] leading-[1.45] text-zinc-500">
              {cluster.seed[1]}
            </p>
          </div>
        </motion.div>
      </div>

      {/* country chip → scattered companies → nested evidence reveal */}
      {groups.map((g, i) => {
        const t = 0.95 + i * GROUP_STEP;
        return (
          <div key={i}>
            <Node
              x={g.pos.x}
              y={g.pos.y}
              align={g.align}
              delay={t}
              instant={instant}
            >
              <span className="inline-block rounded border border-[#E2E1DC]/90 bg-white/55 px-1.5 py-px font-code text-[10px] text-zinc-500">
                {g.country}
              </span>
            </Node>
            {g.companies.map((co, ci) => {
              const ct = t + 0.4 + ci * COMPANY_STEP;
              const cx = g.pos.x + co.pos.x;
              const cy = g.pos.y + co.pos.y;
              return (
                <div key={ci}>
                  <Node
                    x={cx}
                    y={cy}
                    align={g.align}
                    delay={ct}
                    instant={instant}
                  >
                    <span className="text-[13px] font-medium tracking-tight text-zinc-800">
                      {co.name}
                    </span>
                  </Node>
                  {/* delicate indented evidence behind a hairline divider */}
                  <Node
                    x={cx}
                    y={cy + 11}
                    align={g.align}
                    top
                    delay={ct + 0.25}
                    instant={instant}
                  >
                    <div
                      className={
                        g.align === "right"
                          ? "border-r border-[#E2E1DC] pr-2 text-right"
                          : "border-l border-[#E2E1DC] pl-2"
                      }
                    >
                      {co.evidence.map((ev, j) => (
                        <motion.p
                          key={j}
                          initial={
                            instant
                              ? false
                              : { opacity: 0, x: g.align === "right" ? 3 : -3 }
                          }
                          animate={{ opacity: 1, x: 0 }}
                          transition={
                            instant
                              ? { duration: 0 }
                              : {
                                  delay: ct + 0.3 + j * 0.2,
                                  duration: 0.4,
                                  ease: EASE,
                                }
                          }
                          className={`font-code text-[10px] leading-[1.6] ${ev.green ? "text-emerald-600" : "text-zinc-400"}`}
                          dir="auto"
                        >
                          {ev.t}
                        </motion.p>
                      ))}
                    </div>
                  </Node>
                </div>
              );
            })}
          </div>
        );
      })}
    </motion.div>
  );
}

/* ── ambient canvas: one active cluster, the previous as a ghost trace ── */

// client-only mount: false during SSR/hydration, true right after — the
// animated SVG never renders on the server, so markup cannot diverge
const subscribeNever = () => () => {};
const useMounted = () =>
  useSyncExternalStore(
    subscribeNever,
    () => true,
    () => false,
  );

const COMPACT_QUERY = "(max-width: 1023px)";
const subscribeCompact = (cb: () => void) => {
  const mq = window.matchMedia(COMPACT_QUERY);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
};
const useCompact = () =>
  useSyncExternalStore(
    subscribeCompact,
    () => window.matchMedia(COMPACT_QUERY).matches,
    () => false,
  );

export default function DiscoveryGraph() {
  const reduced = useReducedMotion();
  const mounted = useMounted();
  const compact = useCompact();
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (reduced || !mounted) return;
    const interval = window.setInterval(
      () => setActive((a) => a + 1),
      (compact ? ROTATE + 1 : ROTATE) * 1000,
    );
    return () => window.clearInterval(interval);
  }, [reduced, compact, mounted]);

  if (!mounted) return <div aria-hidden className="absolute inset-0" />;

  // active cluster builds; the previous one ghosts; older ones exit
  const ids =
    compact || reduced ? [active] : [active - 1, active].filter((i) => i >= 0);

  return (
    <div aria-hidden className="pointer-events-none absolute inset-0">
      <AnimatePresence>
        {ids.map((id) => (
          <ClusterBloom
            key={id}
            cluster={CLUSTERS[id % CLUSTERS.length]}
            compact={compact}
            dimmed={id !== active}
            instant={!!reduced}
          />
        ))}
      </AnimatePresence>
    </div>
  );
}
