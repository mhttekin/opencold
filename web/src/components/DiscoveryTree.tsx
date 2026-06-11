"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";

/* ── scene specs ──
 * Each scene mirrors the real discovery pipeline:
 * seed (industry — region) → multilingual ICP expansion → companies → grounded facts.
 */

type CompanySpec = { name: string; domain: string; fact: string };
type BranchSpec = {
  icp: string;
  lang: string;
  rtl?: boolean;
  companies: CompanySpec[];
};
type SceneSpec = { industry: string; region: string; branches: BranchSpec[] };

const SCENES: SceneSpec[] = [
  {
    industry: "insurance",
    region: "MENA",
    branches: [
      {
        icp: "insurance companies in Saudi Arabia",
        lang: "EN",
        companies: [
          {
            name: "Tawuniya",
            domain: "tawuniya.com.sa",
            fact: "Riyadh HQ · +966 phone · fit 96",
          },
          {
            name: "Bupa Arabia",
            domain: "bupa.com.sa",
            fact: "“health insurance” in site copy · fit 94",
          },
        ],
      },
      {
        icp: "شركات التأمين في الإمارات",
        lang: "AR",
        rtl: true,
        companies: [
          {
            name: "Daman",
            domain: "damanhealth.ae",
            fact: "Abu Dhabi · «التأمين الصحي» · fit 93",
          },
        ],
      },
      {
        icp: "compagnies d’assurance au Maroc",
        lang: "FR",
        companies: [
          {
            name: "Wafa Assurance",
            domain: "wafaassurance.ma",
            fact: "Casablanca · « assurance vie » · fit 91",
          },
        ],
      },
    ],
  },
  {
    industry: "logistics",
    region: "Western Europe",
    branches: [
      {
        icp: "freight forwarders in the UK",
        lang: "EN",
        companies: [
          {
            name: "Davies Turner",
            domain: "daviesturner.com",
            fact: "+44 phone · “freight forwarding” · fit 93",
          },
        ],
      },
      {
        icp: "Spediteure in Deutschland",
        lang: "DE",
        companies: [
          {
            name: "Dachser",
            domain: "dachser.de",
            fact: "Kempten HQ · „Spedition“ · fit 95",
          },
          {
            name: "Rhenus Logistics",
            domain: "rhenus.group",
            fact: "Holzwickede · +49 phone · fit 94",
          },
        ],
      },
      {
        icp: "transitaires en France",
        lang: "FR",
        companies: [
          {
            name: "Bolloré Logistics",
            domain: "bollore-logistics.com",
            fact: "Puteaux · « commissionnaire » · fit 90",
          },
        ],
      },
    ],
  },
  {
    industry: "dental clinics",
    region: "LATAM",
    branches: [
      {
        icp: "clínicas dentales en México",
        lang: "ES",
        companies: [
          {
            name: "Dentalia",
            domain: "dentalia.com",
            fact: "CDMX · 70+ clinics · fit 95",
          },
        ],
      },
      {
        icp: "clínicas odontológicas no Brasil",
        lang: "PT",
        companies: [
          {
            name: "OdontoCompany",
            domain: "odontocompany.com",
            fact: "São Paulo · “rede odontológica” · fit 94",
          },
        ],
      },
      {
        icp: "dental clinics in Colombia",
        lang: "EN",
        companies: [
          {
            name: "Sonría",
            domain: "sonria.com.co",
            fact: "Bogotá · .com.co domain · fit 92",
          },
        ],
      },
    ],
  },
];

/* ── flatten a scene into timed lines ── */

type Line =
  | {
      kind: "icp";
      prefix: string;
      delay: number;
      typeDur: number;
      text: string;
      lang: string;
      rtl?: boolean;
    }
  | {
      kind: "company";
      prefix: string;
      delay: number;
      resolveAt: number;
      name: string;
      domain: string;
    }
  | { kind: "fact"; prefix: string; delay: number; text: string };

type Phase = { at: number; label: string; done?: boolean };

const SEED_START = 0.3; // caret pause before typing
const CHAR_SPEED = 0.05; // seed typing speed per character
const ICP_CHAR_SPEED = 0.034; // ICP "translation" typing speed
const SCAN_DUR = 0.6; // how long a company shimmers before resolving
const HOLD = 4.6; // seconds to rest on the finished tree

function buildScene(spec: SceneSpec): {
  lines: Line[];
  phases: Phase[];
  total: number;
} {
  const seedLen = `${spec.industry} — ${spec.region}`.length;
  const seedEnd = SEED_START + seedLen * CHAR_SPEED + 0.3;
  let t = seedEnd;
  const lines: Line[] = [];
  let firstCompany = 0;
  let firstFact = 0;

  spec.branches.forEach((branch, bi) => {
    const lastBranch = bi === spec.branches.length - 1;
    t += 0.45;
    const typeDur = branch.icp.length * ICP_CHAR_SPEED;
    lines.push({
      kind: "icp",
      prefix: lastBranch ? "└─ " : "├─ ",
      delay: t,
      typeDur,
      text: branch.icp,
      lang: branch.lang,
      rtl: branch.rtl,
    });
    t += 0.15 + typeDur;
    const cont = lastBranch ? "   " : "│  ";
    branch.companies.forEach((co, ci) => {
      const lastCo = ci === branch.companies.length - 1;
      t += 0.3;
      if (!firstCompany) firstCompany = t;
      const resolveAt = t + SCAN_DUR;
      lines.push({
        kind: "company",
        prefix: cont + (lastCo ? "└─ " : "├─ "),
        delay: t,
        resolveAt,
        name: co.name,
        domain: co.domain,
      });
      t = resolveAt + 0.3;
      if (!firstFact) firstFact = t;
      lines.push({
        kind: "fact",
        prefix: cont + (lastCo ? "   " : "│  ") + "└─ ",
        delay: t,
        text: co.fact,
      });
      t += 0.25;
    });
  });

  const nCompanies = spec.branches.reduce((n, b) => n + b.companies.length, 0);
  const phases: Phase[] = [
    { at: 0.05, label: "parsing icp seed…" },
    { at: seedEnd, label: "expanding into native languages…" },
    { at: firstCompany, label: "searching the native-language web…" },
    { at: firstFact, label: "crawling sites · verifying fit…" },
    {
      at: t + 0.5,
      label: `done — ${nCompanies} verified · ${spec.branches.length} languages`,
      done: true,
    },
  ];

  return { lines, phases, total: t + 0.5 + HOLD };
}

/* ── small pieces ── */

const lineEase = [0.22, 1, 0.36, 1] as const;
const SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

/** Counts 0 → value once `delay` seconds have passed (for the fit scores). */
function TickNumber({ value, delay }: { value: number; delay: number }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    let interval: number | undefined;
    let frame = 0;
    const total = 14;
    const timeout = window.setTimeout(() => {
      interval = window.setInterval(() => {
        frame++;
        setDisplay(Math.round((value * frame) / total));
        if (frame >= total) window.clearInterval(interval);
      }, 36);
    }, delay * 1000);
    return () => {
      window.clearTimeout(timeout);
      if (interval) window.clearInterval(interval);
    };
  }, [value, delay]);
  return <>{display}</>;
}

function SeedLine({ industry, region }: { industry: string; region: string }) {
  const seedLen = `${industry} — ${region}`.length;
  return (
    <div className="whitespace-pre leading-[2.05]">
      <span className="text-zinc-300">{"❯ "}</span>
      <span className="inline-flex items-baseline">
        <motion.span
          initial={{ width: 0 }}
          animate={{ width: `${seedLen}ch` }}
          transition={{
            delay: SEED_START,
            duration: seedLen * CHAR_SPEED,
            ease: "linear",
          }}
          className="inline-block overflow-hidden whitespace-pre align-bottom"
        >
          <span className="font-semibold text-zinc-900">{industry}</span>
          <span className="text-zinc-300"> {"—"} </span>
          <span className="font-semibold text-zinc-900">{region}</span>
        </motion.span>
        <span className="tree-caret" />
      </span>
    </div>
  );
}

function TreeLine({ line }: { line: Line }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay: line.delay, duration: 0.2 }}
      className="whitespace-pre leading-[2.05]"
    >
      <motion.span
        initial={{ opacity: 0, x: -8 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: line.delay, duration: 0.35, ease: lineEase }}
        className="inline-block text-zinc-300"
      >
        {line.prefix}
      </motion.span>

      {line.kind === "icp" && (
        <>
          {/* clip-path reveal = typing, from the correct side for RTL text */}
          <motion.span
            initial={{
              clipPath: line.rtl ? "inset(0 0 0 100%)" : "inset(0 100% 0 0)",
            }}
            animate={{ clipPath: "inset(0 0 0 0)" }}
            transition={{
              delay: line.delay + 0.15,
              duration: line.typeDur,
              ease: "linear",
            }}
            className="inline-block whitespace-pre text-zinc-700"
            dir={line.rtl ? "rtl" : undefined}
          >
            {line.text}
          </motion.span>
          <motion.span
            initial={{ opacity: 0, scale: 0.7 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{
              delay: line.delay + 0.15 + line.typeDur,
              duration: 0.25,
              ease: lineEase,
            }}
            className="tree-pill"
          >
            {line.lang}
          </motion.span>
        </>
      )}

      {line.kind === "company" && (
        <span className="relative inline-block whitespace-pre align-bottom">
          {/* shimmering scan block while "searching"… */}
          <motion.span
            initial={{ opacity: 1 }}
            animate={{ opacity: 0 }}
            transition={{ delay: line.resolveAt, duration: 0.18 }}
            className="tree-scan absolute left-0 top-0"
            aria-hidden
          >
            {"░░░░░░░░░░░░░░░░░░░░░░"}
          </motion.span>
          {/* …resolving into the company */}
          <motion.span
            initial={{ opacity: 0, filter: "blur(4px)" }}
            animate={{ opacity: 1, filter: "blur(0px)" }}
            transition={{ delay: line.resolveAt, duration: 0.3 }}
          >
            <span className="font-medium text-zinc-900">
              {line.name.padEnd(17)}
            </span>
            <span className="text-zinc-400">{line.domain}</span>
          </motion.span>
        </span>
      )}

      {line.kind === "fact" && <FactBody line={line} />}
    </motion.div>
  );
}

function FactBody({ line }: { line: Extract<Line, { kind: "fact" }> }) {
  // "… · fit 96" gets a counting score; everything else renders as-is
  const m = line.text.match(/^(.*· )fit (\d+)$/);
  return (
    <>
      <motion.span
        initial={{ opacity: 0, scale: 0 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{
          delay: line.delay + 0.05,
          type: "spring",
          stiffness: 520,
          damping: 20,
        }}
        className="inline-block text-emerald-500"
      >
        {"✓ "}
      </motion.span>
      <motion.span
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: line.delay + 0.15, duration: 0.35 }}
        className="text-zinc-400"
      >
        {m ? (
          <>
            {m[1]}
            {"fit "}
            <span className="font-medium text-emerald-600">
              <TickNumber value={Number(m[2])} delay={line.delay + 0.2} />
            </span>
          </>
        ) : (
          line.text
        )}
      </motion.span>
    </>
  );
}

/** Terminal-style narration of the pipeline phase, with a live spinner. */
function StatusLine({ phases }: { phases: Phase[] }) {
  const [phaseIdx, setPhaseIdx] = useState(0);
  const [frame, setFrame] = useState(0);
  const phase = phases[phaseIdx];

  useEffect(() => {
    const ids = phases.map((p, i) =>
      window.setTimeout(() => setPhaseIdx(i), p.at * 1000),
    );
    return () => ids.forEach((id) => window.clearTimeout(id));
  }, [phases]);

  useEffect(() => {
    if (phase.done) return;
    const id = window.setInterval(() => setFrame((f) => f + 1), 90);
    return () => window.clearInterval(id);
  }, [phase.done]);

  return (
    <div className="mt-5 flex items-center gap-2 text-[10.5px] text-zinc-400 sm:text-[11px]">
      <span
        className={`inline-block w-[1ch] ${phase.done ? "text-emerald-500" : "text-zinc-400"}`}
      >
        {phase.done ? "●" : SPINNER[frame % SPINNER.length]}
      </span>
      <AnimatePresence mode="popLayout">
        <motion.span
          key={phaseIdx}
          initial={{ opacity: 0, y: 5 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -5 }}
          transition={{ duration: 0.25, ease: lineEase }}
          className={phase.done ? "text-zinc-500" : undefined}
        >
          {phase.label}
        </motion.span>
      </AnimatePresence>
    </div>
  );
}

/* ── main component ── */

export default function DiscoveryTree() {
  const [idx, setIdx] = useState(0);
  const spec = SCENES[idx % SCENES.length];
  const { lines, phases, total } = useMemo(() => buildScene(spec), [spec]);

  useEffect(() => {
    const id = window.setTimeout(() => setIdx((i) => i + 1), total * 1000);
    return () => window.clearTimeout(id);
  }, [idx, total]);

  return (
    <div className="relative h-[380px] w-full overflow-hidden sm:h-[420px]">
      {/* ambient glow that slowly breathes behind the tree */}
      <motion.div
        aria-hidden
        className="absolute -inset-x-8 -inset-y-4 -z-10 rounded-[40px] bg-[radial-gradient(ellipse_at_center,rgb(16_185_129/0.07),rgb(244_244_245/0.5)_45%,transparent_72%)] blur-2xl"
        animate={{ scale: [1, 1.07, 1], opacity: [0.7, 1, 0.7] }}
        transition={{ duration: 8, repeat: Infinity, ease: "easeInOut" }}
      />
      <AnimatePresence mode="wait">
        <motion.div
          key={idx}
          exit={{ opacity: 0, y: -14, filter: "blur(6px)" }}
          transition={{ duration: 0.45, ease: "easeIn" }}
          className="absolute inset-x-0 top-2"
        >
          <div className="font-code mx-auto w-fit max-w-full text-[11px] sm:text-[12.5px] md:text-[13px]">
            <SeedLine industry={spec.industry} region={spec.region} />
            {lines.map((line, i) => (
              <TreeLine key={i} line={line} />
            ))}
            <StatusLine phases={phases} />
          </div>
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
