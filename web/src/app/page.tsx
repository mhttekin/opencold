"use client";

import {
  ArrowRight,
  ArrowUp,
  Check,
  ChevronDown,
  Clipboard,
  Compass,
  Download,
  ExternalLink,
  FileSpreadsheet,
  Globe,
  Mail,
  MapPin,
  Phone,
  Play,
  Send,
  ShieldCheck,
  Star,
  X,
} from "lucide-react";
import { motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";

import DiscoveryGraph from "@/components/DiscoveryGraph";
import WorldMap from "@/components/WorldMap";
import {
  parseCsv,
  pollRun,
  sendEmails,
  startRun as startRunApi,
  testSmtp,
  type Lead,
  type Progress,
  type ResultRow,
  type RunPayload,
  type SmtpConfig,
} from "@/lib/api";

/* ── types ── */

type Stage = "drop" | "configure" | "running" | "results";
type Mode = "outreach" | "discovery";

/* ── constants ── */

type ProviderType = "anthropic" | "openai" | "proxy";

const PROVIDER_MODELS: Record<Exclude<ProviderType, "proxy">, { id: string; label: string }[]> = {
  anthropic: [
    { id: "claude-opus-4-8", label: "Claude Opus 4.8" },
    { id: "claude-opus-4-6", label: "Claude Opus 4.6" },
    { id: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
    { id: "claude-haiku-4-5", label: "Claude Haiku 4.5" },
  ],
  openai: [
    { id: "gpt-5.5", label: "GPT-5.5" },
    { id: "gpt-5.5-pro", label: "GPT-5.5 Pro" },
    { id: "gpt-5.4", label: "GPT-5.4" },
    { id: "gpt-5.4-mini", label: "GPT-5.4 Mini" },
  ],
};

type CompanyConfidence = "verified" | "review" | "rejected";

const MOCK_COMPANIES: {
  company: string;
  website: string;
  email: string;
  emailType: string;
  phone: string;
  linkedin: string;
  region: string;
  sizeTier: string;
  regionFit: number;
  confidence: CompanyConfidence;
  reason: string;
}[] = [
  {
    company: "Greenfield Insurance",
    website: "greenfield.co.uk",
    email: "partnerships@greenfield.co.uk",
    emailType: "partnership",
    phone: "+44 20 7946 0813",
    linkedin: "linkedin.com/company/greenfield-insurance",
    region: "United Kingdom",
    sizeTier: "Mid-market",
    regionFit: 94,
    confidence: "verified",
    reason: "ICP terms in site copy · .co.uk · London address",
  },
  {
    company: "Harbour & Vine Underwriting",
    website: "harbourvine.co.uk",
    email: "hello@harbourvine.co.uk",
    emailType: "general",
    phone: "+44 161 496 0177",
    linkedin: "linkedin.com/company/harbour-vine",
    region: "United Kingdom",
    sizeTier: "SME",
    regionFit: 88,
    confidence: "verified",
    reason: "“commercial insurance broker” on homepage · Manchester",
  },
  {
    company: "Northgate Risk Partners",
    website: "northgaterisk.co.uk",
    email: "bd@northgaterisk.co.uk",
    emailType: "partnership",
    phone: "+44 131 555 042",
    linkedin: "linkedin.com/company/northgate-risk",
    region: "United Kingdom",
    sizeTier: "Mid-market",
    regionFit: 90,
    confidence: "verified",
    reason: "ICP match · +44 phone · Edinburgh office",
  },
  {
    company: "Meridian Cover Group",
    website: "meridiancover.com",
    email: "",
    emailType: "",
    phone: "+44 117 230 0091",
    linkedin: "linkedin.com/company/meridian-cover",
    region: "United Kingdom",
    sizeTier: "SME",
    regionFit: 76,
    confidence: "review",
    reason: "Region strong, but ICP wording ambiguous — verify line of business",
  },
  {
    company: "Atlas Insurance LLC",
    website: "atlasinsurance.com",
    email: "info@atlasinsurance.com",
    emailType: "general",
    phone: "+1 312 555 0148",
    linkedin: "linkedin.com/company/atlas-insurance-us",
    region: "United States",
    sizeTier: "Enterprise",
    regionFit: 18,
    confidence: "rejected",
    reason: "Namesake — .com + Chicago address, outside target region",
  },
];

// Verified leads first (the real Top-N), then the review/rejected pile below a
// "wall" — mirrors how the discovery CSV is laid out.
const VERIFIED_COMPANIES = MOCK_COMPANIES.filter((c) => c.confidence === "verified");
const REVIEW_COMPANIES = MOCK_COMPANIES.filter((c) => c.confidence !== "verified");
const ORDERED_COMPANIES = [...VERIFIED_COMPANIES, ...REVIEW_COMPANIES];
const WALL_INDEX = VERIFIED_COMPANIES.length;

/* ── helpers ── */

function warningBadge(w: string) {
  if (!w) return null;
  const labels: Record<string, string> = {
    short_personalization: "Low personalization",
    generic_opener: "Generic opener",
    generation_failed: "Failed",
  };
  return (
    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-700">
      {labels[w] || w}
    </span>
  );
}

function confidenceBadge(c: CompanyConfidence) {
  const map: Record<CompanyConfidence, { label: string; cls: string }> = {
    verified: { label: "Verified", cls: "bg-emerald-100 text-emerald-700" },
    review: { label: "Review", cls: "bg-amber-100 text-amber-700" },
    rejected: { label: "Rejected", cls: "bg-zinc-200 text-zinc-500" },
  };
  const { label, cls } = map[c];
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${cls}`}>
      {label}
    </span>
  );
}

function Counter({ value }: { value: number }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    let frame = 0;
    const total = 22;
    const id = window.setInterval(() => {
      frame++;
      setDisplay(Math.round((value * frame) / total));
      if (frame >= total) window.clearInterval(id);
    }, 18);
    return () => window.clearInterval(id);
  }, [value]);
  return <span className="font-semibold text-zinc-900">{display}</span>;
}

/* ── main page ── */

export default function Home() {
  const [stage, setStage] = useState<Stage>("drop");
  const [mode, setMode] = useState<Mode>("discovery");
  const [fileName, setFileName] = useState("");
  const [dropHint, setDropHint] = useState<string | null>(null);

  // discovery — left pipeline
  const [icp, setIcp] = useState("");
  const [countries, setCountries] = useState<string[]>([]);

  // discovery — right sidebar accordions
  const [dProviderOpen, setDProviderOpen] = useState(false);
  const [dOptionsOpen, setDOptionsOpen] = useState(false);

  // discovery options
  const [targetCount, setTargetCount] = useState(25);
  const [findPeople, setFindPeople] = useState(false);
  const [requireContact, setRequireContact] = useState(false);

  // discovery results
  const [openCompany, setOpenCompany] = useState<number | null>(0);

  // configure — left: campaign (progressive expand)
  const [campaignTitle, setCampaignTitle] = useState("");
  const [campaignPitch, setCampaignPitch] = useState("");

  // configure — right sidebar accordions
  const [profileOpen, setProfileOpen] = useState(true);
  const [providerOpen, setProviderOpen] = useState(false);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);

  // provider
  const [provider, setProvider] = useState<ProviderType>("anthropic");
  const [selectedModel, setSelectedModel] = useState("claude-opus-4-6");
  const [customModel, setCustomModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [modelDropOpen, setModelDropOpen] = useState(false);
  // proxy-specific
  const [proxyUrl, setProxyUrl] = useState("");
  const [proxyToken, setProxyToken] = useState("");
  const [proxyModel, setProxyModel] = useState("");

  // profile fields
  const [profileName, setProfileName] = useState("");
  const [profileCompany, setProfileCompany] = useState("");
  const [profileRole, setProfileRole] = useState("");
  const [profileBio, setProfileBio] = useState("");

  // template
  const [template, setTemplate] = useState("");

  // options
  const [findContacts, setFindContacts] = useState(true);
  const [requireVerified, setRequireVerified] = useState(false);

  // results
  const [openRow, setOpenRow] = useState<number | null>(0);
  const [smtpOpen, setSmtpOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  // run + results data (from the API)
  const [leads, setLeads] = useState<Lead[]>([]);
  const [results, setResults] = useState<ResultRow[]>([]);
  const [runProgress, setRunProgress] = useState<Progress | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const pollAbort = useRef<AbortController | null>(null);

  // smtp drawer
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState("587");
  const [smtpUser, setSmtpUser] = useState("");
  const [smtpPass, setSmtpPass] = useState("");
  const [smtpFrom, setSmtpFrom] = useState("");
  const [smtpTesting, setSmtpTesting] = useState(false);
  const [smtpTestMsg, setSmtpTestMsg] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<string | null>(null);

  // stop polling if the component unmounts mid-run
  useEffect(() => () => pollAbort.current?.abort(), []);

  const hasCampaign = campaignTitle.trim().length > 0;
  const hasProfile = profileName.trim().length > 0;
  const canRun = hasCampaign && hasProfile;

  // discovery derived
  const hasIcp = icp.trim().length > 0;
  const canRunDiscovery = hasIcp && countries.length > 0;
  const toggleCountry = (name: string) =>
    setCountries((prev) =>
      prev.includes(name) ? prev.filter((c) => c !== name) : [...prev, name],
    );

  const effectiveModel =
    provider === "proxy"
      ? proxyModel || "\u2014"
      : selectedModel === "custom"
        ? customModel || "\u2014"
        : selectedModel;

  const switchProvider = (p: ProviderType) => {
    setProvider(p);
    setModelDropOpen(false);
    if (p === "anthropic") setSelectedModel("claude-opus-4-6");
    else if (p === "openai") setSelectedModel("gpt-5.5");
    else setSelectedModel("");
  };

  const startConfigure = (name = "companies.csv") => {
    setFileName(name);
    setStage("configure");
  };

  const buildRunPayload = (): RunPayload => {
    const runModel =
      provider === "proxy"
        ? proxyModel
        : selectedModel === "custom"
          ? customModel
          : selectedModel;
    return {
      leads,
      campaign: {
        title: campaignTitle,
        description: profileBio || campaignTitle,
        pitch: campaignPitch,
      },
      identity: { name: profileName, email: smtpFrom },
      profile: {
        company: profileCompany,
        role: profileRole,
        bio: profileBio,
        pitch: campaignPitch,
      },
      provider: {
        type: provider,
        api_key: provider === "proxy" ? proxyToken : apiKey,
        model: runModel,
        ...(provider === "proxy" && proxyUrl ? { base_url: proxyUrl } : {}),
      },
      options: {
        do_resolve_websites: true,
        do_enrich: true,
        do_verify: findContacts,
        drop_invalid: requireVerified,
        ...(template.trim() ? { template } : {}),
      },
    };
  };

  const startRun = async () => {
    // Discovery is still a mocked preview — not wired to the API yet.
    if (mode === "discovery") {
      setStage("running");
      window.setTimeout(() => setStage("results"), 1400);
      return;
    }
    if (!canRun) return;
    setRunError(null);
    setRunProgress(null);
    setResults([]);
    setSendResult(null);
    setStage("running");

    pollAbort.current?.abort();
    const controller = new AbortController();
    pollAbort.current = controller;

    try {
      const { job_id } = await startRunApi(buildRunPayload());
      const final = await pollRun(
        job_id,
        (job) => setRunProgress(job.progress ?? null),
        { intervalMs: 2000, signal: controller.signal },
      );
      if (final.status === "succeeded") {
        setResults(final.results ?? []);
        setOpenRow(0);
        setStage("results");
      } else {
        setRunError(final.error ?? "Generation failed.");
        setStage("configure");
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setRunError(e instanceof Error ? e.message : String(e));
      setStage("configure");
    }
  };

  // ── results helpers ──
  const recipientName = (row: ResultRow) =>
    row.name ||
    [row.first_name, row.last_name].filter(Boolean).join(" ") ||
    row.email ||
    "—";
  const firstWarning = (w?: string) => (w ? w.split(" | ")[0] : "");
  const sendableResults = results.filter(
    (r) => r.email && r.generated_email && !r.generated_email.startsWith("ERROR:"),
  );
  const skippedCount = results.length - sendableResults.length;

  const copyText = (text: string) => navigator.clipboard?.writeText(text);
  const copyAll = () =>
    copyText(
      results
        .map((r) => `Subject: ${r.generated_subject ?? ""}\n\n${r.generated_email ?? ""}`)
        .join("\n\n———\n\n"),
    );

  const downloadCsv = () => {
    if (results.length === 0) return;
    const cols = Array.from(
      results.reduce((set, r) => {
        Object.keys(r).forEach((k) => set.add(k));
        return set;
      }, new Set<string>()),
    );
    const esc = (v: string) =>
      /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
    const lines = [
      cols.join(","),
      ...results.map((r) => cols.map((c) => esc((r[c] ?? "") as string)).join(",")),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "opencold-drafts.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  // ── smtp helpers ──
  const buildSmtp = (): SmtpConfig => ({
    host: smtpHost,
    port: Number(smtpPort) || 587,
    username: smtpUser,
    password: smtpPass,
    sender_email: smtpFrom || smtpUser,
    sender_name: profileName,
    use_tls: true,
  });

  const doTestSmtp = async () => {
    setSmtpTesting(true);
    setSmtpTestMsg(null);
    try {
      const res = await testSmtp(buildSmtp());
      setSmtpTestMsg(res.ok ? "Connection OK" : `Failed: ${res.error}`);
    } catch (e) {
      setSmtpTestMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setSmtpTesting(false);
    }
  };

  const doSend = async () => {
    setSending(true);
    setSendResult(null);
    try {
      const items = sendableResults.map((r) => ({
        email: r.email as string,
        name: recipientName(r),
        subject: r.generated_subject ?? "",
        body: r.generated_email ?? "",
      }));
      const res = await sendEmails(buildSmtp(), items);
      setSendResult(
        `Sent ${res.sent}/${res.results.length}` +
          (res.failed ? `, ${res.failed} failed` : ""),
      );
      setConfirmOpen(false);
    } catch (e) {
      setSendResult(e instanceof Error ? e.message : String(e));
      setConfirmOpen(false);
    } finally {
      setSending(false);
    }
  };

  // mode navigation — both modes land on their hero; discovery is the
  // default front door, its CTA moves on to the configure panel.
  const goOutreach = () => {
    setMode("outreach");
    setStage("drop");
  };
  const goDiscovery = () => {
    setMode("discovery");
    setStage("drop");
  };
  const resetHome = () => {
    pollAbort.current?.abort();
    setStage("drop");
    setMode("discovery");
  };

  return (
    <main className="relative flex min-h-screen flex-col bg-[#FAFAF7] text-zinc-900">
      {/* notebook grid background */}
      <div
        className={`grid-field ${stage !== "drop" ? "grid-field--fade" : ""}`}
      />

      {/* header */}
      <header className="relative z-10 mx-auto flex w-full max-w-6xl items-center justify-between px-6 pb-5 pt-8 sm:px-10 sm:pt-10">
        <button
          className="text-[15px] font-semibold tracking-tight"
          onClick={resetHome}
        >
          OpenCold
        </button>
        <a
          href="https://github.com/mhttekin/opencold"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-zinc-200 px-3 text-xs font-medium text-zinc-600 transition hover:border-zinc-400 hover:text-zinc-900 active:scale-[0.97]"
        >
          <svg
            viewBox="0 0 16 16"
            width={14}
            height={14}
            fill="currentColor"
            aria-hidden="true"
          >
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
          </svg>
          Star
          <Star size={11} className="fill-amber-400 text-amber-400" />
        </a>
      </header>

      {/* ── STAGE: DROP ── */}
      {stage === "drop" && (
        <div className="relative z-10 flex flex-1 flex-col">
          <div className="flex justify-center px-6 pt-2 sm:pt-4">
            <ModeSelector
              mode={mode}
              onOutreach={goOutreach}
              onDiscovery={goDiscovery}
            />
          </div>
          {mode === "discovery" ? (
            <DiscoveryHero
              onStart={(icpText) => {
                if (icpText) setIcp(icpText);
                setStage("configure");
              }}
            />
          ) : (
            <DropHero
              onFile={(file) => {
                console.log("Parsed file:", file);
                setDropHint(`Reading ${file.name}…`);
                // TODO: hand off file to processing pipeline
                window.setTimeout(() => {
                  setDropHint(null);
                  startConfigure(file.name);
                }, 1200);
              }}
              hint={dropHint}
              onHintClear={() => setDropHint(null)}
            />
          )}
        </div>
      )}

      {/* ── STAGE: CONFIGURE (outreach) ── */}
      {stage === "configure" && mode === "outreach" && (
        <section className="configure-enter relative z-10 mx-auto max-w-5xl px-6 pb-20 pt-6 sm:pt-10">
          {/* top bar — file indicator + run button */}
          <div className="mb-8 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="grid size-7 place-items-center rounded-lg bg-zinc-100">
                <Check size={14} className="text-zinc-500" />
              </div>
              <div>
                <p className="text-sm font-medium">{fileName}</p>
                <p className="text-xs text-zinc-400">Ready to configure</p>
              </div>
            </div>
            <button
              disabled={!canRun}
              className="inline-flex h-10 items-center gap-2 rounded-lg bg-zinc-900 px-5 text-sm font-medium text-white transition disabled:opacity-30 active:scale-[0.97]"
              onClick={startRun}
            >
              <Play size={14} />
              Run
            </button>
          </div>

          {runError && (
            <div className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {runError}
            </div>
          )}

          {/* two-column layout */}
          <div className="grid items-start gap-8 lg:grid-cols-[1fr_340px]">
            {/* ── LEFT: sections ── */}
            <div className="space-y-10">
              {/* Section 1: Campaign */}
              <div className="config-section">
                <div className="config-section-header">
                  <span className="config-step-number">1</span>
                  <div>
                    <h2 className="text-[15px] font-semibold tracking-tight">
                      Campaign
                    </h2>
                    <p className="mt-0.5 text-sm text-zinc-400">
                      Give this run a name and describe your outreach goal.
                    </p>
                  </div>
                </div>
                <div className="mt-5 space-y-3">
                  <label className="block text-xs font-medium text-zinc-500">
                    Campaign title
                    <input
                      className="mt-1.5 h-10 w-full rounded-lg border border-zinc-200 bg-white px-4 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                      value={campaignTitle}
                      onChange={(e) => setCampaignTitle(e.target.value)}
                      placeholder="e.g. Q3 DevTool partnerships"
                    />
                  </label>
                  <label className="block text-xs font-medium text-zinc-500">
                    What&apos;s the pitch or purpose of this outreach?
                    <textarea
                      className="mt-1.5 min-h-[72px] w-full resize-y rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                      value={campaignPitch}
                      onChange={(e) => setCampaignPitch(e.target.value)}
                      placeholder="e.g. We help B2B teams automate outreach — looking to partner with dev tool companies..."
                    />
                  </label>
                </div>
              </div>

              {/* Section 2: Ready to run — expands when Campaign is filled */}
              <div
                className="accordion-body"
                style={{ gridTemplateRows: hasCampaign ? "1fr" : "0fr" }}
              >
                <div className="min-h-0 overflow-hidden">
                  <div className="config-section" style={{ borderBottom: "none" }}>
                    <div className="config-section-header">
                      <span className="config-step-number">2</span>
                      <div>
                        <h2 className="text-[15px] font-semibold tracking-tight">
                          Ready to run
                        </h2>
                        <p className="mt-0.5 text-sm text-zinc-400">
                          We&apos;ll scan each company&apos;s website, find the
                          right contact, and generate personalized emails.
                        </p>
                      </div>
                    </div>
                    <div className="mt-5">
                      <button
                        disabled={!canRun}
                        className="inline-flex h-10 items-center gap-2 rounded-lg bg-zinc-900 px-6 text-sm font-medium text-white transition disabled:opacity-30 active:scale-[0.97]"
                        onClick={startRun}
                      >
                        <Play size={14} />
                        Run opencold
                        <ArrowRight size={14} />
                      </button>
                      {!hasProfile && hasCampaign && (
                        <p className="mt-3 text-xs text-zinc-400">
                          Fill in your{" "}
                          <button
                            className="underline hover:text-zinc-900"
                            onClick={() => setProfileOpen(true)}
                          >
                            Profile
                          </button>{" "}
                          to continue.
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* ── RIGHT: sidebar accordions ── */}
            <aside className="space-y-3 lg:sticky lg:top-6 lg:self-start">
              {/* Profile accordion */}
              <Accordion
                title="Profile"
                badge="required"
                open={profileOpen}
                onToggle={() => setProfileOpen(!profileOpen)}
                filled={hasProfile}
              >
                <div className="space-y-3">
                  <label className="block text-xs font-medium text-zinc-500">
                    Your name
                    <input
                      className="mt-1.5 h-10 w-full rounded-lg border border-zinc-200 px-3 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                      value={profileName}
                      onChange={(e) => setProfileName(e.target.value)}
                      placeholder="Jane Smith"
                    />
                  </label>
                  <label className="block text-xs font-medium text-zinc-500">
                    Company
                    <input
                      className="mt-1.5 h-10 w-full rounded-lg border border-zinc-200 px-3 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                      value={profileCompany}
                      onChange={(e) => setProfileCompany(e.target.value)}
                      placeholder="Acme Inc"
                    />
                  </label>
                  <label className="block text-xs font-medium text-zinc-500">
                    Role
                    <input
                      className="mt-1.5 h-10 w-full rounded-lg border border-zinc-200 px-3 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                      value={profileRole}
                      onChange={(e) => setProfileRole(e.target.value)}
                      placeholder="Growth Lead"
                    />
                  </label>
                  <label className="block text-xs font-medium text-zinc-500">
                    What you do / offer
                    <textarea
                      className="mt-1.5 min-h-[72px] w-full resize-y rounded-lg border border-zinc-200 px-3 py-2 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                      value={profileBio}
                      onChange={(e) => setProfileBio(e.target.value)}
                      placeholder="We help B2B teams automate outreach..."
                    />
                  </label>
                </div>
              </Accordion>

              {/* Template accordion */}
              <Accordion
                title="Template"
                open={templateOpen}
                onToggle={() => setTemplateOpen(!templateOpen)}
                filled={template.trim().length > 0}
              >
                <label className="block text-xs font-medium text-zinc-500">
                  Custom email template
                  <textarea
                    className="mt-1.5 min-h-[120px] w-full resize-y rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                    value={template}
                    onChange={(e) => setTemplate(e.target.value)}
                    placeholder={"Hi {first_name},\n\nI noticed {fact}...\n\nBest,\n{sender_name}"}
                  />
                </label>
                <p className="mt-2 text-[11px] text-zinc-400">
                  Variables: {"{first_name}"}, {"{company}"}, {"{fact}"},{" "}
                  {"{sender_name}"}
                </p>
              </Accordion>

              {/* Provider accordion */}
              <Accordion
                title="Provider"
                badge="required"
                open={providerOpen}
                onToggle={() => setProviderOpen(!providerOpen)}
                filled={provider === "proxy" ? proxyUrl.length > 0 : apiKey.length > 0}
              >
                <ProviderFields
                  provider={provider}
                  switchProvider={switchProvider}
                  apiKey={apiKey}
                  setApiKey={setApiKey}
                  selectedModel={selectedModel}
                  setSelectedModel={setSelectedModel}
                  customModel={customModel}
                  setCustomModel={setCustomModel}
                  modelDropOpen={modelDropOpen}
                  setModelDropOpen={setModelDropOpen}
                  proxyUrl={proxyUrl}
                  setProxyUrl={setProxyUrl}
                  proxyToken={proxyToken}
                  setProxyToken={setProxyToken}
                  proxyModel={proxyModel}
                  setProxyModel={setProxyModel}
                />
              </Accordion>

              {/* Options accordion */}
              <Accordion
                title="Options"
                open={optionsOpen}
                onToggle={() => setOptionsOpen(!optionsOpen)}
              >
                <div className="space-y-4">
                  <SidebarToggle
                    label="Find contact emails"
                    description="MX + SMTP verification"
                    checked={findContacts}
                    onChange={setFindContacts}
                  />
                  <SidebarToggle
                    label="Verified emails only"
                    description="Filter out unverified rows"
                    checked={requireVerified}
                    onChange={setRequireVerified}
                  />
                </div>
              </Accordion>

              {/* run summary */}
              <div className="rounded-xl border border-zinc-100 bg-zinc-50/50 p-5">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                  Run summary
                </h3>
                <dl className="mt-4 space-y-3 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-zinc-400">File</dt>
                    <dd className="font-medium">{fileName}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-zinc-400">Campaign</dt>
                    <dd className="max-w-[160px] truncate text-right font-medium">
                      {campaignTitle || "\u2014"}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-zinc-400">Profile</dt>
                    <dd className="font-medium">
                      {profileName || "\u2014"}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-zinc-400">Model</dt>
                    <dd className="max-w-[160px] truncate text-right font-mono text-xs font-medium">
                      {effectiveModel}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-zinc-400">Email lookup</dt>
                    <dd className="font-medium">
                      {findContacts ? "On" : "Off"}
                    </dd>
                  </div>
                </dl>
              </div>
            </aside>
          </div>
        </section>
      )}

      {/* ── STAGE: CONFIGURE (discovery) ── */}
      {stage === "configure" && mode === "discovery" && (
        <section className="configure-enter relative z-10 mx-auto max-w-5xl px-6 pb-20 pt-6 sm:pt-10">
          {/* top bar — discovery indicator + run button */}
          <div className="mb-8 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="grid size-7 place-items-center rounded-lg bg-zinc-100">
                <Compass size={14} className="text-zinc-500" />
              </div>
              <div>
                <p className="text-sm font-medium">Company discovery</p>
                <p className="text-xs text-zinc-400">
                  No file needed — describe and target
                </p>
              </div>
            </div>
            <button
              disabled={!canRunDiscovery}
              className="inline-flex h-10 items-center gap-2 rounded-lg bg-zinc-900 px-5 text-sm font-medium text-white transition disabled:opacity-30 active:scale-[0.97]"
              onClick={startRun}
            >
              <Play size={14} />
              Run
            </button>
          </div>

          {/* two-column layout */}
          <div className="grid items-start gap-8 lg:grid-cols-[1fr_340px]">
            {/* ── LEFT: sections ── */}
            <div className="space-y-10">
              {/* Section 1: ICP */}
              <div className="config-section">
                <div className="config-section-header">
                  <span className="config-step-number">1</span>
                  <div>
                    <h2 className="text-[15px] font-semibold tracking-tight">
                      What do the target companies do?
                    </h2>
                    <p className="mt-0.5 text-sm text-zinc-400">
                      Describe your ideal customer — their industry, product, or
                      niche.
                    </p>
                  </div>
                </div>
                <div className="mt-5">
                  <label className="block text-xs font-medium text-zinc-500">
                    Target profile (ICP)
                    <textarea
                      className="mt-1.5 min-h-[84px] w-full resize-y rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                      value={icp}
                      onChange={(e) => setIcp(e.target.value)}
                      placeholder="e.g. commercial insurance brokers, B2B logistics startups, independent dental clinics..."
                    />
                  </label>
                </div>
              </div>

              {/* Section 2: Countries — expands once ICP is filled */}
              <div
                className="accordion-body"
                style={{ gridTemplateRows: hasIcp ? "1fr" : "0fr" }}
              >
                <div className="min-h-0 overflow-hidden">
                  <div className="config-section">
                    <div className="config-section-header">
                      <span className="config-step-number">2</span>
                      <div>
                        <h2 className="text-[15px] font-semibold tracking-tight">
                          Which countries should we target?
                        </h2>
                        <p className="mt-0.5 text-sm text-zinc-400">
                          Click the map or use the suggestions — pick one or more.
                        </p>
                      </div>
                    </div>
                    <div className="mt-5">
                      <WorldMap
                        selected={countries}
                        onToggle={toggleCountry}
                        onClear={() => setCountries([])}
                      />
                    </div>
                  </div>
                </div>
              </div>

              {/* Section 3: Ready to run — expands once ICP + countries set */}
              <div
                className="accordion-body"
                style={{ gridTemplateRows: canRunDiscovery ? "1fr" : "0fr" }}
              >
                <div className="min-h-0 overflow-hidden">
                  <div className="config-section" style={{ borderBottom: "none" }}>
                    <div className="config-section-header">
                      <span className="config-step-number">3</span>
                      <div>
                        <h2 className="text-[15px] font-semibold tracking-tight">
                          Ready to discover
                        </h2>
                        <p className="mt-0.5 text-sm text-zinc-400">
                          We&apos;ll seed candidates, crawl their sites, and verify
                          each match against your profile and region.
                        </p>
                      </div>
                    </div>
                    <div className="mt-5">
                      <button
                        disabled={!canRunDiscovery}
                        className="inline-flex h-10 items-center gap-2 rounded-lg bg-zinc-900 px-6 text-sm font-medium text-white transition disabled:opacity-30 active:scale-[0.97]"
                        onClick={startRun}
                      >
                        <Play size={14} />
                        Run discovery
                        <ArrowRight size={14} />
                      </button>
                      <p className="mt-3 text-xs text-zinc-400">
                        Provider is optional — without one, discovery runs
                        deterministic-only.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* ── RIGHT: sidebar accordions ── */}
            <aside className="space-y-3 lg:sticky lg:top-6 lg:self-start">
              {/* Provider — optional for discovery */}
              <Accordion
                title="Provider"
                badge="optional"
                open={dProviderOpen}
                onToggle={() => setDProviderOpen(!dProviderOpen)}
                filled={provider === "proxy" ? proxyUrl.length > 0 : apiKey.length > 0}
              >
                <p className="mb-3 text-[11px] leading-relaxed text-zinc-400">
                  Optional. With a provider, an LLM seeds known companies and judges
                  each match. Without one, discovery uses search + deterministic
                  checks.
                </p>
                <ProviderFields
                  provider={provider}
                  switchProvider={switchProvider}
                  apiKey={apiKey}
                  setApiKey={setApiKey}
                  selectedModel={selectedModel}
                  setSelectedModel={setSelectedModel}
                  customModel={customModel}
                  setCustomModel={setCustomModel}
                  modelDropOpen={modelDropOpen}
                  setModelDropOpen={setModelDropOpen}
                  proxyUrl={proxyUrl}
                  setProxyUrl={setProxyUrl}
                  proxyToken={proxyToken}
                  setProxyToken={setProxyToken}
                  proxyModel={proxyModel}
                  setProxyModel={setProxyModel}
                />
              </Accordion>

              {/* Options */}
              <Accordion
                title="Options"
                open={dOptionsOpen}
                onToggle={() => setDOptionsOpen(!dOptionsOpen)}
              >
                <div className="space-y-4">
                  <SidebarToggle
                    label="Find people"
                    description="Also search a named contact per company"
                    checked={findPeople}
                    onChange={setFindPeople}
                  />
                  <SidebarToggle
                    label="Require contact"
                    description="Drop companies with no email"
                    checked={requireContact}
                    onChange={setRequireContact}
                  />
                </div>
              </Accordion>

              {/* companies-to-discover slider */}
              <div className="rounded-xl border border-zinc-100 bg-zinc-50/50 p-5">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                    Companies to discover
                  </h3>
                  <span className="text-sm font-semibold text-zinc-900">
                    {targetCount}
                  </span>
                </div>
                <input
                  type="range"
                  min={5}
                  max={100}
                  step={5}
                  value={targetCount}
                  onChange={(e) => setTargetCount(Number(e.target.value))}
                  aria-label="Companies to discover"
                  className="range-slider mt-4 w-full accent-zinc-900"
                />
                <div className="mt-1 flex justify-between text-[10px] text-zinc-400">
                  <span>5</span>
                  <span>100</span>
                </div>
              </div>

              {/* run summary */}
              <div className="rounded-xl border border-zinc-100 bg-zinc-50/50 p-5">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                  Run summary
                </h3>
                <dl className="mt-4 space-y-3 text-sm">
                  <div className="flex justify-between gap-4">
                    <dt className="text-zinc-400">Profile</dt>
                    <dd className="max-w-[180px] truncate text-right font-medium">
                      {icp || "—"}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-zinc-400">Countries</dt>
                    <dd className="font-medium">{countries.length || "—"}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-zinc-400">Target</dt>
                    <dd className="font-medium">{targetCount} companies</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-zinc-400">Provider</dt>
                    <dd className="max-w-[180px] truncate text-right font-mono text-xs font-medium">
                      {(provider === "proxy" ? proxyUrl : apiKey)
                        ? effectiveModel
                        : "None"}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-zinc-400">Find people</dt>
                    <dd className="font-medium">{findPeople ? "On" : "Off"}</dd>
                  </div>
                </dl>
              </div>
            </aside>
          </div>
        </section>
      )}

      {/* ── STAGE: RUNNING ── */}
      {stage === "running" && (
        <section className="configure-enter relative z-10 mx-auto max-w-3xl px-6 pb-20 pt-8 sm:pt-16">
          <h2 className="text-2xl font-semibold tracking-tight">
            {mode === "discovery" ? "Discovering companies…" : "Running…"}
          </h2>
          <p className="mt-2 text-sm text-zinc-400">
            {mode === "discovery"
              ? "Seeding candidates, crawling sites, and verifying matches."
              : runProgress?.message ||
                "Researching websites and generating personalized emails."}
          </p>
          {mode === "outreach" && runProgress?.total ? (
            <p className="mt-3 text-xs font-medium text-zinc-500">
              {runProgress.current ?? 0} / {runProgress.total}
            </p>
          ) : null}
          <SkeletonTable />
        </section>
      )}

      {/* ── STAGE: RESULTS (outreach) ── */}
      {stage === "results" && mode === "outreach" && (
        <section className="configure-enter relative z-10 mx-auto max-w-4xl px-6 pb-20 pt-8 sm:pt-16">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight">
                Generated emails
              </h2>
              <p className="mt-1 text-sm text-zinc-400">
                {fileName} &middot; {results.length} emails generated
              </p>
            </div>
            <div className="flex gap-2">
              <button
                className="inline-flex h-9 items-center gap-2 rounded-lg bg-zinc-900 px-4 text-sm font-medium text-white transition active:scale-[0.97]"
                onClick={downloadCsv}
              >
                <Download size={15} />
                Download CSV
              </button>
              <button
                className="inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-200 px-4 text-sm font-medium text-zinc-700 transition hover:border-zinc-400 active:scale-[0.97]"
                onClick={() => setSmtpOpen(true)}
              >
                <Mail size={15} />
                Send via SMTP
              </button>
              <button
                className="grid size-9 place-items-center rounded-lg border border-zinc-200 text-zinc-400 transition hover:border-zinc-400 hover:text-zinc-900 active:scale-[0.97]"
                aria-label="Copy to clipboard"
                onClick={copyAll}
              >
                <Clipboard size={15} />
              </button>
            </div>
          </div>

          <div className="stats-row mt-4 border-b border-zinc-100 pb-4">
            <span>
              <Counter value={results.length} /> emails
            </span>
            <span>
              <Counter
                value={results.filter((r) => !r.quality_warnings).length}
              />{" "}
              clean
            </span>
            <span>
              <Counter
                value={results.filter((r) => r.quality_warnings).length}
              />{" "}
              warnings
            </span>
          </div>

          {results.length === 0 && (
            <p className="mt-10 text-center text-sm text-zinc-400">
              No drafts were produced. Check your leads and provider settings, then run again.
            </p>
          )}

          <div className="mt-6 space-y-3">
            {results.map((row, i) => {
              const warned = !!row.quality_warnings;
              return (
              <div
                key={`${row.email ?? "row"}-${i}`}
                className={`result-row rounded-xl border border-zinc-100 overflow-hidden ${openRow === i ? "result-row--open" : ""}`}
                style={{ animationDelay: `${i * 60}ms` }}
              >
                <button
                  className="flex w-full items-center gap-4 px-5 py-4 text-left transition hover:bg-zinc-50"
                  onClick={() => setOpenRow(openRow === i ? null : i)}
                >
                  <span className={`size-2 flex-shrink-0 rounded-full ${warned ? "bg-amber-400" : "bg-emerald-500"}`} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold truncate">
                      {row.generated_subject || "(no subject)"}
                    </p>
                    <p className="mt-0.5 text-xs text-zinc-400">
                      To: {recipientName(row)} &lt;{row.email}&gt;
                      {" "}&middot;{" "}{row.company}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {warned && warningBadge(firstWarning(row.quality_warnings))}
                    <ChevronDown
                      size={14}
                      className={`text-zinc-400 transition-transform ${openRow === i ? "rotate-180" : ""}`}
                    />
                  </div>
                </button>
                <div className="result-detail">
                  <div className="min-h-0">
                    <div className="border-t border-zinc-100 px-5 py-5">
                      <div className="flex items-center gap-2 text-xs text-zinc-400">
                        <Mail size={12} />
                        <span>Subject: <span className="font-medium text-zinc-600">{row.generated_subject}</span></span>
                      </div>
                      <pre className="mt-4 whitespace-pre-wrap font-sans text-sm leading-relaxed text-zinc-700">
                        {row.generated_email}
                      </pre>
                      <div className="mt-4 flex gap-2">
                        <button
                          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-zinc-200 px-3 text-xs font-medium text-zinc-500 transition hover:border-zinc-400 hover:text-zinc-900 active:scale-[0.97]"
                          onClick={() => copyText(row.generated_email ?? "")}
                        >
                          <Clipboard size={12} />
                          Copy
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              );
            })}
          </div>
        </section>
      )}

      {/* ── STAGE: RESULTS (discovery) ── */}
      {stage === "results" && mode === "discovery" && (
        <section className="configure-enter relative z-10 mx-auto max-w-4xl px-6 pb-20 pt-8 sm:pt-16">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight">
                Discovered companies
              </h2>
              <p className="mt-1 text-sm text-zinc-400">
                {icp || "Target profile"} &middot;{" "}
                {countries.length} {countries.length === 1 ? "country" : "countries"}{" "}
                &middot; {MOCK_COMPANIES.length} found
              </p>
            </div>
            <div className="flex gap-2">
              <button className="inline-flex h-9 items-center gap-2 rounded-lg bg-zinc-900 px-4 text-sm font-medium text-white transition active:scale-[0.97]">
                <Download size={15} />
                Download CSV
              </button>
              <button
                className="grid size-9 place-items-center rounded-lg border border-zinc-200 text-zinc-400 transition hover:border-zinc-400 hover:text-zinc-900 active:scale-[0.97]"
                aria-label="Copy to clipboard"
              >
                <Clipboard size={15} />
              </button>
            </div>
          </div>

          <div className="stats-row mt-4 border-b border-zinc-100 pb-4">
            <span>
              <Counter value={MOCK_COMPANIES.length} /> companies
            </span>
            <span>
              <Counter value={VERIFIED_COMPANIES.length} /> verified
            </span>
            <span>
              <Counter value={REVIEW_COMPANIES.length} /> to review
            </span>
          </div>

          <div className="mt-6 space-y-3">
            {ORDERED_COMPANIES.map((row, i) => (
              <div key={row.company}>
                {i === WALL_INDEX && (
                  <div className="my-5 flex items-center gap-3">
                    <span className="h-px flex-1 bg-zinc-100" />
                    <span className="rounded-full bg-zinc-100 px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
                      Review below
                    </span>
                    <span className="h-px flex-1 bg-zinc-100" />
                  </div>
                )}
                <div
                  className={`result-row rounded-xl border border-zinc-100 overflow-hidden ${openCompany === i ? "result-row--open" : ""}`}
                  style={{ animationDelay: `${i * 60}ms` }}
                >
                  <button
                    className="flex w-full items-center gap-4 px-5 py-4 text-left transition hover:bg-zinc-50"
                    onClick={() => setOpenCompany(openCompany === i ? null : i)}
                  >
                    <span
                      className={`size-2 flex-shrink-0 rounded-full ${
                        row.confidence === "verified"
                          ? "bg-emerald-500"
                          : row.confidence === "review"
                            ? "bg-amber-400"
                            : "bg-zinc-300"
                      }`}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold">
                        {row.company}
                      </p>
                      <p className="mt-0.5 flex items-center gap-1.5 text-xs text-zinc-400">
                        <Globe size={11} />
                        {row.website}
                        <span>&middot;</span>
                        <MapPin size={11} />
                        {row.region}
                        <span>&middot;</span>
                        {row.sizeTier}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="hidden text-[11px] font-medium text-zinc-400 sm:inline">
                        fit {row.regionFit}
                      </span>
                      {confidenceBadge(row.confidence)}
                      <ChevronDown
                        size={14}
                        className={`text-zinc-400 transition-transform ${openCompany === i ? "rotate-180" : ""}`}
                      />
                    </div>
                  </button>
                  <div className="result-detail">
                    <div className="min-h-0">
                      <div className="border-t border-zinc-100 px-5 py-5">
                        <dl className="grid gap-3 sm:grid-cols-2">
                          <ContactRow
                            icon={<Mail size={12} />}
                            label="Email"
                            value={
                              row.email
                                ? `${row.email}${row.emailType ? ` · ${row.emailType}` : ""}`
                                : "—"
                            }
                          />
                          <ContactRow
                            icon={<Phone size={12} />}
                            label="Phone"
                            value={row.phone || "—"}
                          />
                          <ContactRow
                            icon={<ExternalLink size={12} />}
                            label="LinkedIn"
                            value={row.linkedin}
                          />
                          <ContactRow
                            icon={<MapPin size={12} />}
                            label="Region fit"
                            value={`${row.regionFit} / 100`}
                          />
                        </dl>
                        <div className="mt-4 flex items-start gap-2 rounded-lg bg-zinc-50 px-3 py-2.5 text-xs text-zinc-500">
                          <ShieldCheck
                            size={13}
                            className="mt-0.5 flex-shrink-0 text-zinc-400"
                          />
                          <span>
                            <span className="font-medium text-zinc-600">
                              Verification:{" "}
                            </span>
                            {row.reason}
                          </span>
                        </div>
                        <div className="mt-4 flex gap-2">
                          <button className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-zinc-200 px-3 text-xs font-medium text-zinc-500 transition hover:border-zinc-400 hover:text-zinc-900 active:scale-[0.97]">
                            <Clipboard size={12} />
                            Copy row
                          </button>
                          {row.website && (
                            <a
                              href={`https://${row.website}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-zinc-200 px-3 text-xs font-medium text-zinc-500 transition hover:border-zinc-400 hover:text-zinc-900 active:scale-[0.97]"
                            >
                              <ExternalLink size={12} />
                              Visit site
                            </a>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── SMTP drawer ── */}
      {smtpOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/15 backdrop-blur-[2px]"
          onClick={() => setSmtpOpen(false)}
        >
          <aside
            className="absolute right-0 top-0 h-full w-full max-w-md border-l border-zinc-100 bg-white p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold tracking-tight">
                SMTP setup
              </h2>
              <button
                className="grid size-8 place-items-center rounded-lg border border-zinc-200 text-zinc-400 transition hover:text-zinc-900 active:scale-[0.97]"
                onClick={() => setSmtpOpen(false)}
                aria-label="Close"
              >
                <X size={15} />
              </button>
            </div>
            <div className="mt-6 grid gap-4">
              <label className="text-xs font-medium text-zinc-500">
                Host
                <input
                  className="mt-1.5 h-10 w-full rounded-lg border border-zinc-200 px-3 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                  value={smtpHost}
                  onChange={(e) => setSmtpHost(e.target.value)}
                  placeholder="smtp.gmail.com"
                />
              </label>
              <label className="text-xs font-medium text-zinc-500">
                Port
                <input
                  className="mt-1.5 h-10 w-full rounded-lg border border-zinc-200 px-3 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                  value={smtpPort}
                  onChange={(e) => setSmtpPort(e.target.value)}
                  inputMode="numeric"
                  placeholder="587"
                />
              </label>
              <label className="text-xs font-medium text-zinc-500">
                User
                <input
                  className="mt-1.5 h-10 w-full rounded-lg border border-zinc-200 px-3 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                  value={smtpUser}
                  onChange={(e) => setSmtpUser(e.target.value)}
                  autoComplete="off"
                />
              </label>
              <label className="text-xs font-medium text-zinc-500">
                Password
                <input
                  className="mt-1.5 h-10 w-full rounded-lg border border-zinc-200 px-3 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                  type="password"
                  value={smtpPass}
                  onChange={(e) => setSmtpPass(e.target.value)}
                  autoComplete="new-password"
                />
              </label>
              <label className="text-xs font-medium text-zinc-500">
                From address
                <input
                  className="mt-1.5 h-10 w-full rounded-lg border border-zinc-200 px-3 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                  value={smtpFrom}
                  onChange={(e) => setSmtpFrom(e.target.value)}
                  placeholder="you@company.com"
                />
              </label>
            </div>
            {smtpTestMsg && (
              <p className="mt-3 text-xs font-medium text-zinc-500">{smtpTestMsg}</p>
            )}
            <button
              className="mt-5 h-10 w-full rounded-lg border border-zinc-200 text-sm font-medium transition hover:border-zinc-400 active:scale-[0.97] disabled:opacity-40"
              onClick={doTestSmtp}
              disabled={smtpTesting || !smtpHost}
            >
              {smtpTesting ? "Testing…" : "Test connection"}
            </button>
            <button
              className="mt-3 inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-zinc-900 text-sm font-medium text-white transition active:scale-[0.97] disabled:opacity-40"
              onClick={() => setConfirmOpen(true)}
              disabled={sendableResults.length === 0}
            >
              <Send size={15} />
              Send all ({sendableResults.length})
            </button>
            {sendResult && (
              <p className="mt-3 text-xs font-medium text-zinc-500">{sendResult}</p>
            )}
          </aside>
        </div>
      )}

      {/* ── footer ── */}
      <footer className="font-code relative z-10 mx-auto mt-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-2 px-6 py-6 text-[11px] text-zinc-400 sm:px-10">
        <p>© 2026 opencold</p>
        <div className="flex items-center gap-5">
          <a
            href="https://github.com/mhttekin/opencold"
            target="_blank"
            rel="noopener noreferrer"
            className="transition hover:text-zinc-900"
          >
            github
          </a>
          <a
            href="https://github.com/mhttekin/opencold#readme"
            target="_blank"
            rel="noopener noreferrer"
            className="transition hover:text-zinc-900"
          >
            docs
          </a>
        </div>
      </footer>

      {/* ── confirm dialog ── */}
      {confirmOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/20 backdrop-blur-[2px] p-5">
          <div className="w-full max-w-sm rounded-xl border border-zinc-100 bg-white p-6 shadow-2xl">
            <h2 className="text-lg font-semibold tracking-tight">
              Send {sendableResults.length}{" "}
              {sendableResults.length === 1 ? "email" : "emails"}?
            </h2>
            {skippedCount > 0 && (
              <p className="mt-2 text-sm text-zinc-400">
                {skippedCount} row{skippedCount === 1 ? "" : "s"} with no email or a
                failed draft will be skipped.
              </p>
            )}
            <div className="mt-6 grid grid-cols-2 gap-3">
              <button
                className="h-9 rounded-lg border border-zinc-200 text-sm font-medium active:scale-[0.97] disabled:opacity-40"
                onClick={() => setConfirmOpen(false)}
                disabled={sending}
              >
                Cancel
              </button>
              <button
                className="h-9 rounded-lg bg-zinc-900 text-sm font-medium text-white active:scale-[0.97] disabled:opacity-40"
                onClick={doSend}
                disabled={sending}
              >
                {sending ? "Sending…" : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

/* ── components ── */

function ModeSelector({
  mode,
  onOutreach,
  onDiscovery,
}: {
  mode: Mode;
  onOutreach: () => void;
  onDiscovery: () => void;
}) {
  return (
    <div className="inline-flex items-center gap-1 rounded-xl border border-zinc-200 bg-white/70 p-1 backdrop-blur">
      <ModeButton
        active={mode === "discovery"}
        onClick={onDiscovery}
        icon={<Compass size={14} />}
        label="Discovery"
      />
      <ModeButton
        active={mode === "outreach"}
        onClick={onOutreach}
        icon={<Mail size={14} />}
        label="Outreach"
      />
    </div>
  );
}

function ModeButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex h-9 items-center gap-2 rounded-lg px-4 text-sm font-medium transition active:scale-[0.97] ${
        active
          ? "bg-zinc-900 text-white shadow-sm"
          : "text-zinc-500 hover:text-zinc-900"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function ContactRow({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-start gap-2">
      <span className="mt-0.5 text-zinc-400">{icon}</span>
      <div className="min-w-0">
        <dt className="text-[11px] uppercase tracking-wider text-zinc-400">
          {label}
        </dt>
        <dd className="truncate text-sm text-zinc-700">{value}</dd>
      </div>
    </div>
  );
}

function ProviderFields({
  provider,
  switchProvider,
  apiKey,
  setApiKey,
  selectedModel,
  setSelectedModel,
  customModel,
  setCustomModel,
  modelDropOpen,
  setModelDropOpen,
  proxyUrl,
  setProxyUrl,
  proxyToken,
  setProxyToken,
  proxyModel,
  setProxyModel,
}: {
  provider: ProviderType;
  switchProvider: (p: ProviderType) => void;
  apiKey: string;
  setApiKey: (v: string) => void;
  selectedModel: string;
  setSelectedModel: (v: string) => void;
  customModel: string;
  setCustomModel: (v: string) => void;
  modelDropOpen: boolean;
  setModelDropOpen: (v: boolean) => void;
  proxyUrl: string;
  setProxyUrl: (v: string) => void;
  proxyToken: string;
  setProxyToken: (v: string) => void;
  proxyModel: string;
  setProxyModel: (v: string) => void;
}) {
  return (
    <div className="space-y-3">
      {/* provider tabs */}
      <div className="flex gap-0.5 rounded-md bg-zinc-100 p-0.5">
        {(["anthropic", "openai", "proxy"] as const).map((p) => (
          <button
            key={p}
            className={`flex-1 rounded px-2 py-1 text-[11px] font-semibold tracking-wide transition ${
              provider === p
                ? "bg-white text-zinc-900 shadow-sm"
                : "text-zinc-400 hover:text-zinc-600"
            }`}
            onClick={() => switchProvider(p)}
          >
            {p === "anthropic" ? "Anthropic" : p === "openai" ? "OpenAI" : "Proxy"}
          </button>
        ))}
      </div>

      {/* API key — all providers */}
      <label className="block text-[11px] font-medium text-zinc-400">
        API key
        <input
          type="password"
          className="mt-1 h-9 w-full rounded-lg border border-zinc-200 px-3 text-xs font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
          value={provider === "proxy" ? proxyToken : apiKey}
          onChange={(e) =>
            provider === "proxy"
              ? setProxyToken(e.target.value)
              : setApiKey(e.target.value)
          }
          placeholder={
            provider === "anthropic"
              ? "sk-ant-..."
              : provider === "openai"
                ? "sk-..."
                : "Bearer token"
          }
        />
      </label>

      {provider !== "proxy" ? (
        <>
          {/* model — click to expand inline list */}
          <div>
            <span className="mb-1 block text-[11px] font-medium text-zinc-400">Model</span>
            <button
              className="flex h-9 w-full items-center justify-between rounded-lg border border-zinc-200 px-3 text-xs transition hover:border-zinc-400"
              onClick={() => setModelDropOpen(!modelDropOpen)}
            >
              <span className="font-medium text-zinc-900">
                {selectedModel === "custom"
                  ? customModel || "Custom"
                  : PROVIDER_MODELS[provider].find((m) => m.id === selectedModel)?.label ?? selectedModel}
              </span>
              <ChevronDown
                size={12}
                className={`text-zinc-400 transition-transform ${modelDropOpen ? "rotate-180" : ""}`}
              />
            </button>

            {/* inline options */}
            <div
              className="accordion-body mt-1"
              style={{ gridTemplateRows: modelDropOpen ? "1fr" : "0fr" }}
            >
              <div className="min-h-0 overflow-hidden">
                <div className="space-y-0.5 rounded-lg border border-zinc-100 bg-zinc-50/60 p-1">
                  {PROVIDER_MODELS[provider].map((m) => (
                    <button
                      key={m.id}
                      className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs transition ${
                        selectedModel === m.id
                          ? "bg-white shadow-sm"
                          : "hover:bg-white/60"
                      }`}
                      onClick={() => {
                        setSelectedModel(m.id);
                        setCustomModel("");
                        setModelDropOpen(false);
                      }}
                    >
                      <span className={`font-medium ${selectedModel === m.id ? "text-zinc-900" : "text-zinc-600"}`}>
                        {m.label}
                      </span>
                      <span className="ml-auto font-mono text-[10px] text-zinc-400">
                        {m.id}
                      </span>
                    </button>
                  ))}
                  <button
                    className={`flex w-full items-center rounded-md px-2.5 py-1.5 text-left text-xs transition ${
                      selectedModel === "custom"
                        ? "bg-white shadow-sm"
                        : "hover:bg-white/60"
                    }`}
                    onClick={() => {
                      setSelectedModel("custom");
                      setModelDropOpen(false);
                    }}
                  >
                    <span className={`font-medium ${selectedModel === "custom" ? "text-zinc-900" : "text-zinc-600"}`}>
                      Custom...
                    </span>
                  </button>
                </div>
              </div>
            </div>
          </div>

          {selectedModel === "custom" && (
            <input
              className="h-9 w-full rounded-lg border border-zinc-200 px-3 text-xs text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
              value={customModel}
              onChange={(e) => setCustomModel(e.target.value)}
              placeholder="Custom model ID"
              autoFocus
            />
          )}
        </>
      ) : (
        <>
          <label className="block text-[11px] font-medium text-zinc-400">
            Router URL
            <input
              className="mt-1 h-9 w-full rounded-lg border border-zinc-200 px-3 text-xs font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
              value={proxyUrl}
              onChange={(e) => setProxyUrl(e.target.value)}
              placeholder="https://your-proxy.example.com/v1"
            />
          </label>
          <label className="block text-[11px] font-medium text-zinc-400">
            Model name
            <input
              className="mt-1 h-9 w-full rounded-lg border border-zinc-200 px-3 text-xs font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
              value={proxyModel}
              onChange={(e) => setProxyModel(e.target.value)}
              placeholder="e.g. llama-3.1-70b"
            />
          </label>
        </>
      )}
    </div>
  );
}

function Accordion({
  title,
  badge,
  open,
  onToggle,
  filled,
  children,
}: {
  title: string;
  badge?: string;
  open: boolean;
  onToggle: () => void;
  filled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-zinc-100 bg-zinc-50/50 overflow-hidden">
      <button
        className="flex w-full items-center justify-between px-5 py-4 text-left"
        onClick={onToggle}
      >
        <div className="flex items-center gap-2">
          {filled && (
            <span className="grid size-4 place-items-center rounded-full bg-zinc-900">
              <Check size={10} className="text-white" />
            </span>
          )}
          <span className="text-sm font-semibold text-zinc-700">{title}</span>
          {badge && (
            <span className="rounded-full bg-zinc-200 px-2 py-0.5 text-[10px] font-medium text-zinc-500">
              {badge}
            </span>
          )}
        </div>
        <ChevronDown
          size={14}
          className={`text-zinc-400 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      <div
        className="accordion-body"
        style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="px-5 pb-5">{children}</div>
        </div>
      </div>
    </div>
  );
}

function SidebarToggle({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      className="flex w-full items-center justify-between gap-3 text-left"
      onClick={() => onChange(!checked)}
    >
      <div>
        <p className="text-sm font-medium text-zinc-700">{label}</p>
        <p className="text-xs text-zinc-400">{description}</p>
      </div>
      <span className={`toggle-track ${checked ? "toggle-track--on" : ""}`}>
        <span className="toggle-thumb" />
      </span>
    </button>
  );
}

function DiscoveryHero({
  onStart,
}: {
  onStart: (icp?: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const [copied, setCopied] = useState(false);

  const submit = () => onStart(draft.trim() || undefined);

  const copyInstall = () => {
    navigator.clipboard?.writeText("pip install opencold");
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <section className="relative z-10 mx-auto flex w-full max-w-6xl flex-1 flex-col justify-end px-6 pb-8 pt-4 sm:px-10 lg:min-h-[540px] lg:pb-12">
      {/* ambient discovery graph — full-bleed canvas on desktop, its own
          block below the copy on mobile so nodes never sit behind text */}
      <div className="relative order-last mt-10 h-[330px] w-full lg:absolute lg:inset-0 lg:order-none lg:mt-0 lg:h-auto">
        <DiscoveryGraph />
      </div>

      {/* warm lower wash — an atmospheric stage for the copy, not a
          container: an ellipse anchored at the bottom that dissolves before
          reaching any of its own edges (top, left, and right all fade) */}
      <div
        aria-hidden
        className="pointer-events-none absolute bottom-0 left-[-8%] hidden h-[62%] w-[90%] lg:block"
        style={{
          background:
            "radial-gradient(ellipse 72% 95% at 38% 100%, rgba(248,244,234,0.78), rgba(248,244,234,0.38) 52%, transparent 76%)",
        }}
      />

      {/* editorial poster row: copy bottom-left, CTAs bottom-right */}
      <div className="relative z-10 flex flex-col gap-9 lg:flex-row lg:items-end lg:justify-between lg:gap-12">
        <div className="relative max-w-2xl">
          <motion.h1
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1, duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
            className="text-left text-[clamp(2.1rem,4.5vw,3.4rem)] font-normal leading-[1.08] tracking-tight"
          >
            Two words in.
            <br />
            {/* one soft highlight hugging the full second line; clones per
                line if it ever wraps on small screens */}
            <motion.span
              initial={{ backgroundSize: "0% 30%" }}
              animate={{ backgroundSize: "100% 30%" }}
              transition={{
                delay: 1.0,
                duration: 0.6,
                ease: [0.22, 1, 0.36, 1],
              }}
              className="bg-no-repeat [-webkit-box-decoration-break:clone] [box-decoration-break:clone] sm:whitespace-nowrap"
              style={{
                backgroundImage:
                  "linear-gradient(rgb(167 243 208 / 0.5), rgb(167 243 208 / 0.5))",
                backgroundPosition: "0 88%",
              }}
            >
              Verified companies out.
            </motion.span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              delay: 0.25,
              duration: 0.7,
              ease: [0.22, 1, 0.36, 1],
            }}
            className="mt-5 max-w-md text-left text-[15px] leading-relaxed text-zinc-500"
          >
            Describe your ICP once. OpenCold expands it into local search
            terms, finds real companies, and verifies every match from their
            own websites.
          </motion.p>
        </div>

        <div className="flex w-full max-w-sm flex-col gap-2.5">
          {/* primary CTA — a command/prompt bar: type an ICP, run discovery.
              opacity-only entrance: animating transform here triggers a
              subpixel re-raster snap on retina when the GPU layer is demoted
              at animation end (reads as a one-frame flicker + tiny shift) */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.4, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            className="flex h-[52px] w-full items-center gap-2.5 rounded-2xl border border-zinc-200 bg-white/80 pl-4 pr-2.5 transition-colors focus-within:border-zinc-400"
          >
            <Compass size={14} className="shrink-0 text-zinc-300" />
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submit();
              }}
              placeholder="Describe your ICP…"
              aria-label="Describe your ideal customer profile"
              className="h-full w-full bg-transparent font-sans text-[12.5px] text-zinc-900 outline-none placeholder:text-zinc-400"
            />
            <button
              onClick={submit}
              aria-label="Run discovery"
              className="grid size-8 shrink-0 place-items-center rounded-full bg-zinc-900 text-white transition hover:bg-zinc-700 active:scale-[0.95]"
            >
              <ArrowRight size={14} />
            </button>
          </motion.div>

          {/* secondary — run it locally instead */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.55, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            className="flex h-9 w-full items-center justify-between rounded-lg border border-zinc-200/70 bg-zinc-100/60 pl-3.5 pr-1 font-code text-[11.5px] text-zinc-500"
          >
            <span>
              <span className="text-zinc-400">$ </span>pip install opencold
            </span>
            <button
              onClick={copyInstall}
              aria-label="Copy install command"
              className="grid size-7 shrink-0 place-items-center rounded-md text-zinc-400 transition hover:text-zinc-900"
            >
              {copied ? (
                <Check size={13} className="text-emerald-600" />
              ) : (
                <Clipboard size={13} />
              )}
            </button>
          </motion.div>

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.7, duration: 0.8 }}
            className="font-code text-[10.5px] text-zinc-400"
          >
            no API key needed · open source · searches in any language
          </motion.p>
        </div>
      </div>
    </section>
  );
}

function DropHero({
  onFile,
  hint,
  onHintClear,
}: {
  onFile: (file: File) => void;
  hint: string | null;
  onHintClear: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const errorTimer = useRef<ReturnType<typeof setTimeout>>(null);

  const onDrop = useCallback(
    (accepted: File[], rejected: { file: File }[]) => {
      if (rejected.length > 0) {
        setError("Only .csv files are accepted");
        if (errorTimer.current) clearTimeout(errorTimer.current);
        errorTimer.current = setTimeout(() => {
          setError(null);
          onHintClear();
        }, 3500);
        return;
      }
      if (accepted.length > 0) {
        setError(null);
        onFile(accepted[0]);
      }
    },
    [onFile, onHintClear],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "text/csv": [".csv"] },
    multiple: false,
    noClick: false,
  });

  return (
    <section className="relative z-10 mx-auto grid min-h-[calc(100vh-150px)] w-full max-w-6xl items-center gap-12 px-6 py-10 sm:px-10 lg:grid-cols-[1.25fr_1fr] lg:gap-16">
      {/* ── LEFT: copy + hint ── */}
      <div>
        <h1 className="whitespace-nowrap text-left text-[clamp(2rem,4.5vw,3.5rem)] font-normal leading-[1.08] tracking-tight">
          Cold outreach,
          <br />
          grounded in research.
        </h1>

        <p className="mt-6 max-w-md text-left text-base leading-relaxed text-zinc-500">
          Drop a CSV of companies. OpenCold reads each website, finds the right
          contact, and writes emails that reference real facts.
        </p>

        {/* required columns — hint */}
        <div className="mt-7 flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-zinc-400">
            Required columns
          </span>
          {["Name", "Company"].map((c) => (
            <span
              key={c}
              className="rounded-full border border-zinc-200 bg-white px-3 py-1 text-xs font-medium text-zinc-600"
            >
              {c}
            </span>
          ))}
          <span className="text-xs text-zinc-400">
            — website found automatically
          </span>
        </div>
      </div>

      {/* ── RIGHT: drop zone ── */}
      <div className="w-full">
        <div
          {...getRootProps()}
          className={`dropzone ${isDragActive ? "dropzone--active" : ""}`}
        >
          <input {...getInputProps()} />

          <div className="dropzone-icon">
            <FileSpreadsheet size={22} strokeWidth={1.75} />
          </div>

          <p className="mt-4 text-base font-semibold">
            {isDragActive ? "Drop to start" : "Drop your CSV here"}
          </p>
          <p className="mt-1 text-sm">
            {error ? (
              <span className="font-medium text-red-500">{error}</span>
            ) : hint ? (
              <span className="font-medium text-zinc-500">{hint}</span>
            ) : (
              <span className="text-zinc-400">or click to browse</span>
            )}
          </p>

          {/* upward pull arrow — appears while dragging */}
          <div className="dropzone-pull">
            <ArrowUp size={18} strokeWidth={1.75} />
          </div>
        </div>

        {/* CSV ghost preview — shows the expected shape of the file */}
        <div className="csv-sheet mt-6">
          <div className="csv-header">
            <span>Name</span>
            <span>Company</span>
            <span>Email</span>
          </div>
          <div className="csv-row" />
          <div className="csv-row csv-row--two" />
          <div className="csv-row csv-row--three" />
        </div>
      </div>
    </section>
  );
}

function SkeletonTable() {
  return (
    <div className="mt-6 space-y-3">
      {[0, 1, 2, 3, 4].map((row) => (
        <div
          key={row}
          className="rounded-xl border border-zinc-100 px-5 py-4"
          style={{ animationDelay: `${row * 120}ms` }}
        >
          <div className="flex items-center gap-4">
            <span className="size-2 rounded-full bg-zinc-200 skeleton" />
            <div className="flex-1 space-y-2">
              <span className="block h-3.5 w-3/5 rounded-full bg-zinc-100 skeleton" />
              <span className="block h-2.5 w-2/5 rounded-full bg-zinc-50 skeleton" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
